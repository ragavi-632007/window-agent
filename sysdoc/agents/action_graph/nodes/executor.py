"""Action Executor — run one strategy; never crash on logging."""
from __future__ import annotations

from typing import Callable

from display.animations import (
    agent_log,
    agent_log_err,
    agent_log_ok,
    agent_log_step,
    agent_log_warn,
)
from display.banner import get_theme_color


def make_action_executor_node(executor_obj) -> Callable[[dict], dict]:
    def action_executor_node(state: dict) -> dict:
        plan = state.get("action_plan") or {}
        strategy = plan.get("strategy") or "install"
        theme_col = get_theme_color()

        packages = plan.get("packages") or []
        if not packages:
            packages = [{
                "name": plan.get("target_name") or plan.get("goal") or "target",
                "id": plan.get("target_id") or "",
                "manager": plan.get("manager") or "winget",
                "choco_id": plan.get("choco_id") or "",
                "scoop_id": plan.get("scoop_id") or "",
            }]

        results = []
        attempts_made = list(state.get("attempts_made") or [])
        all_succeeded = True

        for pkg in packages:
            pkg_item = {
                "name": pkg.get("name") or plan.get("target_name") or "",
                "id": pkg.get("id") or plan.get("target_id") or "",
                "manager": pkg.get("manager") or plan.get("manager") or "winget",
                "choco_id": pkg.get("choco_id") or plan.get("choco_id") or "",
                "scoop_id": pkg.get("scoop_id") or plan.get("scoop_id") or "",
                "from": pkg.get("from_version") or pkg.get("from") or "",
                "to": pkg.get("to_version") or pkg.get("to") or "",
            }

            agent_log_step(
                f"Executor  running strategy '{strategy}' on '{pkg_item['name']}'..."
            )

            # Skip download when already installed (plain install only)
            if strategy == "install":
                is_inst = getattr(executor_obj, "is_installed", None)
                if callable(is_inst):
                    try:
                        ok_inst, ver = is_inst(pkg_item)
                    except Exception:
                        ok_inst, ver = False, ""
                    if ok_inst:
                        agent_log_ok(
                            f"✓ Executor  {pkg_item['name']} already installed"
                            + (f" (v{ver})" if ver else "")
                            + " — skipped download"
                        )
                        results.append({
                            "name": pkg_item["name"],
                            "id": pkg_item["id"],
                            "manager": pkg_item["manager"],
                            "success": True,
                            "strategy_used": "already_installed",
                            "exit_code": 0,
                            "stdout": f"already installed {ver}".strip(),
                            "stderr": "",
                            "output": f"already installed {ver}".strip(),
                        })
                        attempts_made.append(f"already_installed:{pkg_item['id']}")
                        continue

            attempts_made.append(f"{strategy}:{pkg_item['id']}")

            success = False
            stdout = ""
            stderr = ""
            exit_code = -1
            output = ""

            fn = getattr(executor_obj, "run_strategy", None)
            if fn is None:
                agent_log_warn("executor_obj has no run_strategy")
                all_succeeded = False
                output = "no run_strategy"
            else:
                try:
                    ok, raw_output = fn(
                        pkg_item,
                        strategy,
                        color=theme_col,
                        use_progress=True,
                    )
                    success = bool(ok)
                    output = (raw_output or "")[:800]
                    stdout = output
                    if success:
                        agent_log_ok(
                            f"✓ Executor  {pkg_item['name']} completed ({strategy})"
                        )
                    else:
                        agent_log_warn(
                            f"✗ Executor  {pkg_item['name']} failed ({strategy})"
                        )
                        if output:
                            agent_log("error", output[:220].replace("\n", " "))
                except NameError as exc:
                    # Never let a logging NameError mark a good install as failed
                    success = False
                    output = f"logging error: {exc}"
                    stderr = output
                    agent_log_err(f"✗ Executor  logging bug: {exc}")
                except Exception as exc:
                    success = False
                    output = str(exc)[:500]
                    stderr = output
                    agent_log_err(
                        f"✗ Executor  {pkg_item['name']} error ({strategy}): {exc}"
                    )

            if not success:
                all_succeeded = False

            results.append({
                "name": pkg_item["name"],
                "id": pkg_item["id"],
                "manager": pkg_item["manager"],
                "success": success,
                "strategy_used": strategy,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "output": output,
            })

        summary = "; ".join(
            f"{'✓' if r['success'] else '✗'} {r['name']} ({r['strategy_used']})"
            for r in results
        )
        return {
            "execution_results": results,
            "update_results": results,
            "attempts_made": attempts_made,
            "fix_succeeded": all_succeeded,
            "last_fix_result": summary,
        }

    return action_executor_node