"""Git Action Graph models — allowlisted steps only (no free-form shell)."""
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]

StepName = Literal[
    "status", "log", "diff", "remote", "branch_list",
    "stage_all", "commit", "push", "push_upstream", "pull_rebase",
    "create_branch", "checkout", "merge", "stash_save", "stash_pop", "clone",
]


class GitStep(BaseModel):
    name: StepName
    risk: Risk = "medium"
    args: dict = Field(default_factory=dict)
    description: str = ""


class GitPlan(BaseModel):
    goal: str
    reasoning: str = ""
    steps: List[GitStep] = Field(default_factory=list)
    risk: Risk = "medium"
    strategy_hint: Optional[str] = None
    planning_cycle: int = 1


class GitErrorAnalysis(BaseModel):
    category: str
    recoverable: bool
    strategy_id: str
    reason: str


class GitReport(BaseModel):
    ok: bool
    summary: str
    strategy: str = ""
    offer_fixgit: bool = False
    tip: str = ""
