"""LangSmith run tracing — opt-in via LANGSMITH_ENABLED=true in .env.

build_run_metadata() is called on the FINAL state after graph.invoke()
returns (which, after a retry_new_cycle loop, may be after more than one
planning cycle) and then patched onto the completed LangSmith run via
apply_run_metadata().

If LANGSMITH_ENABLED is false (the default), apply_run_metadata() is a
no-op and nothing is sent to LangSmith.
"""
from __future__ import annotations

try:
    from importlib.metadata import version as _pkg_version
    FIXBOT_VERSION = _pkg_version("fixbot")
except Exception:
    FIXBOT_VERSION = "unknown"


def build_run_metadata(domain: str, state: dict) -> dict:
    plan = state.get("repair_plan")  # plain dict, see planner.py
    verification = state.get("verification") or {}
    decision = state.get("supervisor_decision") or {}
    attempts = state.get("attempts_made", [])
    cycle_history = state.get("cycle_history", [])

    return {
        "domain": domain,
        "planner": "structured_output_react",
        "repair_goal": plan.get("goal") if plan else None,
        "root_cause": plan.get("root_cause") if plan else None,
        "primary_fix": plan.get("primary_fix", {}).get("id") if plan else None,
        "fallback_used": attempts[1:] if len(attempts) > 1 else [],
        "attempt_number": len(attempts),
        "planning_cycles_used": state.get("planning_cycle", 1),
        "executor_result": state.get("last_fix_result"),
        "verification_result": verification.get("verification_summary"),
        "confidence": verification.get("confidence"),
        "outcome": decision.get("action", "unknown"),
        "thread_id": state.get("thread_id"),
        "session_id": state.get("session_id"),
        "fixbot_version": FIXBOT_VERSION,
        "cycle_count": len(cycle_history),
    }


def apply_run_metadata(run_id: str, metadata: dict) -> None:
    """Patch metadata/tags onto an already-completed LangSmith run.

    No-ops silently when:
      - LANGSMITH_ENABLED is false (default)
      - run_id is empty
      - LangSmith SDK raises any error (tracing must never crash the app)
    """
    from sysdoc.config import LANGSMITH_ENABLED
    if not LANGSMITH_ENABLED or not run_id:
        return
    try:
        from langsmith import Client
        client = Client()
        client.update_run(
            run_id,
            extra={"metadata": metadata},
            tags=[
                f"domain:{metadata.get('domain')}",
                f"outcome:{metadata.get('outcome')}",
                f"version:{metadata.get('fixbot_version')}",
            ],
        )
    except Exception:
        # Tracing failure must never crash or degrade the main app
        pass
