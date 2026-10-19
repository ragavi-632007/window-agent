"""UPDATE Executor Agent.

Walks the UpdatePlan's package list and for each package:
  1. Tries the plan's strategy (standard_upgrade / force_upgrade / reinstall)
  2. If it fails, escalates through strategies autonomously:
     standard_upgrade → force_upgrade → reinstall
  3. Captures all output for the Verifier and Supervisor to reason about

Unlike the domain Executor (plan_executor.py) which dispatches by fix_id
through fix_registry.py, this executor works directly with UpdateScanner
methods because update operations are parameterized by package (each
package needs its own command), not by a fixed set of domain-level fixes.
"""
from __future__ import annotations

from typing import Callable

from agents.models import UpdatePlan
from display.animations import agent_log_err, agent_log_ok, agent_log_step, agent_log_warn
from display.banner import get_theme_color

# Strategy escalation order — each failed strategy tries the next one
_STRATEGY_CHAIN = ["standard_upgrade", "force_upgrade", "reinstall", "purge_reinstall"]

_STRATEGY_METHOD_MAP = {
    "standard_upgrade": "upgrade_package",
    "force_upgrade": "force_upgrade_package",
    "reinstall": "reinstall_package",
    "purge_reinstall": "purge_reinstall_package",
}


def make_update_executor_node(updater) -> Callable[[dict], dict]:
    """Create the update_executor graph node.

    *updater* is a ``modules.updater.UpdateScanner`` instance with the
    methods: upgrade_package, force_upgrade_package, reinstall_package.
    """

    def update_executor_node(state: dict) -> dict:
        plan = UpdatePlan(**state["update_plan"])
        results: list[dict] = []
        attempts_made: list[str] = []
        all_succeeded = True

        theme_col = get_theme_color()

        for pkg in plan.packages:
            pkg_item = {
                "name": pkg.name,
                "id": pkg.id,
                "manager": pkg.manager,
                "from": pkg.from_version,
                "to": pkg.to_version,
            }

            # Build the strategy chain starting from the plan's strategy
            start_idx = _STRATEGY_CHAIN.index(plan.strategy) if plan.strategy in _STRATEGY_CHAIN else 0
            strategies_to_try = _STRATEGY_CHAIN[start_idx:]

            pkg_succeeded = False
            pkg_output = ""
            used_strategy = ""

            for strategy in strategies_to_try:
                if strategy not in _STRATEGY_METHOD_MAP:
                    continue

                fn = getattr(updater, "run_strategy", None)
                if fn is None:
                    agent_log_warn(f"UpdateScanner has no run_strategy — skipping.")
                    continue

                agent_log_step(f"{strategy}: {pkg.name} ({pkg.manager})")
                attempts_made.append(f"{strategy}:{pkg.id}")
                used_strategy = strategy

                try:
                    success, output = fn(pkg_item, strategy, color=theme_col, use_progress=True)
                    pkg_output = output

                    if success:
                        agent_log_ok(f"{pkg.name} updated via {strategy}")
                        pkg_succeeded = True
                        break
                    else:
                        agent_log_warn(f"{strategy} failed for {pkg.name}: {output[:120]}")
                except Exception as exc:
                    pkg_output = str(exc)
                    agent_log_err(f"{strategy} error for {pkg.name}: {exc}")

            if not pkg_succeeded:
                all_succeeded = False
                agent_log_err(f"All strategies exhausted for {pkg.name}.")

            results.append({
                "name": pkg.name,
                "id": pkg.id,
                "manager": pkg.manager,
                "success": pkg_succeeded,
                "strategy_used": used_strategy,
                "output": pkg_output[:500],  # trim to avoid state bloat
            })

        summary_parts = []
        for r in results:
            status = "✓" if r["success"] else "✗"
            summary_parts.append(f"{status} {r['name']} ({r.get('strategy_used', 'none')})")
        summary = "; ".join(summary_parts)

        return {
            "attempts_made": attempts_made,
            "update_results": results,
            "last_fix_result": summary,
            "fix_succeeded": all_succeeded,
        }

    return update_executor_node
