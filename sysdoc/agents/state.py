"""Per-domain LangGraph state schema, shared by NETWORK / STORAGE / DEV_ENV / SYSTEM."""
from __future__ import annotations

from typing import Annotated, Any, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class DomainAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]

    domain: str                              # "NETWORK" | "STORAGE" | "DEV_ENV" | "SYSTEM"
    telemetry: dict[str, Any]                # from <module>.collect(), auto-run once, refreshable

    # Stored as RepairPlan.model_dump() (a plain dict), not the Pydantic
    # object -- the checkpointer's serializer doesn't have RepairPlan
    # registered and warns it'll be a hard error in a future langgraph
    # version. Nodes that want attribute access do
    # RepairPlan(**state["repair_plan"]) themselves (see plan_executor.py,
    # verifier_node.py).
    repair_plan: Optional[dict]              # set by the Planner each cycle, never rewritten mid-cycle
    approved_fix_id: Optional[str]           # what the human actually approved (may override primary_fix.id)
    gate_choice: Optional[str]               # raw letter returned by PermissionGate.ask_permission()

    attempts_made: list[str]                 # fix_ids the Executor Agent tried this cycle, in order
    fix_succeeded: bool
    last_fix_result: Optional[str]

    # STORAGE-only: written by the find_duplicate_files tool, read + validated
    # by plan_executor.py before it will run "delete_duplicates".
    last_duplicate_scan: Optional[dict[str, list[str]]]

    verification: Optional[dict]             # VerificationOutcome.model_dump()

    # Supervisor-owned. See supervisor.py -- never written by Planner/Executor/Verifier.
    planning_cycle: int                      # starts at 1, incremented on retry_new_cycle
    cycle_history: list[dict]                # one entry per completed cycle: {repair_plan, attempts_made, verification}
    supervisor_decision: Optional[dict]      # SupervisorDecision.model_dump()
    session_id: str
    thread_id: str

    # UPDATE-only fields
    update_plan: Optional[dict]              # UpdatePlan.model_dump()
    available_updates: Optional[list[dict]]  # scan results cached for planner
    update_results: Optional[list[dict]]     # per-package {name, success, output, strategy}
    target_packages: Optional[list[dict]]    # manually selected packages from menu
