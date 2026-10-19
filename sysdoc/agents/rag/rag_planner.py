"""RAG Discovery Planner — LLM agent that refines search strategy before indexing."""
from __future__ import annotations

from typing import Callable, Optional

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from agents.rag.models import RagDiscoveryPlan, RagTask
from agents.rag.tools_rag import make_rag_tools
from display.animations import agent_log, agent_log_ok, agent_log_step, agent_log_warn

DISCOVERY_PLANNER_PROMPT = """You are the Discovery Planner for Fixbot's local file analysis pipeline.

Your job is to understand what the user wants and plan how to find and analyze it.

You have read-only tools:
- search_local_files: find files/folders on the machine
- estimate_index_scope: check how big a folder is before indexing
- list_project_tree: see directory structure for architecture questions
- preview_file: quick peek at a file before full analysis

Steps:
1. Parse the user's intent (summarize, explain, architecture, compare, extract, qa, etc.)
2. Use search_local_files to locate the target if you don't have a concrete path
3. For architecture/structure questions, call list_project_tree on the best folder
4. For large folders, call estimate_index_scope to understand scope
5. Optionally preview_file to confirm you found the right content

Produce a RagDiscoveryPlan with:
- search_query: refined search terms
- task_type: best matching task type
- mode: "query" (strict, context-only) or "chat" (conversational)
- focus: optional section/aspect to emphasize
- preferred_path: best path found (empty if none)
- retrieval_queries: 1-3 semantic search queries tailored to the task
- reasoning: brief explanation of your plan
- confidence: 0.0-1.0

Do not index or modify files. Do not ask the user questions — make your best judgment."""


def make_discovery_planner_node(
    llm: Optional[BaseChatModel] = None,
) -> Callable[[dict], dict]:
    """Build the discovery planner node. Falls back to regex intent if no LLM."""

    def discovery_planner_node(state: dict) -> dict:
        raw = state.get("user_query", "")
        task = state.get("rag_task") or {}
        thread_id = state.get("thread_id") or "default"

        agent_log("planner", "Discovery Planner analyzing request...")

        if llm is None:
            agent_log_warn("Discovery Planner  no LLM — using regex intent only")
            return {}

        try:
            tools = make_rag_tools(thread_id=thread_id)
            agent = create_agent(
                model=llm,
                tools=tools,
                response_format=RagDiscoveryPlan,
                system_prompt=DISCOVERY_PLANNER_PROMPT,
            )

            agent_log_step("Discovery Planner  searching & scoping with tools...")
            result = agent.invoke({
                "messages": [(
                    "user",
                    f"User request: {raw}\n"
                    f"Initial parse: task={task.get('task_type', 'qa')}, "
                    f"target={task.get('target_query', '')}, mode={task.get('mode', 'chat')}",
                )],
            })
            plan: RagDiscoveryPlan = result["structured_response"]

            agent_log_ok(
                f"Discovery Planner  task={plan.task_type}  "
                f"path={plan.preferred_path or '(search)'}  "
                f"confidence={plan.confidence:.0%}"
            )
            agent_log("planner", plan.reasoning[:200] if plan.reasoning else "")

            # Prefer chat for open-ended understanding verbs unless user forced query
            mode = plan.mode
            low = raw.lower()
            strict = any(h in low for h in (
                "only from the file", "only from the document", "strictly based",
                "don't use outside", "only use the", "based solely",
            ))
            explainish = any(w in low for w in (
                "explain", "summarize", "summarise", "describe", "what is",
                "architecture", "structure", "tell me about", "overview",
            ))
            if strict:
                mode = "query"
            elif explainish:
                mode = "chat"

            updated_task = RagTask(
                task_type=plan.task_type,
                mode=mode,
                target_query=plan.search_query or task.get("target_query", ""),
                question=raw,
                focus=plan.focus,
            )

            out: dict = {
                "rag_task": updated_task.model_dump(),
                "search_query": plan.search_query or task.get("target_query", ""),
                "mode": mode,
                "discovery_plan": plan.model_dump(),
                "retrieval_queries": plan.retrieval_queries or [],
            }
            if plan.preferred_path:
                out["primary_path"] = plan.preferred_path
            return out

        except Exception as exc:
            agent_log_warn(f"Discovery Planner  failed ({exc}) — keeping regex parse")
            return {}

    return discovery_planner_node
