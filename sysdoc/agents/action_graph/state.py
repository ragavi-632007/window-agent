"""ActionGraphState — the single shared state TypedDict used by every Action Graph.

All action-domain graphs (INSTALL, UPDATE, UNINSTALL, …) run on this state.
It coexists with DomainAgentState (agents/state.py) which is used by the
supervisor-domain graph (graph.py).  Neither replaces the other.
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class ActionGraphState(TypedDict, total=False):
    # ── identity ──────────────────────────────────────────────────────────
    domain: str          # "INSTALL" | "UPDATE" | "UNINSTALL" | …
    thread_id: str
    session_id: str

    # ── conversation ──────────────────────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── plan (set by Planner each cycle, never rewritten mid-cycle) ───────
    # Stored as plain dict (ActionPlan subclass .model_dump()) — the
    # checkpointer serialiser does not have Pydantic models registered.
    # Nodes that need attribute access do  MyPlan(**state["action_plan"]).
    action_plan: Optional[dict]

    # UPDATE-specific extra: pre-scan results cache for the planner
    available_updates: Optional[list[dict]]

    # ── permission gate ───────────────────────────────────────────────────
    gate_approved: Optional[bool]   # None = not yet seen
    gate_choice: Optional[str]      # raw letter: "y", "n", "t", …

    # ── execution ─────────────────────────────────────────────────────────
    # List of per-package result dicts:
    #   {name, id, manager, success, strategy_used, output}
    execution_results: Optional[list[dict]]
    fix_succeeded: bool
    last_fix_result: Optional[str]
    attempts_made: list[str]        # "strategy:pkg_id" pairs tried this cycle

    # ── verification ──────────────────────────────────────────────────────
    verification: Optional[dict]    # VerificationOutcome-shaped dict

    # ── error analysis (NEW) ──────────────────────────────────────────────
    error_analysis: Optional[dict]
    # Shape:
    #   category              str   see ErrorCategory in error_analyzer.py
    #   recoverable           bool
    #   recommended_strategy  str   next strategy name, "abort", or "escalate"
    #   summary               str   one sentence shown to user
    #   raw_signal            str   excerpt that triggered the classification

    # ── supervisor ────────────────────────────────────────────────────────
    supervisor_decision: Optional[dict]   # SupervisorDecision.model_dump()
    planning_cycle: int                   # starts at 1, supervisor increments
    cycle_history: list[dict]             # one entry per completed cycle
    telemetry: dict[str, Any]             # domain-specific telemetry (optional)

    # ── UNINSTALL-specific ────────────────────────────────────────────────
    # Set by the high-risk gate after per-package y/n prompts.
    # Contains only the packages the user approved for removal.
    approved_packages: Optional[list[dict]]
    _gate_pkg_choices: Optional[dict[str, str]]
