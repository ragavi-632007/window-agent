"""Pre-install check: skip download if app already present."""
from __future__ import annotations

from typing import Callable

from display.animations import agent_log, agent_log_ok, agent_log_step, agent_log_warn


def make_precheck_install_node(updater) -> Callable[[dict], dict]:
    def precheck_install_node(state: dict) -> dict:
        plan = state.get("action_plan") or {}
        # User explicitly asked to force/reinstall on a later cycle
        strategy = (plan.get("strategy") or "install").lower()
        if strategy in ("force_install", "purge_reinstall", "accept_agreements"):
            return {"already_installed": False, "installed_version": ""}

        item = {
            "id": plan.get("target_id") or "",
            "name": plan.get("target_name") or "",
            "manager": plan.get("manager") or "winget",
        }
        if not item["id"] and not item["name"]:
            return {"already_installed": False, "installed_version": ""}

        agent_log_step(
            f"PreCheck  is '{item['name'] or item['id']}' already installed?"
        )
        try:
            installed, version = updater.is_installed(item)
        except Exception as exc:
            agent_log_warn(f"PreCheck  skipped ({exc})")
            return {"already_installed": False, "installed_version": ""}

        if installed:
            agent_log_ok(
                f"PreCheck  already installed"
                + (f" (v{version})" if version else "")
            )
            agent_log(
                "precheck",
                "Skipping download. Offer update / reinstall / cancel to the user.",
            )
            return {
                "already_installed": True,
                "installed_version": version or "unknown",
            }

        agent_log_ok("PreCheck  not installed — will download")
        return {"already_installed": False, "installed_version": ""}

    return precheck_install_node
