"""InstallPlan — ActionPlan subclass for the INSTALL domain."""
from __future__ import annotations

from action_graph.models.base import ActionPlan


class InstallPlan(ActionPlan):
    """Plan produced by the INSTALL Planner.

    Represents a request to install a single package that is NOT yet present
    on the system.  The Planner resolves the human app name to target_id
    (exact winget package ID) before emitting this plan.

    Strategy escalation chain for INSTALL:
        install → force_install → purge_reinstall
    """

    domain: str = "INSTALL"
    risk_level: str = "low"   # default; Planner may raise to "medium"

    # strategy must be one of: "install", "force_install", "purge_reinstall"
    strategy: str = "install"
