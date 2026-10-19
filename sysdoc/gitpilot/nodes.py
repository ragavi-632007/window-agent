"""Git Action Graph nodes.

Error Analyzer never executes git.
Supervisor retries via Planner → Permission Gate → Executor.
Executor runs allowlisted tools only through tool_registry / git_ops.
"""
from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Any, Optional, Tuple

from display.animations import (
    agent_log,
    agent_log_err,
    agent_log_ok,
    agent_log_step,
    agent_log_warn,
)

from gitpilot.models import GitErrorAnalysis, GitPlan, GitStep

MAX_CYCLES = 3

_ERROR_RULES = [
    (
        "upstream_missing",
        True,
        "set_upstream",
        [
            r"has no upstream",
            r"no upstream branch",
            r"set the remote as upstream",
            r"The current branch .* has no upstream",
        ],
    ),
    (
        "rejected_non_ff",
        True,
        "pull_rebase_then_push",
        [
            r"non-fast-forward",
            r"fetch first",
            r"\[rejected\]",
            r"failed to push some refs",
            r"Updates were rejected",
            r"have diverged",
        ],
    ),
    (
        "nothing_to_commit",
        True,
        "push_only",
        [r"nothing to commit", r"working tree clean", r"no changes added to commit"],
    ),
    (
        "unstaged",
        True,
        "stage_then_commit",
        [r"nothing added to commit", r"untracked files present", r"did not match any files"],
    ),
    (
        "auth",
        False,
        "auth_help",
        [
            r"authentication failed",
            r"permission denied \(publickey\)",
            r"could not read Username",
            r"HTTP Basic: Access denied",
            r"403 Forbidden",
            r"Support for password authentication was removed",
            r"Repository not found",
        ],
    ),
    (
        "conflict",
        False,
        "conflict_guide",
        [
            r"CONFLICT \(",
            r"fix conflicts",
            r"You must edit all merge conflicts",
            r"unmerged paths",
            r"needs merge",
        ],
    ),
]


