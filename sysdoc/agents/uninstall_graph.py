"""UNINSTALL domain subgraph.

Flow (via build_action_graph):
    START → planner → permission_gate (HIGH-RISK: per-package y/n) → resolve_gate
         → [action_executor | ticket | skip]
    action_executor → action_verifier → error_analyzer → action_supervisor
         → [finalize_success → END
            | retry_new_cycle → start_new_cycle → planner  (loops)
            | escalate → END]

Risk level: HIGH.
The permission gate shows a preview of every package that will be removed
(name, id, installed version, install date) and requires an explicit y/n
per package.  Only packages the user approved proceed to the Executor.

Strategy escalation chain for UNINSTALL:
    uninstall → force_uninstall → purge_uninstall

Verifier confirms absence: each package must no longer appear in
`winget list --id <id>` output after execution.
"""
from __future__ import annotations

import shutil
import subprocess

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from action_graph import build_action_graph
from action_graph.models import UninstallPlan, UninstallTarget
from action_graph.nodes.supervisor import DEFAULT_MAX_PLANNING_CYCLES
from action_graph.nodes.verifier import winget_absence_validator
from agents.fix_registry import known_fix_ids
from display.animations import agent_log_step, log_ok

# Strategy escalation chain for UNINSTALL
_UNINSTALL_STRATEGY_CHAIN = [
    "uninstall",
    "uninstall_user_scope",  # handles Admin + per-user packages
    "force_uninstall",
    "purge_uninstall",
]

UNINSTALL_PLANNER_PROMPT = """You are the UNINSTALL planner for Fixbot, a Windows system support AI.

The user wants to remove software from their system.
You have list_installed_packages and search_installed_package tools.

Your job:
1. Search for the package(s) the user named using search_installed_package.
2. For each match found, produce an UninstallTarget with:
   - name:              human-readable name
   - id:                exact winget package ID
   - manager:           "winget" (or "pip"/"npm" for libraries)
   - installed_version: currently installed version
   - install_date:      install date if available, else ""
   - data_removal:      ALWAYS False unless the user explicitly said "also remove
                        my data / settings / config". Never set True otherwise.
3. Produce exactly ONE UninstallPlan with:
   - goal:     "Uninstall <names>"
   - domain:   "UNINSTALL"
   - packages: list of UninstallTarget objects (one per package to remove)
   - strategy: ALWAYS "uninstall" unless prior_failure_context says to escalate
   - reasoning: why you identified these packages

IMPORTANT:
- NEVER guess or hallucinate package IDs — only use results from search_installed_package.
- If the user named multiple packages, include all of them.
- If a package is not found, explain in reasoning and set packages to [].
- data_removal must remain False unless the user explicitly requested data removal.
- If prior_failure_context or strategy in the plan says to escalate,
  use uninstall_user_scope, force_uninstall, or purge_uninstall accordingly.

Known strategies for UNINSTALL (in escalation order): {known_fixes}"""


