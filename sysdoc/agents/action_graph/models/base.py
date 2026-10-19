"""Base plan model shared by every actionable domain.

Every domain plan (InstallPlan, UpdatePlan, UninstallPlan, …) inherits
ActionPlan and adds its own domain-specific fields on top.

ActionResult is the execution receipt written by the Executor node.
It is NOT a Pydantic model — it lives as a plain dict in state so the
checkpointer never chokes on an unregistered class.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]


class ActionPlan(BaseModel):
    """Fields every domain plan must carry.

    Nodes downstream (Permission Gate, Executor, Verifier, Error Analyzer,
    Supervisor) only read these common fields plus the domain-specific
    additions in each subclass.
    """

    # ── what are we doing ─────────────────────────────────────────────────
    goal: str = Field(
        description="Plain-language statement of intent, e.g. 'Install Discord'."
    )
    domain: str = Field(
        description="Domain this plan belongs to: 'INSTALL', 'UPDATE', 'UNINSTALL', …"
    )

    # ── what exactly are we acting on ─────────────────────────────────────
    # Plans that operate on a single target set these.
    # Plans that operate on a list of packages (UPDATE, UNINSTALL) override
    # with a packages field in the subclass; these stay empty strings.
    target_name: str = Field(
        default="",
        description="Human-readable target, e.g. 'Discord'.",
    )
    target_id: str = Field(
        default="",
        description="Canonical package / service / registry ID, e.g. 'Discord.Discord'.",
    )
    manager: str = Field(
        default="winget",
        description="Package manager or execution context: 'winget', 'pip', 'npm', 'sc', …",
    )

    # ── how ───────────────────────────────────────────────────────────────
    strategy: str = Field(
        description="Starting strategy from the domain's escalation chain."
    )
    risk_level: Risk = Field(
        default="low",
        description="Risk assessment. Controls permission gate display mode.",
    )

    # ── recovery ──────────────────────────────────────────────────────────
    rollback_strategy: str = Field(
        default="",
        description="What to attempt if all retries are exhausted.",
    )
    verification: List[str] = Field(
        default_factory=list,
        description="Validator names the Verifier should run, in order.",
    )

    # ── metadata ──────────────────────────────────────────────────────────
    reasoning: str = Field(
        description="Why this plan was chosen. Shown at the permission gate."
    )
    max_attempts: int = Field(default=3, ge=1, le=5)
    planning_cycle: int = Field(default=1, ge=1)
    prior_failure_context: Optional[str] = Field(
        default=None,
        description="Error Analyzer summary from the previous cycle, if any.",
    )


class ActionResult(BaseModel):
    """Execution receipt produced by the Executor node.

    Stored as .model_dump() in state["execution_results"] (a list, one
    entry per package / target).  Nodes that need attribute access do
    ActionResult(**entry).
    """
    name: str
    target_id: str
    manager: str
    success: bool
    strategy_used: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    output: str = ""       # stdout + stderr combined, trimmed to 500 chars
