"""UpdatePlan — ActionPlan subclass for the UPDATE domain.

Replaces the UpdatePlan that used to live in agents/models.py.
agents/models.py re-exports this class so all existing imports keep working.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from action_graph.models.base import ActionPlan


class UpdateTarget(BaseModel):
    """A single package to update.  Identical to the original in agents/models.py."""
    name: str = Field(description="Human-readable package name, e.g. 'Microsoft Edge'")
    id: str = Field(description="Canonical package ID, e.g. 'Microsoft.Edge' for winget")
    manager: str = Field(description="Package manager: 'winget', 'pip', or 'npm'")
    from_version: str = Field(default="", description="Currently installed version")
    to_version: str = Field(default="", description="Available target version")


class UpdatePlan(ActionPlan):
    """Plan produced by the UPDATE Planner.

    Strategy escalation chain for UPDATE:
        standard_upgrade → force_upgrade → reinstall → purge_reinstall
    """
    domain: str = "UPDATE"
    strategy: str = Field(
        default="standard_upgrade",
        description=(
            "Initial strategy: 'standard_upgrade', 'force_upgrade', "
            "'reinstall', or 'purge_reinstall'."
        ),
    )
    packages: List[UpdateTarget] = Field(
        default_factory=list,
        description="Ordered list of packages to update.",
    )
    goal: str = Field(
        default="Update packages",
        description="Plain-language update goal.",
    )
    reasoning: str = Field(
        default="",
        description="Why these packages and this strategy were chosen.",
    )
    prior_failure_context: Optional[str] = Field(
        default=None,
        description="What went wrong last cycle, if this is a re-plan.",
    )
