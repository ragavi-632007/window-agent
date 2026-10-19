from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from langchain_core.language_models import BaseChatModel
from typing_extensions import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agents.rag.nodes import (
    context_assembler_node,
    finalize_node,
    ingester_node,
    intent_refine_node,
    locator_node,
    permission_gate_node,
    retriever_node,
    scope_resolver_node,
    start_rag_cycle_node,
    supervisor_node,
)
from agents.rag.rag_planner import make_discovery_planner_node
from agents.rag.specialized_agents import (
    make_quality_reviewer_node,
    make_specialized_reasoner_node,
)


class FileRagState(TypedDict, total=False):
    user_query: str
    thread_id: str
    workspace_id: str
    mode: str
    rag_task: dict
    discovery_plan: dict
    search_query: str
    search_results: list
    primary_path: str
    rag_plan: dict
    gate_choice: str
    gate_approved: bool
    ingestion_ok: bool
    chunk_count: int
    doc_count: int
    ingest_strategy: str
    attached_text: str
    retrieved_chunks: list
    citations: list
    pinned_snippets: list
    chat_history: list
    assembled_context: str
    retrieved_context: str
    retrieval_queries: list
    rag_answer: dict
    quality_review: dict
    supervisor_decision: dict
    rag_cycle: int
    max_rag_cycles: int
    retry_retrieval_query: str
    last_fix_result: str
    search_summary: str


def _route_after_gate(state: dict) -> str:
    return "ingest" if state.get("gate_approved") else "skip"


def _route_supervisor(state: dict) -> str:
    decision = state.get("supervisor_decision") or {}
    action = decision.get("action", "finalize_success")
    if action == "retry_retrieval":
        return "retry"
    if action == "retry_analysis":
        return "retry_analysis"
    if action == "escalate":
        return "finalize"
    return "finalize"


def _default_checkpoint_path() -> str:
    base = Path(__file__).resolve().parents[2]  # sysdoc/
    mem = base / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    return str(mem / "rag_checkpoints.db")


def build_file_rag_graph(llm: Optional[BaseChatModel] = None):
    g = StateGraph(FileRagState)

    g.add_node("intent_refine", intent_refine_node)
    g.add_node("discovery_planner", make_discovery_planner_node(llm))
    g.add_node("locator", locator_node)
    g.add_node("scope_resolver", scope_resolver_node)
    g.add_node("permission_gate", permission_gate_node)
    g.add_node("ingester", ingester_node)
    g.add_node("retriever", retriever_node)
    g.add_node("context_assembler", context_assembler_node)
    g.add_node("specialized_analyst", make_specialized_reasoner_node(llm))
    g.add_node("quality_reviewer", make_quality_reviewer_node(llm))
    g.add_node("supervisor", supervisor_node)
    g.add_node("start_rag_cycle", start_rag_cycle_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "intent_refine")
    g.add_edge("intent_refine", "discovery_planner")
    g.add_edge("discovery_planner", "locator")
    g.add_edge("locator", "scope_resolver")
    g.add_edge("scope_resolver", "permission_gate")
    g.add_conditional_edges(
        "permission_gate",
        _route_after_gate,
        {"ingest": "ingester", "skip": END},
    )
    g.add_edge("ingester", "retriever")
    g.add_edge("retriever", "context_assembler")
    g.add_edge("context_assembler", "specialized_analyst")
    g.add_edge("specialized_analyst", "quality_reviewer")
    g.add_edge("quality_reviewer", "supervisor")
    g.add_conditional_edges(
        "supervisor",
        _route_supervisor,
        {
            "finalize": "finalize",
            "retry": "start_rag_cycle",
            "retry_analysis": "specialized_analyst",
        },
    )
    g.add_edge("start_rag_cycle", "retriever")
    g.add_edge("finalize", END)

    db_path = os.environ.get("FIXBOT_RAG_CHECKPOINT_DB") or _default_checkpoint_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = g.compile(checkpointer=checkpointer)
    compiled._conn = conn
    return compiled