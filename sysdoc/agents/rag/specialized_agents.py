"""Task-specialized analysis agents for FILE_RAG."""
from __future__ import annotations

from typing import Callable, Optional

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from agents.rag.models import QualityReview, RagAnswer
from agents.rag.prompts import QUALITY_REVIEW_SYSTEM, build_specialized_prompt
from display.animations import agent_log, agent_log_ok, agent_log_step, agent_log_warn, typewriter


def _llm_generate_long(system: str, user: str) -> str:
    try:
        from core.gemini_client import GeminiClient
        from config import MAX_TOKENS_RAG_EXPLAIN
        c = GeminiClient()
        return c.generate_long(
            f"{system}\n\n{user}",
            max_tokens=MAX_TOKENS_RAG_EXPLAIN,
        ) or ""
    except Exception as exc:
        return f"I couldn't generate an answer right now ({exc})."


def make_specialized_reasoner_node(
    llm: Optional[BaseChatModel] = None,
) -> Callable[[dict], dict]:

    def specialized_reasoner_node(state: dict) -> dict:
        task = state.get("rag_task") or {}
        mode = task.get("mode") or state.get("mode") or "chat"
        context = state.get("assembled_context") or ""
        question = task.get("question") or state.get("user_query", "")
        task_type = task.get("task_type", "qa")
        focus = task.get("focus", "")

        agent_log("analyst", f"Specialized agent [{task_type}] generating answer...")

        if not context.strip():
            msg = (
                "I don't have enough local content to answer in strict mode."
                if mode == "query"
                else "I couldn't load usable content from that location. "
                     "Try another file name or paste a full path."
            )
            agent_log_warn(f"Analyst [{task_type}]  empty context")
            return {
                "rag_answer": RagAnswer(answer=msg, confidence=0.0).model_dump(),
            }

        system, user = build_specialized_prompt(
            task_type, mode, question, context, focus=focus,
        )

        agent_log_step(f"Analyst [{task_type}]  calling LLM (long-form)...")
        text = _llm_generate_long(system, user)
        follow_ups: list[str] = []

        if (not text or len(text) < 80) and llm is not None:
            try:
                agent = create_agent(
                    model=llm,
                    tools=[],
                    response_format=RagAnswer,
                    system_prompt=system,
                )
                result = agent.invoke({"messages": [("user", user)]})
                answer: RagAnswer = result["structured_response"]
                text = answer.answer or text
                follow_ups = answer.follow_ups or []
            except Exception:
                pass

        preview = (text or "").replace("\n", " ")[:110]
        if preview:
            typewriter(f"  → {preview}...", color="green", delay=0.006)

        agent_log_ok(f"Analyst [{task_type}]  answer ready ({len(text or '')} chars)")
        return {
            "rag_answer": RagAnswer(
                answer=text or "",
                citations=state.get("citations") or [],
                confidence=0.85 if context else 0.2,
                follow_ups=follow_ups,
            ).model_dump(),
        }

    return specialized_reasoner_node


def make_quality_reviewer_node(
    llm: Optional[BaseChatModel] = None,
) -> Callable[[dict], dict]:

    def quality_reviewer_node(state: dict) -> dict:
        answer = state.get("rag_answer") or {}
        context = state.get("assembled_context") or ""
        task = state.get("rag_task") or {}
        text = answer.get("answer") or ""
        task_type = task.get("task_type", "qa")
        cycle = int(state.get("rag_cycle") or 1)

        agent_log_step("Quality Reviewer  checking groundedness & completeness...")

        depth_tasks = {"explain", "architecture", "outline", "summarize"}
        min_len = 800 if task_type in depth_tasks else 200

        if not text.strip() or len(text) < 40:
            review = QualityReview(
                passes=False, score=0.1,
                issues=["Answer too short or empty"],
                suggested_retrieval_query=task.get("question", ""),
            )
            agent_log_warn("Quality Reviewer  failed — empty answer")
            return {"quality_review": review.model_dump()}

        if not context.strip():
            review = QualityReview(
                passes=False, score=0.2,
                issues=["No context was assembled"],
            )
            return {"quality_review": review.model_dump()}

        if task_type in depth_tasks and len(text) < min_len and cycle < 2:
            review = QualityReview(
                passes=False,
                score=0.45,
                issues=[
                    f"Answer too short for {task_type} "
                    f"({len(text)} chars; want ≥{min_len})"
                ],
                suggested_retrieval_query=task.get("question", ""),
                follow_ups=answer.get("follow_ups") or [],
            )
            agent_log_warn(
                f"Quality Reviewer  needs deeper answer ({len(text)} < {min_len} chars)"
            )
            return {"quality_review": review.model_dump()}

        if llm is not None and len(text) > 100:
            try:
                agent = create_agent(
                    model=llm,
                    tools=[],
                    response_format=QualityReview,
                    system_prompt=QUALITY_REVIEW_SYSTEM,
                )
                result = agent.invoke({"messages": [(
                    "user",
                    f"Task: {task_type}\n"
                    f"Question: {task.get('question', '')}\n\n"
                    f"Context length: {len(context)} chars\n"
                    f"Context preview:\n{context[:1500]}\n\n"
                    f"Draft answer ({len(text)} chars):\n{text[:4000]}",
                )]})
                review: QualityReview = result["structured_response"]
                if task_type in depth_tasks and len(text) < min_len:
                    review.passes = False
                    review.issues = list(review.issues or []) + [
                        f"Below minimum depth ({len(text)} < {min_len})"
                    ]
                follow_ups = answer.get("follow_ups") or []
                if review.follow_ups and not follow_ups:
                    answer = {**answer, "follow_ups": review.follow_ups}

                if review.passes:
                    agent_log_ok(f"Quality Reviewer  passed (score={review.score:.0%})")
                else:
                    agent_log_warn(
                        f"Quality Reviewer  needs improvement (score={review.score:.0%})"
                    )
                return {"quality_review": review.model_dump(), "rag_answer": answer}
            except Exception as exc:
                agent_log_warn(f"Quality Reviewer  LLM failed ({exc}) — heuristic pass")

        has_citations = "[" in text and "]" in text
        has_headings = "##" in text or "###" in text
        score = 0.55
        if len(text) >= min_len:
            score += 0.2
        if has_citations:
            score += 0.1
        if has_headings:
            score += 0.1
        threshold = 0.75 if task_type in depth_tasks else 0.65
        review = QualityReview(
            passes=score >= threshold,
            score=min(score, 1.0),
            issues=[] if score >= threshold else [
                "Answer may lack depth, citations, or structure"
            ],
            follow_ups=answer.get("follow_ups") or [],
        )
        agent_log_ok(f"Quality Reviewer  heuristic (score={review.score:.0%})")
        return {"quality_review": review.model_dump()}

    return quality_reviewer_node