def _audit(path: str, step: str, code: int, err: str) -> None:
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        line = (
            f"{datetime.datetime.utcnow().isoformat()}Z | {path} | {step} | "
            f"code={code} | {(err or '')[:200]}\n"
        )
        with open(log_dir / "gitpilot_audit.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _analyze_text(text: str) -> GitErrorAnalysis:
    for category, recoverable, strategy, patterns in _ERROR_RULES:
        for pat in patterns:
            if re.search(pat, text or "", re.I):
                return GitErrorAnalysis(
                    category=category,
                    recoverable=recoverable,
                    strategy_id=strategy,
                    reason=f"Matched {category} → {strategy}",
                )
    return GitErrorAnalysis(
        category="unknown",
        recoverable=True,
        strategy_id="set_upstream",
        reason="Unknown error — try set upstream then push",
    )


def _run_tool(tool_name: str, *args, **kwargs) -> Tuple[str, str, int]:
    """Sole execution gateway — registry first, git_ops fallback."""
    try:
        from gitpilot.tool_registry import get_registry

        reg = get_registry()
        tool = reg.get_tool(tool_name)
        if tool is not None:
            return tool.execute(*args, **kwargs)
    except Exception:
        pass

    from gitpilot import git_ops

    mapping = {
        "git_status": lambda: git_ops.get_status(args[0]),
        "git_log": lambda: git_ops.get_log(args[0], kwargs.get("n", 10)),
        "git_diff": lambda: git_ops.get_diff_full(args[0]),
        "git_stage_all": lambda: git_ops.stage_all(args[0]),
        "git_commit": lambda: git_ops.commit(args[0], kwargs.get("message", "Update")),
        "git_push": lambda: git_ops.push(
            args[0], kwargs.get("branch", "main"), first_push=False
        ),
        "git_push_upstream": lambda: git_ops.push(
            args[0], kwargs.get("branch", "main"), first_push=True
        ),
        "git_pull": lambda: git_ops.pull_rebase(args[0]),
        "git_branch": lambda: git_ops.create_branch(args[0], kwargs.get("name", "feature")),
        "git_checkout": lambda: git_ops.switch_branch(args[0], kwargs.get("name", "main")),
        "git_merge": lambda: git_ops.merge_branch(args[0], kwargs.get("branch", "main")),
        "git_stash": lambda: git_ops.stash_save(args[0], kwargs.get("message", "")),
        "git_stash_pop": lambda: git_ops.stash_apply(args[0], 0),
        "git_clone": lambda: git_ops.clone_repo(kwargs.get("url", ""), kwargs.get("dest", ".")),
        "git_remote": lambda: git_ops.get_remote(args[0]),
    }
    fn = mapping.get(tool_name)
    if not fn:
        return "", f"blocked tool: {tool_name}", 1
    return fn()


# ── Nodes ─────────────────────────────────────────────────────────────────

def resolve_repo_node(state: dict) -> dict:
    from gitpilot import git_ops
    from gitpilot import shared_state

    agent_log("GitResolver", "Resolving repository path...")
    path = (
        state.get("repo_path")
        or state.get("preferred_path")
        or shared_state.get_last_repo_path()
        or os.getcwd()
    )
    path = os.path.abspath(os.path.expanduser(str(path)))

    if not git_ops.is_git_repo(path):
        cur = path
        found = None
        for _ in range(10):
            if git_ops.is_git_repo(cur):
                found = cur
                break
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
        if found:
            path = found
        else:
            agent_log_warn(f"Not a git repo: {path}")
            return {"repo_path": path, "repo_ok": False}

    shared_state.set_last_repo_path(path)
    agent_log_ok(f"Repo: {path}")
    return {"repo_path": path, "repo_ok": True}


def inspect_node(state: dict) -> dict:
    from gitpilot import git_ops
    from gitpilot import shared_state

    path = state.get("repo_path") or os.getcwd()
    agent_log("Inspector", f"Inspecting {path}")
    if not state.get("repo_ok", True):
        return {"inspect": {"error": "not_a_repo"}}

    branch = git_ops.get_branch(path)
    st_out, _, _ = git_ops.get_status_short(path)
    remote_out, _, _ = git_ops.get_remote(path)
    inspect = {
        "branch": branch,
        "status_short": (st_out or "").strip(),
        "remote": (remote_out or "").strip(),
        "has_staged": git_ops.has_staged_changes(path),
        "has_commits": git_ops.has_commits(path),
        "dirty": bool((st_out or "").strip()),
    }
    shared_state.update_from_inspect(path, inspect)
    agent_log_step(
        f"branch={branch} dirty={inspect['dirty']} staged={inspect['has_staged']}"
    )
    return {"inspect": inspect}


def planner_node(state: dict) -> dict:
    agent_log("Planner", "Building allowlisted git plan...")
    cycle = int(state.get("planning_cycle") or 1)
    query = (state.get("user_query") or "").lower()
    inspect = state.get("inspect") or {}
    branch = inspect.get("branch") or "main"
    hint = state.get("strategy_hint") or ""
    kind = state.get("git_kind") or ""
    tried = set(state.get("attempts_made") or [])
    steps: list[GitStep] = []

    # Recovery plans from Error Analyzer (via Supervisor) — never executed here
    if hint == "set_upstream":
        steps = [
            GitStep(
                name="push_upstream",
                risk="medium",
                args={"branch": branch},
                description=f"push -u origin {branch}",
            )
        ]
    elif hint == "pull_rebase_then_push":
        steps = [
            GitStep(name="pull_rebase", risk="medium", description="pull --rebase"),
            GitStep(
                name="push",
                risk="medium",
                args={"branch": branch},
                description="push",
            ),
        ]
    elif hint == "push_only":
        steps = [
            GitStep(
                name="push",
                risk="medium",
                args={"branch": branch},
                description="push only",
            )
        ]
    elif hint == "stage_then_commit":
        msg = state.get("commit_message") or "Update files"
        steps = [
            GitStep(name="stage_all", risk="medium", description="git add ."),
            GitStep(
                name="commit",
                risk="medium",
                args={"message": msg},
                description=f'commit -m "{msg[:50]}"',
            ),
            GitStep(
                name="push_upstream",
                risk="medium",
                args={"branch": branch},
                description=f"push -u origin {branch}",
            ),
        ]
    else:
        # Initial plan from kind / query
        if kind == "clone" or "clone" in query:
            m = re.search(r"(https?://\S+|git@\S+)", state.get("user_query") or "")
            url = m.group(1) if m else ""
            dest = state.get("clone_dest") or os.getcwd()
            steps = [
                GitStep(
                    name="clone",
                    risk="medium",
                    args={"url": url, "dest": dest},
                    description=f"git clone {url or '<url>'}",
                )
            ]
        elif kind == "merge" or "merge" in query:
            m = re.search(r"merge\s+(\S+)", query)
            other = m.group(1) if m else ""
            steps = [
                GitStep(
                    name="merge",
                    risk="medium",
                    args={"branch": other},
                    description=f"merge {other or '<branch>'}",
                )
            ]
        elif kind == "stash" or "stash" in query:
            if "pop" in query or "apply" in query:
                steps = [
                    GitStep(name="stash_pop", risk="medium", description="stash pop")
                ]
            else:
                steps = [
                    GitStep(name="stash_save", risk="medium", description="stash save")
                ]
        elif kind == "branch" or "branch" in query:
            m = re.search(r"branch\s+([A-Za-z0-9._/\-]+)", query)
            bname = m.group(1) if m else "feature/new"
            steps = [
                GitStep(
                    name="create_branch",
                    risk="medium",
                    args={"name": bname},
                    description=f"branch {bname}",
                ),
                GitStep(
                    name="checkout",
                    risk="medium",
                    args={"name": bname},
                    description=f"checkout {bname}",
                ),
            ]
        elif kind == "pull" or (
            any(w in query for w in ("pull", "sync from")) and "push" not in query
        ):
            steps = [
                GitStep(name="pull_rebase", risk="medium", description="pull --rebase")
            ]
        else:
            msg = state.get("commit_message")
            if not msg:
                try:
                    from gitpilot import git_ops
                    from gitpilot.ai_helper import generate_commit_message

                    path = state.get("repo_path") or "."
                    st, _, _ = git_ops.get_status(path)
                    dn, _, _ = git_ops.get_diff_names(path)
                    msg = (
                        generate_commit_message(st or "", dn or "")
                        or "Update project files"
                    )
                except Exception:
                    msg = "Update project files"
            if inspect.get("dirty") or kind in ("commit", "push", "") or any(
                w in query for w in ("commit", "push", "save")
            ):
                steps.append(
                    GitStep(name="stage_all", risk="medium", description="git add .")
                )
                steps.append(
                    GitStep(
                        name="commit",
                        risk="medium",
                        args={"message": msg},
                        description=f'commit -m "{msg[:50]}"',
                    )
                )
            if kind == "push" or "push" in query or "github" in query or not kind:
                steps.append(
                    GitStep(
                        name="push_upstream",
                        risk="medium",
                        args={"branch": branch},
                        description=f"push -u origin {branch}",
                    )
                )

    sig = "+".join(s.name for s in steps)
    if sig in tried and cycle > 1 and not hint:
        steps = [
            GitStep(
                name="push_upstream",
                risk="medium",
                args={"branch": branch},
                description=f"push -u origin {branch}",
            )
        ]

    plan = GitPlan(
        goal=state.get("user_query") or "Git operation",
        reasoning=f"cycle={cycle} hint={hint or 'none'} kind={kind} branch={branch}",
        steps=steps,
        risk="medium",
        strategy_hint=hint or None,
        planning_cycle=cycle,
    )
    agent_log_ok(f"Plan: {' → '.join(s.name for s in steps) or '(empty)'}")
    for s in steps:
        agent_log_step(f"  • {s.name}: {s.description or s.name}")
    return {"git_plan": plan.model_dump(), "commit_message": state.get("commit_message")}


def permission_gate_node(state: dict) -> dict:
    plan = state.get("git_plan") or {}
    steps = plan.get("steps") or []
    cycle = int(state.get("planning_cycle") or 1)
    sig = "+".join(
        (s.get("name") if isinstance(s, dict) else s.name) for s in steps
    )
    hint = state.get("strategy_hint") or ""

    for s in steps:
        risk = s.get("risk") if isinstance(s, dict) else "medium"
        name = s.get("name") if isinstance(s, dict) else getattr(s, "name", "")
        if risk == "high" or name in ("reset_hard", "push_force", "delete_branch"):
            agent_log_warn("High-risk step blocked — use fixgit UI")
            return {"approved": False, "gate_choice": "blocked_high_risk"}

    if state.get("auto_approve"):
        return {"approved": True, "gate_choice": "y", "last_approved_sig": sig}

    if cycle > 1 and hint in (
        "set_upstream",
        "push_only",
        "stage_then_commit",
        "pull_rebase_then_push",
    ) and state.get("gate_choice") in ("y", "yes"):
        agent_log_ok(f"PermissionGate reusing approval for recovery `{hint}`")
        return {"approved": True, "gate_choice": "y", "last_approved_sig": sig}

    agent_log("PermissionGate", "Awaiting approval...")
    try:
        from rich.console import Console

        console = Console()
        console.print("  [bold]Git plan[/bold]")
        for s in steps:
            name = s.get("name") if isinstance(s, dict) else s.name
            desc = (
                s.get("description")
                if isinstance(s, dict)
                else getattr(s, "description", "")
            )
            console.print(f"    • {name}: {desc}")
        console.print(f"  Repo: {state.get('repo_path')}")
        if hint:
            console.print(f"  [dim]Recovery: {hint}[/dim]")
        console.print("  Proceed? [y/N]: ", end="")
        choice = input().strip().lower()
    except Exception:
        choice = "n"

    ok = choice in ("y", "yes")
    (agent_log_ok if ok else agent_log_warn)(
        "PermissionGate approved" if ok else "PermissionGate denied"
    )
    return {
        "approved": ok,
        "gate_choice": choice or "n",
        "last_approved_sig": sig if ok else state.get("last_approved_sig") or "",
    }


def executor_node(state: dict) -> dict:
    if not state.get("approved"):
        return {
            "step_results": [],
            "last_error": "not_approved",
            "executor_ok": False,
        }

    path = state.get("repo_path") or "."
    plan = state.get("git_plan") or {}
    steps = plan.get("steps") or []
    results = []
    last_error = ""
    ok_all = True
    branch = (state.get("inspect") or {}).get("branch") or "main"

    # step name → registry tool
    tool_map = {
        "status": ("git_status", lambda a: _run_tool("git_status", path)),
        "log": ("git_log", lambda a: _run_tool("git_log", path)),
        "diff": ("git_diff", lambda a: _run_tool("git_diff", path)),
        "remote": ("git_remote", lambda a: _run_tool("git_remote", path)),
        "stage_all": ("git_stage_all", lambda a: _run_tool("git_stage_all", path)),
        "commit": (
            "git_commit",
            lambda a: _run_tool(
                "git_commit",
                path,
                message=a.get("message")
                or state.get("commit_message")
                or "Update",
            ),
        ),
        "push": (
            "git_push",
            lambda a: _run_tool(
                "git_push", path, branch=a.get("branch") or branch
            ),
        ),
        "push_upstream": (
            "git_push_upstream",
            lambda a: _run_tool(
                "git_push_upstream", path, branch=a.get("branch") or branch
            ),
        ),
        "pull_rebase": ("git_pull", lambda a: _run_tool("git_pull", path)),
        "create_branch": (
            "git_branch",
            lambda a: _run_tool("git_branch", path, name=a.get("name") or "feature"),
        ),
        "checkout": (
            "git_checkout",
            lambda a: _run_tool(
                "git_checkout", path, name=a.get("name") or branch
            ),
        ),
        "merge": (
            "git_merge",
            lambda a: _run_tool(
                "git_merge", path, branch=a.get("branch") or ""
            ),
        ),
        "stash_save": (
            "git_stash",
            lambda a: _run_tool("git_stash", path, message=a.get("message") or ""),
        ),
        "stash_pop": ("git_stash_pop", lambda a: _run_tool("git_stash_pop", path)),
        "clone": (
            "git_clone",
            lambda a: _run_tool(
                "git_clone",
                path,
                url=a.get("url") or "",
                dest=a.get("dest") or path,
            ),
        ),
    }

    agent_log("Executor", f"Running {len(steps)} step(s) via registry...")

    for s in steps:
        name = s.get("name") if isinstance(s, dict) else s.name
        args = (s.get("args") if isinstance(s, dict) else s.args) or {}
        agent_log_step(f"exec {name}")
        entry = tool_map.get(name)
        if not entry:
            out, err, code = "", f"blocked tool: {name}", 1
        else:
            try:
                out, err, code = entry[1](args)
            except Exception as exc:
                out, err, code = "", str(exc), 1

        _audit(path, name, code, err or out or "")
        results.append(
            {"name": name, "code": code, "stdout": out or "", "stderr": err or ""}
        )
        if code != 0:
            ok_all = False
            last_error = (err or out or f"exit {code}").strip()
            agent_log_err(f"{name} failed: {last_error[:200]}")
            break
        agent_log_ok(f"{name} ok")

    attempts = list(state.get("attempts_made") or [])
    attempts.append(
        "+".join(s.get("name") if isinstance(s, dict) else s.name for s in steps)
    )
    return {
        "step_results": results,
        "last_error": last_error,
        "executor_ok": ok_all,
        "attempts_made": attempts,
    }


def verifier_node(state: dict) -> dict:
    from gitpilot import git_ops

    path = state.get("repo_path") or "."
    agent_log("Verifier", "Checking outcome...")
    if not state.get("executor_ok"):
        return {
            "verification": {
                "success": False,
                "summary": f"Executor failed: {state.get('last_error') or 'unknown'}",
            }
        }
    st, _, _ = git_ops.get_status_short(path)
    branch = git_ops.get_branch(path)
    summary = f"branch={branch} status={(st or '').strip()[:120] or 'clean'}"
    agent_log_ok(summary)
    return {
        "verification": {"success": True, "summary": summary},
        "inspect_after": {"branch": branch, "status_short": st},
    }


def error_analyzer_node(state: dict) -> dict:
    """Classify failure → strategy_id only. Does NOT run git."""
    agent_log("ErrorAnalyzer", "Classifying failure (no execution)...")
    if (state.get("verification") or {}).get("success"):
        return {
            "error_analysis": {
                "category": "none",
                "recoverable": False,
                "strategy_id": "none",
                "reason": "success",
            }
        }

    err = state.get("last_error") or ""
    for r in state.get("step_results") or []:
        err += "\n" + (r.get("stderr") or "") + "\n" + (r.get("stdout") or "")

    analysis = _analyze_text(err)

    # Richer tips for auth / conflict (still no execution)
    if analysis.strategy_id == "auth_help":
        analysis.reason += (
            " | Fix: gh auth login  OR  SSH key in GitHub  OR  PAT as password"
        )
    if analysis.strategy_id == "conflict_guide":
        analysis.reason += (
            " | Fix: resolve conflict files → git add → git rebase --continue "
            "(or open fixgit)"
        )

    agent_log_warn(
        f"{analysis.category} → {analysis.strategy_id} recoverable={analysis.recoverable}"
    )
    return {"error_analysis": analysis.model_dump()}


def supervisor_node(state: dict) -> dict:
    ver = state.get("verification") or {}
    analysis = state.get("error_analysis") or {}
    cycle = int(state.get("planning_cycle") or 1)

    if ver.get("success"):
        agent_log_ok("Supervisor: SUCCESS")
        return {
            "supervisor_decision": {
                "action": "success",
                "reason": ver.get("summary") or "ok",
            }
        }

    strategy = analysis.get("strategy_id") or "escalate"
    recoverable = bool(analysis.get("recoverable"))

    if strategy in ("auth_help", "conflict_guide", "escalate"):
        agent_log_warn("Supervisor: ESCALATE")
        return {
            "supervisor_decision": {
                "action": "escalate",
                "reason": analysis.get("reason") or strategy,
            },
            "strategy_hint": strategy,
        }

    if recoverable and cycle < MAX_CYCLES:
        agent_log_warn(f"Supervisor: RETRY cycle {cycle + 1} strategy={strategy}")
        return {
            "supervisor_decision": {
                "action": "retry",
                "reason": f"retry with {strategy}",
            },
            "strategy_hint": strategy,
            "planning_cycle": cycle + 1,
            "step_results": [],
            "last_error": "",
            "verification": None,
            "approved": False,
        }

    agent_log_err("Supervisor: ESCALATE (cycles exhausted)")
    return {
        "supervisor_decision": {
            "action": "escalate",
            "reason": "cycles exhausted",
        }
    }


def report_node(state: dict) -> dict:
    dec = state.get("supervisor_decision") or {}
    action = dec.get("action") or "escalate"
    ver = state.get("verification") or {}
    analysis = state.get("error_analysis") or {}

    if action == "success" or ver.get("success"):
        summary = ver.get("summary") or "Git operation completed successfully."
        agent_log_ok(summary)
        return {
            "report": {
                "ok": True,
                "summary": summary,
                "offer_fixgit": False,
                "tip": "",
            }
        }

    reason = dec.get("reason") or analysis.get("reason") or "Git agent could not finish"
    strategy = analysis.get("strategy_id") or state.get("strategy_hint") or ""
    tips = {
        "auth_help": (
            "GitHub auth failed (browser localhost often breaks). "
            "FixBot can open the Auth Helper next."
        ),
        "conflict_guide": (
            "Merge/rebase conflict. Edit conflicted files, git add them, "
            "then git rebase --continue (or git merge --continue). Or type fixgit."
        ),
        "escalate": "Open fixgit for the guided GitPilot coach.",
    }
    tip = tips.get(strategy, "Type fixgit for guided GitPilot UI.")
    agent_log_warn(reason)
    return {
        "report": {
            "ok": False,
            "summary": reason,
            "strategy": strategy,
            "offer_fixgit": True,
            "offer_auth_helper": strategy == "auth_help",
            "tip": tip,
        }
    }


def route_supervisor(state: dict) -> str:
    action = (state.get("supervisor_decision") or {}).get("action") or "escalate"
    if action == "retry":
        return "retry"
    return "report"
