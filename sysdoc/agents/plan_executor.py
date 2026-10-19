"""Executor Agent.

Does NOT think. Walks the RepairPlan -- primary_fix, then each fallback in
the plan's own order -- through the existing ThreadPoolExecutor timeout
wrapper (executor._call_fix_with_timeout, i.e. "Existing Executor" in the
architecture diagram), until one succeeds or max_attempts is reached.
Never invents a fix outside the plan and never re-plans -- that's the
Supervisor's call, made after the Verifier Agent reports, not something
this node decides.
"""
from __future__ import annotations

from typing import Callable

from agents.fix_registry import fix_method_name
from agents.models import RepairPlan
from display.animations import log_cmd, log_err, log_ok, log_warn

_STORAGE_TIMEOUT_SECONDS = 300
_DEFAULT_TIMEOUT_SECONDS = 60


def make_plan_executor_node(domain: str, domain_module, core_executor) -> Callable[[dict], dict]:
    timeout = _STORAGE_TIMEOUT_SECONDS if domain == "STORAGE" else _DEFAULT_TIMEOUT_SECONDS

    def plan_executor_node(state: dict) -> dict:
        plan = RepairPlan(**state["repair_plan"])
        approved = state.get("approved_fix_id") or plan.primary_fix.id

        fallback_ids = [f.id for f in plan.fallbacks if f.id != approved]
        candidates = [approved] + fallback_ids
        candidates = candidates[: plan.max_attempts]

        attempts_made: list[str] = []
        last_error: str | None = None

        for fix_id in candidates:
            method_name = fix_method_name(domain, fix_id)
            if method_name is None:
                # Not implemented yet (see fix_registry.py TODOs) -- skip
                # rather than crash, so a partially-implemented fallback
                # chain still degrades gracefully.
                log_warn(f"{fix_id} has no registered implementation yet -- skipping.")
                continue

            fn = getattr(domain_module, method_name)
            attempts_made.append(fix_id)
            log_cmd(fix_id)

            try:
                if domain == "STORAGE" and fix_id == "delete_duplicates":
                    scan = state.get("last_duplicate_scan")
                    if not scan:
                        last_error = "No duplicate scan in state -- find_duplicate_files was never called."
                        log_warn(last_error)
                        continue
                    result = core_executor._call_fix_with_timeout(
                        lambda: fn(scan), os_data={}, timeout=timeout
                    )
                else:
                    result = core_executor._call_fix_with_timeout(fn, os_data={}, timeout=timeout)

                log_ok(f"{fix_id} executed successfully.")
                return {
                    "attempts_made": attempts_made,
                    "last_fix_result": result,
                    "fix_succeeded": True,
                }
            except Exception as exc:  # noqa: BLE001 -- deliberately broad, we just move to the next candidate
                last_error = str(exc)
                log_err(f"{fix_id} failed: {last_error}")
                continue

        return {
            "attempts_made": attempts_made,
            "last_fix_result": last_error or "No valid fix_id in plan could be executed.",
            "fix_succeeded": False,
        }

    return plan_executor_node
