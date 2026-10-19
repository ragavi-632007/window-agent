"""Action Supervisor Node — workflow coordinator for the Action Graph.

Owns all retry/escalate decisions. Reads verification + Error Analyzer output.
Never executes commands. Never analyzes errors.

Possible outcomes (graph edges):
    finalize_success  → END
    retry_new_cycle   → start_new_cycle → Planner (loop)
    escalate          → escalate_node → END
"""
from __future__ import annotations

from typing import Callable, Literal
from pydantic import BaseModel

from display.animations import agent_log_err, agent_log_ok, agent_log_step, agent_log_warn

class SupervisorDecision(BaseModel):
    action: Literal["finalize_success", "retry_new_cycle", "escalate"]
    reason: str

DEFAULT_MAX_PLANNING_CYCLES = 3


def make_action_supervisor_node(
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
    domain_strategy_chain: list | None = None,
) -> Callable[[dict], dict]:
    chain = list(domain_strategy_chain or [])

    def action_supervisor_node(state: dict) -> dict:
        verification   = state.get("verification") or {}
        error_analysis = state.get("error_analysis") or {}
        cycle          = state.get("planning_cycle", 1)
        attempts       = state.get("attempts_made") or []

        decision_dict: dict

        # ── Success ────────────────────────────────────────────────────────
        if verification.get("success"):
            decision = SupervisorDecision(
                action="finalize_success",
                reason="Verifier confirmed the operation completed successfully.",
            )
            agent_log_ok(f"🛡 Supervisor  {decision.reason}")
            decision_dict = decision.model_dump()

        # ── Non-recoverable or cycles exhausted → escalate ─────────────────
        elif not error_analysis.get("recoverable", True) or cycle >= max_planning_cycles:
            reason = (
                f"All {max_planning_cycles} planning cycles exhausted without success."
                if cycle >= max_planning_cycles
                else (
                    "Error Analyzer classified failure as non-recoverable: "
                    f"{error_analysis.get('summary', 'see logs')}."
                )
            )
            decision = SupervisorDecision(action="escalate", reason=reason)
            agent_log_err(f"🛡 Supervisor  {reason}")
            decision_dict = decision.model_dump()

        # ── Recoverable → retry ────────────────────────────────────────────
        else:
            recommended = error_analysis.get("recommended_strategy", "")

            if recommended in ("retry_same", "replan"):
                # retry_same: re-run the same strategy (network hiccup, hash miss)
                # replan: Planner re-runs with error context (ambiguous package)
                current_strategy = (state.get("action_plan") or {}).get("strategy", "")
                next_strategy = current_strategy or (chain[0] if chain else "")
            elif recommended in chain:
                next_strategy = recommended
            else:
                # Step one past what was last tried in the domain chain
                tried = {a.split(":")[0] for a in attempts}
                next_strategy = next(
                    (s for s in chain if s not in tried),
                    chain[-1] if chain else "",
                )

            reason = (
                f"Cycle {cycle} failed. "
                f"Error Analyzer: {error_analysis.get('summary', 'unknown failure')}. "
                f"Scheduling retry with strategy '{next_strategy}'."
            )
            decision = SupervisorDecision(action="retry_new_cycle", reason=reason)
            agent_log_warn(f"🛡 Supervisor  {reason}")
            decision_dict = decision.model_dump()
            decision_dict["next_strategy"] = next_strategy

        history_entry = {
            "action_plan":    state.get("action_plan"),
            "attempts_made":  attempts,
            "verification":   verification,
            "error_analysis": error_analysis,
        }

        return {
            "supervisor_decision": decision_dict,
            "cycle_history": (state.get("cycle_history") or []) + [history_entry],
        }

    return action_supervisor_node


def route_supervisor_decision(state: dict) -> str:
    decision = state.get("supervisor_decision") or {}
    return decision.get("action", "escalate")


def make_start_new_cycle_node(
    domain: str,
    domain_strategy_chain: list | None = None,
) -> Callable[[dict], dict]:
    """Resets per-cycle state. Carries failure context forward to the Planner."""
    chain = list(domain_strategy_chain or [])

    def start_new_cycle_node(state: dict) -> dict:
        cycle          = state.get("planning_cycle", 1)
        verification   = state.get("verification") or {}
        error_analysis = state.get("error_analysis") or {}
        exec_results   = state.get("execution_results") or state.get("update_results") or []
        decision       = state.get("supervisor_decision") or {}
        next_strategy  = decision.get("next_strategy") or (chain[0] if chain else "")

        bits: list[str] = []
        if verification.get("verification_summary"):
            bits.append(verification["verification_summary"])
        if error_analysis.get("summary"):
            bits.append(f"Error: {error_analysis['summary']}")
        for r in exec_results:
            if not r.get("success"):
                bits.append(
                    f"{r.get('name', '?')} / {r.get('strategy_used', '?')}: "
                    f"{(r.get('output') or '')[:180]}"
                )
        failure_context = " | ".join(b for b in bits if b) or "Previous attempt failed."

        agent_log_step(
            f"🛡 Supervisor  Starting new cycle "
            f"(cycle {cycle + 1}), strategy: {next_strategy}..."
        )

        existing_plan = dict(state.get("action_plan") or {})
        if next_strategy:
            existing_plan["strategy"] = next_strategy
        existing_plan["prior_failure_context"] = failure_context
        existing_plan["planning_cycle"] = cycle + 1

        return {
            "planning_cycle":    cycle + 1,
            "action_plan":       existing_plan,
            "update_plan":       existing_plan,   # UPDATE compat alias
            "repair_plan":       None,
            "gate_approved":     None,
            "gate_choice":       None,
            "attempts_made":     [],
            "fix_succeeded":     False,
            "verification":      None,
            "error_analysis":    None,
            "execution_results": [],
            "update_results":    [],
            "messages": [
                (
                    "system",
                    f"Previous {domain} cycle failed (cycle {cycle}): {failure_context} "
                    f"Use strategy '{next_strategy}'. Do not repeat the same approach.",
                )
            ],
        }

    return start_new_cycle_node


def make_escalate_node() -> Callable[[dict], dict]:
    def escalate_node(state: dict) -> dict:
        decision = state.get("supervisor_decision") or {}
        reason = decision.get("reason", "All planning cycles exhausted.")
        agent_log_err(f"🛡 Supervisor  Escalating: {reason}")
        return {"last_fix_result": "escalated_after_exhausted_planning_cycles"}
    return escalate_node
