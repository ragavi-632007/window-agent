from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

TaskType = Literal[
    "summarize",
    "explain",
    "qa",
    "compare",
    "architecture",
    "outline",
    "extract",
    "search_in",
]

ChatMode = Literal["chat", "query"]


class RagTask(BaseModel):
    task_type: TaskType = "qa"
    mode: ChatMode = "chat"  # chat = helpful ChatGPT-style; query = strict RAG-only
    target_query: str = Field(default="", description="Name/path fragment to locate")
    question: str = Field(default="", description="User question or instruction")
    focus: str = Field(default="", description="Optional focus e.g. Chapter 3")


class RagPlan(BaseModel):
    goal: str
    task: RagTask
    primary_path: str = ""
    paths: List[str] = Field(default_factory=list)
    estimated_files: int = 0
    estimated_mb: float = 0.0
    risk_level: Literal["low", "medium", "high"] = "low"
    reasoning: str = ""
    max_chunks: int = 12
    workspace_id: str = "default"


class RagAnswer(BaseModel):
    answer: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0
    follow_ups: List[str] = Field(default_factory=list)


class RagDiscoveryPlan(BaseModel):
    """Output from the Discovery Planner agent — refined search & analysis strategy."""

    search_query: str = Field(description="Refined query to locate files/folders")
    task_type: TaskType = "qa"
    mode: ChatMode = "chat"
    focus: str = Field(default="", description="Specific section or aspect to emphasize")
    preferred_path: str = Field(default="", description="Best path if already identified")
    ingest_strategy_hint: Literal["attach", "rag", "auto"] = "auto"
    retrieval_queries: List[str] = Field(
        default_factory=list,
        description="1-3 semantic search queries for the retriever",
    )
    reasoning: str = ""
    confidence: float = 0.7


class QualityReview(BaseModel):
    """Output from the Quality Reviewer agent."""

    passes: bool = Field(description="True if answer is grounded and complete enough")
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    issues: List[str] = Field(default_factory=list)
    suggested_retrieval_query: str = Field(
        default="",
        description="If retry needed, a broader or different retrieval query",
    )
    follow_ups: List[str] = Field(default_factory=list)


class RagSupervisorDecision(BaseModel):
    action: Literal["finalize_success", "retry_retrieval", "retry_analysis", "escalate"]
    reason: str = ""