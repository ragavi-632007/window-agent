"""build_action_graph() — the single factory function every domain wrapper calls.

The graph topology is fixed:

    START
      │
      ▼
   planner_node  (domain-injected)
      │
      ▼
   permission_gate  (interrupt — always)
      │
      ▼
   resolve_gate_choice
      │
      ├── gate_approved=False → END  (user said n or t)
      │
      ▼
   action_executor  (shared)
      │
      ▼
   action_verifier  (domain validator_fn injected)
      │
      ▼
   error_analyzer   (shared, llm optional)
      │
      ▼
   action_supervisor  (shared)
      │
      ├── finalize_success → END
      ├── retry_new_cycle  → start_new_cycle → planner_node  (loop)
      └── escalate         → escalate_node → END

Only the injected functions change per domain:
    planner_node       — the LLM agent + prompt + domain tools
    executor_obj       — module with run_strategy(item, strategy) -> (bool, str)
    validator_fn       — (plan, results) -> {success, confidence, summary, details}
    permission_display — "standard" | "high_risk"
    strategy_chain     — ordered list of strategies for this domain
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Literal, Optional

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from action_graph.nodes.error_analyzer import make_error_analyzer_node
from action_graph.nodes.executor import make_action_executor_node
from action_graph.nodes.permission_gate import (
    action_permission_gate_node,
    make_high_risk_gate_node,
    make_resolve_gate_choice_node,
)
from action_graph.nodes.supervisor import (
    make_action_supervisor_node,
    make_escalate_node,
    make_start_new_cycle_node,
    route_supervisor_decision,
    DEFAULT_MAX_PLANNING_CYCLES,
)
from action_graph.nodes.verifier import make_action_verifier_node
from action_graph.state import ActionGraphState


def build_action_graph(
    domain: str,
    planner_node: Callable[[dict], dict],
    executor_obj,
    validator_fn: Callable[[dict, list], dict],
    llm: Optional[BaseChatModel] = None,
    permission_display: Literal["standard", "high_risk"] = "standard",
    strategy_chain: Optional[list[str]] = None,
    checkpoint_db_path: str = "sysdoc/memory/fixbot_state.db",
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
):
    """Build and compile an Action Graph for *domain*.

    Args:
        domain:             Domain string, e.g. "INSTALL", "UPDATE", "UNINSTALL".
        planner_node:       The LLM-agent node function for this domain.
                            Must read ActionGraphState and return a dict that
                            sets at least "action_plan" and "messages".
        executor_obj:       Object with run_strategy(item, strategy, **kw)
                            returning (success: bool, output: str).
        validator_fn:       Callable (plan, results) -> verification dict.
        llm:                Optional LLM for Error Analyzer fallback classification.
        permission_display: "standard" shows one y/n prompt.
        "high_risk" shows per-package preview (UNINSTALL).
        strategy_chain:     Ordered escalation chain for this domain.
                            e.g. ["install", "force_install", "purge_reinstall"]
        checkpoint_db_path: SQLite path for LangGraph checkpointer.
        max_planning_cycles: Hard ceiling on retry cycles (default 3).

    Returns:
        A compiled LangGraph StateGraph with a _conn attribute holding the
        SQLite connection (caller should keep a reference).
    """
    chain = list(strategy_chain or [])

    # ── Gate nodes (chosen by permission_display) ─────────────────────────
    if permission_display == "high_risk":
        gate_node    = make_high_risk_gate_node()
    else:
        gate_node    = action_permission_gate_node   # plain function, not a closure

    resolve_node = make_resolve_gate_choice_node(permission_display)

    # ── Shared nodes ──────────────────────────────────────────────────────
    executor_node  = make_action_executor_node(executor_obj)
    verifier_node  = make_action_verifier_node(validator_fn)
    analyzer_node  = make_error_analyzer_node(llm=llm, domain_strategy_chain=chain)
    supervisor_node = make_action_supervisor_node(
        max_planning_cycles=max_planning_cycles,
        domain_strategy_chain=chain,
    )
    cycle_node     = make_start_new_cycle_node(domain, domain_strategy_chain=chain)
    escalate_node  = make_escalate_node()

    # ── Ticket stub (domain wrappers may override by adding their own node) ─
    def ticket_node(state: dict) -> dict:
        from display.animations import agent_log_step
        agent_log_step("Opening a support ticket...")
        return {"last_fix_result": "ticket_opened"}

    # ── Routing functions ─────────────────────────────────────────────────

    def _route_after_gate(state: dict) -> str:
        """Route after resolve_gate_choice based on approval."""
        choice = state.get("gate_choice", "n")
        approved = state.get("gate_approved", False)
        if choice == "t":
            return "ticket"
        if not approved:
            return "skip"
        return "execute"

    # ── Graph assembly ────────────────────────────────────────────────────
    graph = StateGraph(ActionGraphState)

    graph.add_node("planner",           planner_node)
    graph.add_node("permission_gate",   gate_node)
    graph.add_node("resolve_gate",      resolve_node)
    graph.add_node("action_executor",   executor_node)
    graph.add_node("action_verifier",   verifier_node)
    graph.add_node("error_analyzer",    analyzer_node)
    graph.add_node("action_supervisor", supervisor_node)
    graph.add_node("start_new_cycle",   cycle_node)
    graph.add_node("escalate",          escalate_node)
    graph.add_node("ticket",            ticket_node)

    # Edges
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "permission_gate")
    graph.add_edge("permission_gate", "resolve_gate")
    graph.add_conditional_edges(
        "resolve_gate",
        _route_after_gate,
        {
            "execute": "action_executor",
            "ticket":  "ticket",
            "skip":    END,
        },
    )
    graph.add_edge("ticket", END)
    graph.add_edge("action_executor", "action_verifier")
    graph.add_edge("action_verifier", "error_analyzer")
    graph.add_edge("error_analyzer", "action_supervisor")
    graph.add_conditional_edges(
        "action_supervisor",
        route_supervisor_decision,
        {
            "finalize_success": END,
            "retry_new_cycle":  "start_new_cycle",
            "escalate":         "escalate",
        },
    )
    graph.add_edge("start_new_cycle", "planner")
    graph.add_edge("escalate", END)

    # Compile with persistence Saver
    conn = sqlite3.connect(checkpoint_db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = graph.compile(checkpointer=checkpointer)
    compiled._conn = conn
    return compiled