def _make_uninstall_tools(updater) -> list:
    """Build read-only tools for the UNINSTALL planner."""
    from langchain_core.tools import tool

    @tool
    def list_installed_packages(manager: str = "winget") -> list:
        """List all installed packages for the given manager ('winget', 'pip', 'npm').
        Returns list of dicts with keys: name, id, version, manager."""
        if manager == "winget" and shutil.which("winget"):
            try:
                proc = subprocess.run(
                    ["winget", "list", "--accept-source-agreements"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30,
                )
                return _parse_winget_list(proc.stdout)
            except Exception:
                return []
        return []

    @tool
    def search_installed_package(query: str) -> list:
        """Search installed packages for a name query.
        Returns list of dicts: name, id, version, manager.
        Use this to resolve the user's app name to the exact installed package ID."""
        results = []
        if shutil.which("winget"):
            try:
                proc = subprocess.run(
                    ["winget", "list", "--name", query, "--accept-source-agreements"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=20,
                )
                results.extend(_parse_winget_list(proc.stdout))
            except Exception:
                pass
        # Also search pip
        if shutil.which("pip"):
            try:
                proc = subprocess.run(
                    ["pip", "show", query], capture_output=True, text=True, timeout=10,
                )
                if proc.returncode == 0:
                    lines = {
                        k.lower(): v.strip()
                        for line in proc.stdout.splitlines()
                        if ":" in line
                        for k, v in [line.split(":", 1)]
                    }
                    if lines.get("name"):
                        results.append({
                            "name":    lines["name"],
                            "id":      lines["name"],
                            "version": lines.get("version", ""),
                            "manager": "pip",
                        })
            except Exception:
                pass
        return [r for r in results if query.lower() in r.get("name", "").lower()
                or query.lower() in r.get("id", "").lower()]

    return [list_installed_packages, search_installed_package]


def _parse_winget_list(stdout: str) -> list[dict]:
    """Parse `winget list` tabular output into dicts using column offsets."""
    lines = stdout.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "Name" in line and "Id" in line:
            header_idx = i
            break
    if header_idx is None:
        return []

    header = lines[header_idx]
    # Find start positions of columns
    col_starts: list[int] = []
    for word in ("Name", "Id", "Version", "Source"):
        idx = header.find(word)
        if idx != -1:
            col_starts.append(idx)
    col_starts = sorted(col_starts)

    if len(col_starts) < 2:
        return []

    results = []
    for line in lines[header_idx + 2:]:   # skip header + separator
        stripped = line.strip()
        if not stripped:
            continue
        if all(c in ("-", "─", " ") for c in line):
            continue

        fields = []
        for k, start in enumerate(col_starts):
            end = col_starts[k + 1] if k + 1 < len(col_starts) else len(line)
            value = line[start:end].strip() if start < len(line) else ""
            fields.append(value)

        if len(fields) >= 2 and fields[0] and fields[1]:
            results.append({
                "name":    fields[0],
                "id":      fields[1],
                "version": fields[2] if len(fields) > 2 else "",
                "manager": "winget",
            })
    return results


def _make_uninstall_planner_node(updater, llm: BaseChatModel):
    """Build the UNINSTALL planner node."""
    tools = _make_uninstall_tools(updater)

    def uninstall_planner_node(state: dict) -> dict:
        cycle = state.get("planning_cycle", 1)
        existing_plan = state.get("action_plan") or {}
        forced_strategy = existing_plan.get("strategy") if cycle > 1 else None

        # Prefer winget search without LLM when user named an app
        user_text = ""
        for m in reversed(state.get("messages") or []):
            c = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
            if isinstance(c, str) and c.strip():
                user_text = c.strip()
                break
        name = user_text.lower().replace("uninstall", "").replace("remove", "").strip()

        if name and cycle == 1 and not forced_strategy:
            try:
                hits = updater.search_package(name) if hasattr(updater, "search_package") else []
            except Exception:
                hits = []
            if hits:
                pkg = hits[0]
                from action_graph.models import UninstallPlan, UninstallTarget
                plan_dict = {
                    "goal": f"Uninstall {pkg.get('name') or name}",
                    "domain": "UNINSTALL",
                    "packages": [{
                        "name": pkg.get("name") or name,
                        "id": pkg.get("id") or "",
                        "manager": pkg.get("manager") or "winget",
                    }],
                    "strategy": "uninstall",
                    "reasoning": "winget search (no LLM)",
                    "planning_cycle": cycle,
                }
                log_ok(f"🧠 Planner  Uninstall plan — [{pkg.get('name')}], no LLM")
                return {
                    "messages": state.get("messages") or [],
                    "action_plan": plan_dict,
                    "uninstall_plan": plan_dict,
                }

        # Lazy LLM only if needed
        try:
            from langchain.agents import create_agent
            agent = create_agent(
                model=llm,
                tools=tools,
                response_format=UninstallPlan,
                system_prompt=UNINSTALL_PLANNER_PROMPT.format(
                    known_fixes=_UNINSTALL_STRATEGY_CHAIN
                ),
            )
            agent_log_step(
                f"🧠 Planner  Identifying package(s) to remove"
                + (f" (cycle {cycle}, strategy: {forced_strategy})" if cycle > 1 else "") + "..."
            )
            result = agent.invoke({"messages": state.get("messages", [])})
            plan: UninstallPlan = result["structured_response"]
            messages = result["messages"]
        except Exception as exc:
            from display.animations import agent_log_warn
            agent_log_warn(f"Uninstall LLM unavailable ({exc})")
            plan = UninstallPlan(
                goal=f"Uninstall {name or 'packages'}",
                packages=[],
                strategy=forced_strategy or "uninstall",
                reasoning=f"LLM failure fallback: {exc}",
            )
            messages = state.get("messages") or []

        if cycle == 1 and plan.strategy not in _UNINSTALL_STRATEGY_CHAIN:
            plan = plan.model_copy(update={"strategy": "uninstall"})
        if forced_strategy and forced_strategy in _UNINSTALL_STRATEGY_CHAIN:
            plan = plan.model_copy(update={"strategy": forced_strategy})
        plan = plan.model_copy(update={"planning_cycle": cycle})

        names = ", ".join(p.name for p in plan.packages) or "none found"
        log_ok(
            f"🧠 Planner  Uninstall plan ready — [{names}], "
            f"strategy: {plan.strategy}"
        )

        action_plan = {
            **plan.model_dump(),
            "domain":      "UNINSTALL",
            "target_name": names,
            "target_id":   "",    # per-package in packages list
            "manager":     "winget",
            "risk_level":  "high",
        }
        return {
            "messages":    messages,
            "action_plan": action_plan,
        }

    return uninstall_planner_node


def build_uninstall_subgraph(
    updater,
    read_tools: list,        # kept for API symmetry; UNINSTALL uses its own tools
    llm: BaseChatModel,
    checkpoint_db_path: str = "sysdoc/memory/fixbot_state.db",
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
):
    """Build and compile the UNINSTALL domain subgraph.

    Uses the high-risk permission gate (per-package y/n preview).
    """
    return build_action_graph(
        domain             = "UNINSTALL",
        planner_node       = _make_uninstall_planner_node(updater, llm),
        executor_obj       = updater,
        validator_fn       = winget_absence_validator,
        llm                = llm,
        permission_display = "high_risk",
        strategy_chain     = _UNINSTALL_STRATEGY_CHAIN,
        checkpoint_db_path = checkpoint_db_path,
        max_planning_cycles = max_planning_cycles,
    )
