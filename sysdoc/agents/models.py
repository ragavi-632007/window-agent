"""agents/models.py — domain models (no import of action_graph package root)."""
from __future__ import annotations

from typing import List, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

# Do NOT: from action_graph.models.update_plan import ...
# That loads action_graph/__init__ → builder → supervisor → agents.models (cycle)

Domain = Literal["NETWORK", "STORAGE", "DEV_ENV", "SYSTEM", "UPDATE"]
Risk = Literal["low", "medium", "high"]


class FixCandidate(BaseModel):
    id: str = Field(description="A fix_id known to this domain's fix_registry.py entry.")
    risk: Risk = Field(default="low", description="Planner's own risk assessment.")


class RepairPlan(BaseModel):
    goal: str = Field(description="Plain-language repair goal.")
    root_cause: str = Field(description="Planner's diagnosis.")
    confidence: float = Field(ge=0.0, le=1.0)
    primary_fix: FixCandidate
    fallbacks: List[FixCandidate] = Field(default_factory=list)
    verification: List[str] = Field(description="Validator names to run.")
    reasoning: str = Field(description="Why this fix was chosen.")
    max_attempts: int = Field(default=3, ge=1, le=5)
    planning_cycle: int = Field(default=1, ge=1)
    prior_failure_context: Optional[str] = Field(default=None)


class DomainGuess(BaseModel):
    domain: Literal["NETWORK", "STORAGE", "DEV_ENV", "SYSTEM", "UPDATE", "NONE"]
    reason: str


class CommandPlan(BaseModel):
    command: Optional[str] = Field(default=None)
    reason: str = Field(default="")


class VerificationOutcome(BaseModel):
    success: bool
    confidence: float = Field(ge=0.0, le=1.0)
    before: str
    after: str
    verification_summary: str
    recommended_next_step: str


class SupervisorDecision(BaseModel):
    action: Literal["finalize_success", "retry_new_cycle", "escalate"]
    reason: str


# Lazy re-exports for old callers: from agents.models import UpdatePlan
def __getattr__(name: str):
    if name in ("UpdatePlan", "UpdateTarget"):
        from action_graph.models.update_plan import UpdatePlan, UpdateTarget
        return UpdatePlan if name == "UpdatePlan" else UpdateTarget
    if name in ("InstallPlan", "UninstallPlan"):
        mod = __import__(
            "action_graph.models",
            fromlist=[name],
        )
        return getattr(mod, name)
    raise AttributeError(name)
