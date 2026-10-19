"""Supervisor.

Owns workflow coordination only. It never calls a tool, never runs
PowerShell / CMD / Git / Python / registry / filesystem actions, and never
calls executor._call_fix_with_timeout() directly -- that stays entirely
inside plan_executor.py (the Executor Agent).

The Supervisor's one real decision point is what happens after the
Verifier Agent reports:
  - finalize on success
  - start a NEW planning cycle (a fresh RepairPlan, informed by why the
    last one failed) if planning cycles remain
  - escalate once cycles are exhausted

This is deliberately implemented as plain Python, not an LLM call. None
of these decisions need language reasoning: domain selection already
happened in IntentEngine before the subgraph starts, "did it succeed" is
just reading VerificationOutcome.success, and "retry or escalate" is a
bounded counter policy. That keeps the coordination layer deterministic
and testable, and keeps the one thing that actually needs judgment --
diagnosis -- where it belongs, in the Planner.
"""
from __future__ import annotations

from typing import Callable

from agents.models import SupervisorDecision
from display.animations import log_err, log_ok, log_step, log_warn

DEFAULT_MAX_PLANNING_CYCLES = 2


def make_supervisor_decide_node(max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES) -> Callable[[dict], dict]:
    """Runs immediately after the Verifier Agent node in the graph."""

    def supervisor_decide_node(state: dict) -> dict:
        verification = state.get("verification") or {}
        cycle = state.get("planning_cycle", 1)

        if verification.get("success"):
            decision = SupervisorDecision(
                action="finalize_success",
                reason="Verifier Agent confirmed the repair goal was met.",
            )
        elif cycle < max_planning_cycles:
            decision = SupervisorDecision(
                action="retry_new_cycle",
                reason=f"Cycle {cycle} exhausted without success; "
                       f"{max_planning_cycles - cycle} planning cycle(s) remain.",
            )
        else:
            decision = SupervisorDecision(
                action="escalate",
                reason=f"All {max_planning_cycles} planning cycles exhausted without success.",
            )

        history_entry = {
            "repair_plan": state.get("repair_plan"),  # already a plain dict, see planner.py
            "attempts_made": state.get("attempts_made", []),
            "verification": verification,
        }

        if decision.action == "finalize_success":
            log_ok(f"Supervisor: {decision.reason}")
        elif decision.action == "retry_new_cycle":
            log_warn(f"Supervisor: {decision.reason}")
        else:
            log_err(f"Supervisor: {decision.reason}")

        return {
            "supervisor_decision": decision.model_dump(),
            "cycle_history": state.get("cycle_history", []) + [history_entry],
        }

    return supervisor_decide_node


def route_supervisor_decision(state: dict) -> str:
    """Conditional-edge router reading what supervisor_decide_node just decided."""
    decision = state.get("supervisor_decision") or {}
    return decision.get("action", "escalate")


def make_start_new_cycle_node() -> Callable[[dict], dict]:
    """Resets per-cycle state before looping back to the Planner, while
    carrying forward *why* the last cycle failed so the new RepairPlan is
    informed by it instead of repeating the same diagnosis. This is the
    only place planning_cycle is incremented."""

    def start_new_cycle_node(state: dict) -> dict:
        verification = state.get("verification") or {}
        failure_context = verification.get(
            "verification_summary", "Previous attempt did not resolve the issue."
        )
        log_step(f"Starting a new diagnostic cycle (cycle {state.get('planning_cycle', 1) + 1})...")
        return {
            "planning_cycle": state.get("planning_cycle", 1) + 1,
            "repair_plan": None,
            "approved_fix_id": None,
            "gate_choice": None,
            "attempts_made": [],
            "fix_succeeded": False,
            "verification": None,
            "messages": [
                (
                    "system",
                    f"Previous planning cycle failed: {failure_context} "
                    "Diagnose again with this in mind -- don't repeat the same root_cause "
                    "and primary_fix unless new telemetry genuinely still points to it.",
                )
            ],
        }

    return start_new_cycle_node


def make_escalate_node() -> Callable[[dict], dict]:
    """Terminal node for the exhausted-cycles path. Doesn't open a ticket
    itself -- that stays the existing ticket flow, reachable the same way
    it always was (the human can still choose 't' at the permission gate
    on any cycle). This just marks the outcome clearly for the report."""

    def escalate_node(state: dict) -> dict:
        return {"last_fix_result": "escalated_after_exhausted_planning_cycles"}

    return escalate_node
