"""Assembles one domain subgraph:

collect_telemetry -> planner -> permission_gate -> resolve_gate_choice
    -> [execute | ticket | skip | show_details_and_reask]
execute -> plan_executor -> verifier -> supervisor_decide
    -> [finalize_success -> END
        | retry_new_cycle -> start_new_cycle -> planner   (loops back)
        | escalate -> escalate_node -> END]

Call build_domain_subgraph() once per domain (NETWORK/STORAGE/DEV_ENV/
SYSTEM) with that domain's module and read tools.

Fix: SqliteSaver constructed from a raw connection (outlives `with` block).
Fix: SQLite connection stored on the returned graph object so main.py can
     close it on shutdown via graph._conn.close().
Fix: Caller now passes thread_id_base per-domain to avoid shared thread_id
     collisions between different domain graphs in the same session.
"""
from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agents.permission_gate_node import permission_gate_node, resolve_gate_choice
from agents.planner import make_planner_node
from agents.plan_executor import make_plan_executor_node
from agents.state import DomainAgentState
from agents.supervisor import (
    DEFAULT_MAX_PLANNING_CYCLES,
    make_escalate_node,
    make_start_new_cycle_node,
    make_supervisor_decide_node,
    route_supervisor_decision,
)
from agents.verifier_node import make_verifier_node
from display.animations import log_step


def _route_after_gate(state: dict) -> str:
    choice = state.get("gate_choice")
    if choice == "d":
        return "show_details_and_reask"
    if state.get("approved_fix_id"):
        return "execute"
    if choice == "t":
        return "ticket"
    return "skip"  # "n" or any unrecognized choice — fail closed


def build_domain_subgraph(
    domain: str,
    domain_module,
    read_tools: list,
    llm,
    core_executor,
    checkpoint_db_path: str = "sysdoc/memory/fixbot_state.db",
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
):
    def collect_telemetry_node(state: dict) -> dict:
        log_step(f"Gathering current {domain} telemetry...")
        return {
            "domain": domain,
            "telemetry": domain_module.collect(),
            "planning_cycle": state.get("planning_cycle", 1),
            "cycle_history": state.get("cycle_history", []),
        }

    def ticket_node(state: dict) -> dict:
        log_step("Opening a support ticket...")
        return {"last_fix_result": "ticket_opened"}

    def show_details_node(state: dict) -> dict:
        return {}

    graph = StateGraph(DomainAgentState)
    graph.add_node("collect_telemetry", collect_telemetry_node)
    graph.add_node("planner", make_planner_node(domain, read_tools, llm))
    graph.add_node("permission_gate", permission_gate_node)
    graph.add_node("resolve_gate_choice", resolve_gate_choice)
    graph.add_node("show_details_and_reask", show_details_node)
    graph.add_node("ticket", ticket_node)
    graph.add_node("plan_executor", make_plan_executor_node(domain, domain_module, core_executor))
    graph.add_node("verifier", make_verifier_node(domain, domain_module))
    graph.add_node("supervisor_decide", make_supervisor_decide_node(max_planning_cycles))
    graph.add_node("start_new_cycle", make_start_new_cycle_node())
    graph.add_node("escalate", make_escalate_node())

    graph.add_edge(START, "collect_telemetry")
    graph.add_edge("collect_telemetry", "planner")
    graph.add_edge("planner", "permission_gate")
    graph.add_edge("permission_gate", "resolve_gate_choice")
    graph.add_conditional_edges(
        "resolve_gate_choice",
        _route_after_gate,
        {
            "execute": "plan_executor",
            "ticket": "ticket",
            "skip": END,
            "show_details_and_reask": "show_details_and_reask",
        },
    )
    graph.add_edge("show_details_and_reask", "permission_gate")
    graph.add_edge("ticket", END)
    graph.add_edge("plan_executor", "verifier")
    graph.add_edge("verifier", "supervisor_decide")
    graph.add_conditional_edges(
        "supervisor_decide",
        route_supervisor_decision,
        {
            "finalize_success": END,
            "retry_new_cycle": "start_new_cycle",
            "escalate": "escalate",
        },
    )
    graph.add_edge("start_new_cycle", "planner")
    graph.add_edge("escalate", END)

    conn = sqlite3.connect(checkpoint_db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = graph.compile(checkpointer=checkpointer)
    # Store connection reference so callers can close it on shutdown
    compiled._conn = conn
    return compiled
