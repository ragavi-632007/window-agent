"""UPDATE domain — no eager langchain.agents / transformers import."""
from __future__ import annotations

from typing import Any

from action_graph import build_action_graph
from action_graph.models import UpdatePlan, UpdateTarget
from action_graph.nodes.supervisor import DEFAULT_MAX_PLANNING_CYCLES
from action_graph.nodes.verifier import winget_version_validator
from display.animations import agent_log_step, agent_log_warn, log_ok

_UPDATE_STRATEGY_CHAIN = [
    "standard_upgrade",
    "force_upgrade",
    "reinstall",
    "purge_reinstall",
]


def _scan_updates(updater) -> list[dict]:
    """Deterministic scan — no LLM."""
    try:
        if hasattr(updater, "scan_all"):
            return list(updater.scan_all() or [])
        if hasattr(updater, "scan_winget"):
            return list(updater.scan_winget() or [])
    except Exception as exc:
        agent_log_warn(f"Update scan failed: {exc}")
    return []


def _make_update_planner_node(read_tools: list, llm: Any):
    def update_planner_node(state: dict) -> dict:
        cycle = int(state.get("planning_cycle") or 1)
        target_pkgs = state.get("target_packages")
        existing = state.get("action_plan") or state.get("update_plan") or {}
        forced = existing.get("strategy") if cycle > 1 else None
        strategy = forced or ("standard_upgrade" if cycle == 1 else "force_upgrade")
        if strategy not in _UPDATE_STRATEGY_CHAIN:
            strategy = "standard_upgrade"

        # 1) Manual selection from menu — no LLM
        if target_pkgs:
            packages = [
                UpdateTarget(
                    name=p["name"],
                    id=p["id"],
                    manager=p.get("manager", "winget"),
                    from_version=p.get("from", p.get("from_version", "")),
                    to_version=p.get("to", p.get("to_version", "")),
                )
                for p in target_pkgs
            ]
            plan = UpdatePlan(
                goal=f"Update {', '.join(p.name for p in packages)}",
                packages=packages,
                strategy=strategy,
                reasoning="User selected packages from scan list.",
                max_attempts=3,
                planning_cycle=cycle,
            )
            log_ok(
                f"🧠 Planner  Manual plan — {len(plan.packages)} pkg(s), strategy={strategy}"
            )
        else:
            # 2) Deterministic winget scan — no create_agent
            agent_log_step("🧠 Planner  Scanning for available updates...")
            scanned = _scan_updates(
                # recover updater from tools if needed
                getattr(read_tools, "__self__", None)
            )
            # Prefer updater passed via state or rebuild
            if not scanned:
                try:
                    from modules.updater import UpdateScanner
                    scanned = _scan_updates(UpdateScanner())
                except Exception:
                    scanned = []

            packages = []
            for p in scanned[:20]:
                packages.append(
                    UpdateTarget(
                        name=p.get("name") or p.get("id") or "?",
                        id=p.get("id") or "",
                        manager=p.get("manager") or "winget",
                        from_version=p.get("from") or p.get("from_version") or "",
                        to_version=p.get("to") or p.get("to_version") or "latest",
                    )
                )

            # 3) Optional LLM only if scan empty AND llm provided (lazy import)
            if not packages and llm is not None:
                try:
                    from langchain.agents import create_agent
                    from action_graph.models import UpdatePlan as UP

                    agent = create_agent(
                        model=llm,
                        tools=read_tools,
                        response_format=UP,
                        system_prompt=(
                            "Produce an UpdatePlan for the user's update request. "
                            f"Strategies: {_UPDATE_STRATEGY_CHAIN}"
                        ),
                    )
                    result = agent.invoke({"messages": state.get("messages") or []})
                    plan = result["structured_response"]
                    if forced:
                        plan = plan.model_copy(update={"strategy": forced})
                    plan = plan.model_copy(update={"planning_cycle": cycle})
                    plan_dict = plan.model_dump()
                    log_ok(
                        f"🧠 Planner  LLM plan — {len(plan.packages)} pkg(s), "
                        f"strategy={plan.strategy}"
                    )
                    return {
                        "messages": result.get("messages") or state.get("messages") or [],
                        "action_plan": {
                            **plan_dict,
                            "domain": "UPDATE",
                            "target_name": plan.goal,
                            "target_id": "",
                            "manager": "winget",
                            "risk_level": "low",
                        },
                        "update_plan": plan_dict,
                        "repair_plan": {
                            "goal": plan.goal,
                            "root_cause": f"{len(plan.packages)} package(s) have updates",
                            "confidence": 1.0,
                            "primary_fix": {"id": plan.strategy, "risk": "low"},
                            "fallbacks": [],
                            "reasoning": plan.reasoning,
                            "verification": ["version_check"],
                            "max_attempts": plan.max_attempts,
                            "planning_cycle": cycle,
                            "packages": [p.model_dump() for p in plan.packages],
                        },
                    }
                except Exception as exc:
                    agent_log_warn(f"Planner LLM skipped ({exc})")

            plan = UpdatePlan(
                goal="Update available packages" if packages else "No updates found",
                packages=packages,
                strategy=strategy,
                reasoning="Deterministic winget/pip/npm scan",
                max_attempts=3,
                planning_cycle=cycle,
            )
            log_ok(
                f"🧠 Planner  Scan plan — {len(plan.packages)} pkg(s), strategy={strategy}"
            )

        plan = plan.model_copy(update={"planning_cycle": cycle})
        plan_dict = plan.model_dump()
        return {
            "messages": state.get("messages") or [],
            "action_plan": {
                **plan_dict,
                "domain": "UPDATE",
                "target_name": plan.goal,
                "target_id": "",
                "manager": "winget",
                "risk_level": "low",
            },
            "update_plan": plan_dict,
            "repair_plan": {
                "goal": plan.goal,
                "root_cause": f"{len(plan.packages)} package(s) have updates available",
                "confidence": 1.0,
                "primary_fix": {"id": plan.strategy, "risk": "low"},
                "fallbacks": [],
                "reasoning": plan.reasoning,
                "verification": ["version_check"],
                "max_attempts": plan.max_attempts,
                "planning_cycle": cycle,
                "packages": [p.model_dump() for p in plan.packages],
            },
        }

    return update_planner_node


