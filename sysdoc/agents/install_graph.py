"""INSTALL domain subgraph — no eager langchain.agents / transformers import."""
from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from action_graph import build_action_graph
from action_graph.nodes.supervisor import DEFAULT_MAX_PLANNING_CYCLES
from action_graph.nodes.verifier import winget_presence_validator
from display.animations import agent_log_step, agent_log_warn, log_ok

_INSTALL_STRATEGY_CHAIN = [
    "install",
    "force_install",
    "accept_agreements",
    "choco_install",
    "scoop_install",
    "purge_reinstall",
]


def _extract_user_query(state: dict) -> str:
    q = (state.get("user_query") or "").strip()
    if q and q.lower() not in ("app", "package", "software"):
        return q
    prev = state.get("action_plan") or {}
    for key in ("target_id", "target_name", "goal"):
        v = (prev.get(key) or "").strip()
        if v and v.lower() not in ("app", "package", "install app"):
            return v.replace("Install ", "").strip()
    disc = state.get("discovery_result") or {}
    for key in ("winget_id", "app_name"):
        v = (disc.get(key) or "").strip()
        if v:
            return v
    for m in reversed(state.get("messages") or []):
        content = getattr(m, "content", None) or (
            m.get("content") if isinstance(m, dict) else None
        )
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _discover(user_q: str) -> dict:
    try:
        from action_graph.nodes.command_discovery import discover_package
        return discover_package(user_q)
    except Exception as exc:
        agent_log_warn(f"Discovery unavailable ({exc})")
        return {
            "app_name": user_q,
            "winget_id": "",
            "manager": "winget",
            "confidence": 0.2,
            "strategy_chain": list(_INSTALL_STRATEGY_CHAIN),
            "reasoning": f"discovery failed: {exc}",
            "search_hits": [],
            "choco_id": "",
            "scoop_id": "",
        }


def _plan_from_discovery(discovery: dict, cycle: int, strategy: str = "install") -> dict:
    tid = discovery.get("winget_id") or ""
    name = discovery.get("app_name") or tid or "app"
    return {
        "goal": f"Install {name}",
        "domain": "INSTALL",
        "target_name": name,
        "target_id": tid,
        "manager": discovery.get("manager") or "winget",
        "strategy": strategy if strategy in _INSTALL_STRATEGY_CHAIN else "install",
        "reasoning": discovery.get("reasoning") or "Command Discovery",
        "max_attempts": 3,
        "planning_cycle": cycle,
        "choco_id": discovery.get("choco_id") or "",
        "scoop_id": discovery.get("scoop_id") or "",
        "strategy_chain": discovery.get("strategy_chain") or list(_INSTALL_STRATEGY_CHAIN),
    }


def _make_install_planner_node(read_tools: list, llm: BaseChatModel):
    """Planner without top-level create_agent (avoids transformers hang)."""

    def install_planner_node(state: dict) -> dict:
        cycle = int(state.get("planning_cycle") or 1)
        forced = (state.get("supervisor_decision") or {}).get("next_strategy")
        prev = dict(state.get("action_plan") or {})
        discovery = dict(state.get("discovery_result") or {})

        # Cycle 2+: reuse same package ID — no imports, no LLM
        if cycle > 1 and prev.get("target_id"):
            strategy = forced or prev.get("strategy") or "force_install"
            if strategy not in _INSTALL_STRATEGY_CHAIN:
                strategy = "force_install"
            plan = {
                **prev,
                "strategy": strategy,
                "planning_cycle": cycle,
                "reasoning": f"Retry same package with strategy={strategy}",
            }
            log_ok(f"🧠 Planner  Reuse {plan['target_id']} → {strategy} (cycle {cycle})")
            return {
                "messages": state.get("messages") or [],
                "action_plan": plan,
                "discovery_result": discovery or {
                    "winget_id": prev.get("target_id"),
                    "app_name": prev.get("target_name"),
                },
            }

        user_q = _extract_user_query(state)
        if not discovery.get("winget_id"):
            agent_log_step(f"🧠 Planner  discovering package for: {user_q or 'query'}")
            if user_q:
                discovery = _discover(user_q)

        if discovery.get("winget_id"):
            strategy = "install"
            if forced and forced in _INSTALL_STRATEGY_CHAIN:
                strategy = forced
            plan = _plan_from_discovery(discovery, cycle, strategy=strategy)
            log_ok(f"🧠 Planner  Discovery install plan — {plan['target_id']}")
            return {
                "messages": (state.get("messages") or [])
                + [AIMessage(content=f"Plan: Install {plan['target_id']}")],
                "action_plan": plan,
                "discovery_result": discovery,
                "user_query": user_q,
            }

        # Last resort: offline plan from raw query (still no create_agent)
        agent_log_warn("Planner  no winget id — offline name fallback")
        name = user_q or "app"
        plan = {
            "goal": f"Install {name}",
            "domain": "INSTALL",
            "target_name": name,
            "target_id": name,  # winget may still resolve by name
            "manager": "winget",
            "strategy": forced if forced in _INSTALL_STRATEGY_CHAIN else "install",
            "reasoning": "offline fallback — no discovery hit",
            "max_attempts": 3,
            "planning_cycle": cycle,
            "choco_id": "",
            "scoop_id": "",
            "strategy_chain": list(_INSTALL_STRATEGY_CHAIN),
        }
        log_ok(f"🧠 Planner  Offline plan — {plan['target_id']}")
        return {
            "messages": state.get("messages") or [],
            "action_plan": plan,
            "discovery_result": discovery,
            "user_query": user_q,
        }

    return install_planner_node


def build_install_subgraph(
    updater: Any,
    read_tools: list,
    llm: BaseChatModel,
    checkpoint_db_path: str = "sysdoc/memory/fixbot_state.db",
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
):
    return build_action_graph(
        domain="INSTALL",
        planner_node=_make_install_planner_node(read_tools, llm),
        executor_obj=updater,
        validator_fn=winget_presence_validator,
        llm=llm,
        permission_display="standard",
        strategy_chain=_INSTALL_STRATEGY_CHAIN,
        checkpoint_db_path=checkpoint_db_path,
        max_planning_cycles=max_planning_cycles,
    )