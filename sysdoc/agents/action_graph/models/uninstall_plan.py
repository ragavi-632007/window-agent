"""UninstallPlan — ActionPlan subclass for the UNINSTALL domain.

UNINSTALL is treated as high-risk.  The permission gate shows a per-package
preview and requires explicit y/n for each package before anything runs.
data_removal defaults to False and must never be set True by the Planner
unless the user explicitly said to remove user data / config.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from action_graph.models.base import ActionPlan


class UninstallTarget(BaseModel):
    """A single package to uninstall."""
    name: str = Field(description="Human-readable name, e.g. 'Discord'")
    id: str = Field(description="Exact winget package ID, e.g. 'Discord.Discord'")
    manager: str = Field(default="winget", description="'winget', 'pip', or 'npm'")
    installed_version: str = Field(default="", description="Currently installed version")
    install_date: str = Field(default="", description="Install date if known, else empty")
    data_removal: bool = Field(
        default=False,
        description=(
            "Whether to also remove user data / config directories. "
            "NEVER set True unless the user explicitly asked for a full purge."
        ),
    )


class UninstallPlan(ActionPlan):
    """Plan produced by the UNINSTALL Planner.

    risk_level is hardcoded to 'high' so build_action_graph() always routes
    the permission gate to the high-risk display mode (per-package preview).

    Strategy escalation chain for UNINSTALL:
        uninstall → force_uninstall → purge_uninstall
    """

    domain: str = "UNINSTALL"
    risk_level: str = "high"   # immutable — always high for uninstall
    strategy: str = "uninstall"

    packages: List[UninstallTarget] = Field(
        default_factory=list,
        description="Ordered list of packages to remove.",
    )
    goal: str = Field(
        default="Uninstall packages",
        description="Plain-language uninstall goal.",
    )
    reasoning: str = Field(
        default="",
        description="Why these packages were selected for removal.",
    )