def build_update_subgraph(
    updater,
    read_tools: list,
    llm: Any,
    checkpoint_db_path: str = "sysdoc/memory/fixbot_state.db",
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
):
    # Bind updater into planner via wrapper
    inner = _make_update_planner_node(read_tools, llm)

    def planner_with_updater(state: dict) -> dict:
        # Prefer scan via the real updater instance
        if not state.get("target_packages"):
            try:
                scanned = _scan_updates(updater)
                if scanned and not state.get("target_packages"):
                    # leave for inner to scan again; inject for speed
                    state = {**state, "_scanned_cache": scanned}
            except Exception:
                pass
        # Patch: if inner would rescan empty, use cache
        out = inner(state)
        if not (out.get("update_plan") or {}).get("packages"):
            cached = state.get("_scanned_cache") or _scan_updates(updater)
            if cached:
                packages = [
                    UpdateTarget(
                        name=p.get("name") or "?",
                        id=p.get("id") or "",
                        manager=p.get("manager") or "winget",
                        from_version=p.get("from") or p.get("from_version") or "",
                        to_version=p.get("to") or p.get("to_version") or "latest",
                    )
                    for p in cached[:20]
                ]
                plan = UpdatePlan(
                    goal="Update available packages",
                    packages=packages,
                    strategy="standard_upgrade",
                    reasoning="Updater scan",
                    max_attempts=3,
                    planning_cycle=int(state.get("planning_cycle") or 1),
                )
                plan_dict = plan.model_dump()
                out = {
                    "messages": state.get("messages") or [],
                    "action_plan": {
                        **plan_dict,
                        "domain": "UPDATE",
                        "target_name": plan.goal,
                        "manager": "winget",
                        "risk_level": "low",
                    },
                    "update_plan": plan_dict,
                    "repair_plan": {
                        "goal": plan.goal,
                        "root_cause": f"{len(packages)} updates",
                        "confidence": 1.0,
                        "primary_fix": {"id": "standard_upgrade", "risk": "low"},
                        "fallbacks": [],
                        "reasoning": "Updater scan",
                        "verification": ["version_check"],
                        "max_attempts": 3,
                        "planning_cycle": plan.planning_cycle,
                        "packages": [p.model_dump() for p in packages],
                    },
                }
                log_ok(f"🧠 Planner  Scan plan — {len(packages)} pkg(s)")
        return out

    return build_action_graph(
        domain="UPDATE",
        planner_node=planner_with_updater,
        executor_obj=updater,
        validator_fn=winget_version_validator,
        llm=llm,
        permission_display="standard",
        strategy_chain=_UPDATE_STRATEGY_CHAIN,
        checkpoint_db_path=checkpoint_db_path,
        max_planning_cycles=max_planning_cycles,
    )