from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from display.animations import (
    agent_log,
    agent_log_err,
    agent_log_ok,
    agent_log_progress,
    agent_log_scan,
    agent_log_step,
    agent_log_warn,
    typewriter,
)
from agents.rag.chunking import split_documents
from agents.rag.context import assemble_context, pick_attach_vs_rag
from agents.rag.indexer import build_index, retrieve
from agents.rag.loaders import estimate_scope, iter_folder_files, load_single
from agents.rag.models import RagPlan, RagTask, TaskType
from agents.rag.prompts import build_reasoner_prompt
from langgraph.types import interrupt

_TASK_PATTERNS: list[tuple[TaskType, list[str]]] = [
    ("architecture", ["architecture", "structure", "how is it organized", "project structure"]),
    ("summarize", ["summarize", "summary", "tldr", "overview of"]),
    ("outline", ["outline", "presentation outline", "table of contents"]),
    ("compare", ["compare", "difference", "vs ", "versus"]),
    ("extract", ["extract", "list all", "key concepts", "requirements", "apis"]),
    ("explain", ["explain", "what does", "how does", "describe"]),
    ("search_in", ["where is", "find where", "implemented", "which file"]),
    ("qa", ["what is", "who", "when", "why", "answer"]),
]

_QUERY_HINTS = (
    "only from the file", "only from the document", "strictly based",
    "don't use outside", "only use the", "based solely",
)


def _detect_task(text: str) -> TaskType:
    low = text.lower()
    for task, keys in _TASK_PATTERNS:
        if any(k in low for k in keys):
            return task
    return "qa"


def _detect_mode(text: str) -> str:
    low = text.lower()
    if any(h in low for h in _QUERY_HINTS):
        return "query"
    return "chat"


def _extract_target(text: str) -> str:
    low = text.lower()
    for prefix in (
        "find the ", "find my ", "locate the ", "locate my ",
        "search my ", "open the ", "analyze the ", "explain the ",
        "summarize the ", "summarise the ",
        "find ", "locate ", "search ", "open ", "analyze ", "explain ",
        "summarize ", "summarise ",
    ):
        if prefix in low:
            rest = text[low.index(prefix) + len(prefix):]
            for stop in (" and ", " then ", " — ", " - ", ",", "."):
                if stop in rest.lower():
                    rest = rest[: rest.lower().index(stop)]
            return rest.strip(" \"'")
    m = re.search(r'["\']([^"\']+)["\']', text)
    if m:
        return m.group(1)
    return text.strip()


def _workspace_id(path: str) -> str:
    h = hashlib.sha1(path.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"ws_{h}"


def _llm_generate(system: str, user: str) -> str:
    try:
        from core.gemini_client import GeminiClient
        c = GeminiClient()
        # Plain generate — system folded into prompt for compatibility
        return c.generate(f"{system}\n\n{user}") or ""
    except Exception as exc:
        return f"I couldn't generate an answer right now ({exc})."


# ── nodes ─────────────────────────────────────────────────────────────────

def intent_refine_node(state: dict) -> dict:
    raw = state.get("user_query", "")
    agent_log("parser", f'Raw input: "{raw}"')
    task_type = _detect_task(raw)
    mode = _detect_mode(raw)
    target = _extract_target(raw)
    task = RagTask(
        task_type=task_type,
        mode=mode,  # type: ignore[arg-type]
        target_query=target,
        question=raw,
    )
    agent_log_ok(f'Parsed → task={task_type}  mode={mode}  target="{target}"')
    return {
        "rag_task": task.model_dump(),
        "search_query": target,
        "mode": mode,
    }


def locator_node(state: dict) -> dict:
    from modules.file_finder import search_system

    # If discovery planner already found a path, use it directly
    preferred = state.get("primary_path") or ""
    if preferred:
        from pathlib import Path as _P
        p = _P(preferred)
        if p.exists():
            agent_log_ok(f"Locator  using planner path: {preferred}")
            hit = {
                "name": p.name,
                "path": str(p),
                "type": "folder" if p.is_dir() else "file",
            }
            return {"search_results": [hit], "primary_path": preferred}

    query = state.get("search_query") or state.get("user_query", "")
    agent_log("locator", f'Searching system for "{query}"')
    agent_log_step(f'Locator  scanning priority dirs for "{query}"')

    results = search_system(query, match_mode="any_token")

    for i, r in enumerate((results or [])[:8]):
        path = r.get("path") or r.get("full_path") or ""
        agent_log_scan(path[:58] or query, found=i + 1)
        time.sleep(0.03)

    task = state.get("rag_task") or {}
    if task.get("task_type") in ("architecture", "outline") and results:
        folders = [r for r in results if r.get("type") == "folder"]
        if folders:
            results = folders + [r for r in results if r not in folders]

    n = len(results or [])
    if n:
        top = results[0]
        agent_log_ok(
            f"Locator  {n} hit(s) — top: {top.get('name') or top.get('path')}"
        )
    else:
        agent_log_warn(f'Locator  no matches for "{query}"')

    return {"search_results": (results or [])[:15]}


def scope_resolver_node(state: dict) -> dict:
    results = state.get("search_results") or []
    task = state.get("rag_task") or {}

    agent_log("scope", "Resolving primary path and index scope...")

    if not results:
        agent_log_warn("ScopeResolver  nothing to analyze")
        return {
            "rag_plan": RagPlan(
                goal="No files found",
                task=RagTask(**task) if task else RagTask(),
                reasoning="Locator returned zero results",
            ).model_dump(),
            "primary_path": "",
            "workspace_id": "default",
        }

    primary = results[0]
    path = primary.get("path") or primary.get("full_path") or ""
    ws = _workspace_id(path)
    agent_log_step(f"ScopeResolver  estimating scope for {path}")
    est = estimate_scope(path) if path else {"files": 0, "mb": 0.0, "paths": []}

    plan = RagPlan(
        goal=f"{task.get('task_type', 'qa')} on {path}",
        task=RagTask(**task) if task else RagTask(),
        primary_path=path,
        paths=est.get("paths") or [path],
        estimated_files=est.get("files", 0),
        estimated_mb=est.get("mb", 0.0),
        risk_level="medium" if est.get("files", 0) > 30 else "low",
        reasoning=(
            f"Using top hit; ~{est.get('files', 0)} loadable files "
            f"({est.get('mb', 0)} MB)"
        ),
        workspace_id=ws,
    )

    agent_log(
        "scope",
        f"Primary : {path}\n"
        f"Files   : ~{plan.estimated_files}  ({plan.estimated_mb} MB)\n"
        f"Workspace: {ws}\n"
        f"Task    : {plan.goal}",
    )
    agent_log_ok("ScopeResolver  plan ready — waiting for permission")

    return {
        "rag_plan": plan.model_dump(),
        "primary_path": path,
        "workspace_id": ws,
        "thread_id": state.get("thread_id") or ws,
    }


def permission_gate_node(state: dict) -> dict:
    plan = state.get("rag_plan") or {}
    if not plan.get("primary_path"):
        agent_log_warn("PermissionGate  skipped (no path)")
        return {"gate_approved": False, "gate_choice": "n"}

    agent_log_step("PermissionGate  awaiting user confirmation...")
    choice = interrupt({
        "domain": "FILE_RAG",
        "action_plan": plan,
        "gate_mode": "standard",
        "message": (
            f"Index and analyze local content?\n"
            f"  Path : {plan.get('primary_path')}\n"
            f"  Files: ~{plan.get('estimated_files')}  ({plan.get('estimated_mb')} MB)\n"
            f"  Task : {plan.get('goal')}\n"
            f"Proceed? [y/n]"
        ),
    })
    choice_str = str(choice).strip().lower()
    approved = choice_str.startswith("y") or choice_str.startswith("ok")
    if approved:
        agent_log_ok("PermissionGate  approved")
    else:
        agent_log_warn("PermissionGate  declined")
    return {"gate_choice": choice, "gate_approved": approved}


def ingester_node(state: dict) -> dict:
    path = state.get("primary_path") or ""
    thread_id = state.get("thread_id") or state.get("workspace_id") or "default"

    if not path:
        agent_log_err("Ingester  no path")
        return {
            "ingestion_ok": False,
            "chunk_count": 0,
            "doc_count": 0,
            "ingest_strategy": "none",
            "attached_text": "",
        }

    agent_log("ingester", f"Loading content from {path}")
    p = Path(path)

    docs = []
    if p.is_file():
        agent_log_step(f"Ingester  reading file {p.name}")
        docs = load_single(p)
        agent_log_progress("load", 1, 1, p.name)
    else:
        files = list(iter_folder_files(p, max_files=80))
        total = max(len(files), 1)
        agent_log_step(f"Ingester  walking folder ({len(files)} candidate files)")
        for i, fp in enumerate(files, 1):
            agent_log_progress("load", i, total, fp.name)
            docs.extend(load_single(fp))
            time.sleep(0.01)

    total_chars = sum(len(d.page_content or "") for d in docs)
    strategy = pick_attach_vs_rag(len(docs), total_chars)

    if strategy == "attach":
        attached = "\n\n".join(
            f"[{(d.metadata or {}).get('source', path)}]\n{d.page_content}"
            for d in docs
        )
        agent_log_ok(
            f"Ingester  attach mode — full text ({total_chars} chars, {len(docs)} doc(s))"
        )
        return {
            "ingestion_ok": bool(docs),
            "chunk_count": 0,
            "doc_count": len(docs),
            "ingest_strategy": "attach",
            "attached_text": attached,
        }

    agent_log_step("Ingester  chunking + embedding (RAG mode)...")
    chunks = split_documents(docs)
    build_index(chunks, thread_id=thread_id)
    try:
        from agents.rag.indexer import get_embed_backend
        agent_log("ingester", f"Embed backend: {get_embed_backend()}")
    except Exception:
        pass

    agent_log(
        "ingester",
        f"Loaded {len(docs)} document(s)\n"
        f"Chunks  {len(chunks)}\n"
        f"Index   ready (thread={thread_id})",
    )
    agent_log_ok(f"Ingester  RAG mode — {len(docs)} docs → {len(chunks)} chunks")

    return {
        "ingestion_ok": bool(chunks),
        "chunk_count": len(chunks),
        "doc_count": len(docs),
        "ingest_strategy": "rag",
        "attached_text": "",
    }


def retriever_node(state: dict) -> dict:
    task = state.get("rag_task") or {}
    thread_id = state.get("thread_id") or state.get("workspace_id") or "default"
    strategy = state.get("ingest_strategy") or "rag"
    q = task.get("question") or task.get("target_query") or state.get("user_query", "")

    if strategy == "attach":
        agent_log("retriever", "Attach mode — skipping vector search (full doc in context)")
        agent_log_ok("Retriever  using full attached document")
        return {
            "retrieved_chunks": [],
            "citations": [],
        }

    # Multi-query retrieval: use discovery plan queries + task-specific boosts
    queries: list[str] = list(state.get("retrieval_queries") or [])
    if not queries:
        queries = [q]
    task_type = task.get("task_type", "qa")
    if task_type == "architecture" and not state.get("retrieval_queries"):
        queries = [
            f"architecture structure modules entry points dependencies {q}",
            f"main entry point configuration setup {q}",
        ]
    elif task_type == "outline" and not state.get("retrieval_queries"):
        queries = [f"outline sections chapters topics structure {q}"]

    # On retry cycles, use the suggested query from quality reviewer
    retry_q = state.get("retry_retrieval_query") or ""
    if retry_q:
        queries = [retry_q] + queries
        agent_log("retriever", f'Retry cycle {state.get("rag_cycle", 1)} — query: "{retry_q[:60]}"')

    agent_log("retriever", f"Running {len(queries)} retrieval quer{'y' if len(queries) == 1 else 'ies'}")
    agent_log_step("Retriever  semantic search (multi-query + dedup)")

    seen_keys: set[str] = set()
    chunks = []
    citations = []
    rank = 0

    for query in queries[:3]:
        pairs = retrieve(query, thread_id=thread_id, k=6, score_threshold=0.12)
        for h, score in pairs:
            src = (h.metadata or {}).get("source", "?")
            page = (h.metadata or {}).get("page")
            dedup_key = f"{src}:{page}:{hash((h.page_content or '')[:80])}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            rank += 1
            label = f"{src}" + (f" p.{page}" if page else "")
            agent_log_scan(f"{label[:50]}  score={score:.2f}", found=rank)
            text = h.page_content or ""
            chunks.append({
                "source": src,
                "page": page,
                "text": text[:2000],
                "score": score,
            })
            citations.append({
                "source": src,
                "page": page,
                "snippet": text[:180],
                "score": score,
            })
            if rank >= 10:
                break
        if rank >= 10:
            break
        time.sleep(0.02)

    if chunks:
        agent_log_ok(f"Retriever  {len(chunks)} relevant chunk(s) from {len(queries)} queries")
    else:
        agent_log_warn("Retriever  no chunks above threshold")

    return {
        "retrieved_chunks": chunks,
        "citations": citations,
    }


def context_assembler_node(state: dict) -> dict:
    agent_log_step("ContextAssembler  merging sources (pinned + attach + retrieve + history)")

    assembled = assemble_context(
        retrieved_chunks=state.get("retrieved_chunks") or [],
        attached_text=state.get("attached_text") or "",
        pinned_snippets=state.get("pinned_snippets") or [],
        chat_history=state.get("chat_history") or [],
    )

    if assembled:
        agent_log_ok(f"ContextAssembler  {len(assembled)} chars ready for Gemini")
    else:
        agent_log_warn("ContextAssembler  empty context")

    return {"assembled_context": assembled}


def reasoner_node(state: dict) -> dict:
    task = state.get("rag_task") or {}
    mode = task.get("mode") or state.get("mode") or "chat"
    context = state.get("assembled_context") or state.get("retrieved_context") or ""
    question = task.get("question") or state.get("user_query", "")

    agent_log("reasoner", f"Generating ChatGPT-style answer (mode={mode})...")

    if not context.strip():
        if mode == "query":
            msg = (
                "I don't have enough local content to answer in strict mode.\n\n"
                "Try a broader search, open a specific file, or switch to a normal "
                "question so I can help from what we find."
            )
        else:
            msg = (
                "I couldn't load usable content from that location. "
                "Tell me another file/folder name, or paste a path."
            )
        agent_log_warn("Reasoner  empty context")
        return {
            "rag_answer": {
                "answer": msg,
                "citations": [],
                "confidence": 0.0,
                "follow_ups": [],
            }
        }

    system, user = build_reasoner_prompt(
        task.get("task_type", "qa"),
        mode,
        question,
        context,
    )

    agent_log_step("Reasoner  calling Gemini...")
    text = _llm_generate(system, user)

    preview = (text or "").replace("\n", " ")[:110]
    if preview:
        typewriter(f"  → {preview}...", color="green", delay=0.006)

    agent_log_ok("Reasoner  answer ready")
    return {
        "rag_answer": {
            "answer": text or "",
            "citations": state.get("citations") or [],
            "confidence": 0.8 if context else 0.2,
            "follow_ups": [],
        }
    }


def supervisor_node(state: dict) -> dict:
    from agents.rag.models import RagSupervisorDecision

    answer = state.get("rag_answer") or {}
    review = state.get("quality_review") or {}
    cycle = state.get("rag_cycle", 1)
    max_cycles = state.get("max_rag_cycles", 2)

    agent_log_step(f"Supervisor  evaluating outcome (cycle {cycle}/{max_cycles})...")

    if not state.get("primary_path"):
        decision = RagSupervisorDecision(
            action="escalate",
            reason="Nothing found to analyze",
        )
        agent_log_err(f"Supervisor  {decision.reason}")
    elif review.get("passes") and answer.get("answer"):
        decision = RagSupervisorDecision(
            action="finalize_success",
            reason="Quality review passed — grounded answer ready",
        )
        agent_log_ok(f"Supervisor  {decision.reason}")
    elif cycle < max_cycles and review.get("suggested_retrieval_query"):
        decision = RagSupervisorDecision(
            action="retry_retrieval",
            reason=f"Cycle {cycle}: retrying with broader retrieval",
        )
        agent_log_warn(f"Supervisor  {decision.reason}")
    elif cycle < max_cycles and not review.get("passes"):
        decision = RagSupervisorDecision(
            action="retry_analysis",
            reason=f"Cycle {cycle}: re-analyzing with same context",
        )
        agent_log_warn(f"Supervisor  {decision.reason}")
    elif answer.get("answer") and (state.get("ingestion_ok") or state.get("assembled_context")):
        decision = RagSupervisorDecision(
            action="finalize_success",
            reason="Best-effort answer after retries",
        )
        agent_log_warn(f"Supervisor  {decision.reason}")
    else:
        decision = RagSupervisorDecision(
            action="escalate",
            reason="Could not produce a satisfactory answer",
        )
        agent_log_err(f"Supervisor  {decision.reason}")

    return {"supervisor_decision": decision.model_dump()}


def start_rag_cycle_node(state: dict) -> dict:
    """Increment cycle and prepare for retry."""
    review = state.get("quality_review") or {}
    cycle = state.get("rag_cycle", 1) + 1
    agent_log_step(f"Starting RAG retry cycle {cycle}...")
    return {
        "rag_cycle": cycle,
        "retry_retrieval_query": review.get("suggested_retrieval_query", ""),
        "assembled_context": "",
        "retrieved_chunks": [],
        "rag_answer": {},
        "quality_review": {},
    }


def finalize_node(state: dict) -> dict:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    console = Console()
    answer = state.get("rag_answer") or {}
    text = answer.get("answer") or "No answer."
    cites = answer.get("citations") or []

    agent_log("summary", "Rendering final analysis...")

    console.print()
    console.print(Panel(
        Markdown(text),
        title="[bold cyan]Local Document Chat[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))

    # Sources footer if model omitted them but we have citations
    if cites and "sources" not in text.lower():
        console.print("\n  [bold]Sources[/bold]")
        seen = set()
        for c in cites:
            src = c.get("source")
            if src and src not in seen:
                page = c.get("page")
                console.print(
                    f"  [cyan]•[/cyan] {src}"
                    + (f"  [dim](p.{page})[/dim]" if page else "")
                )
                seen.add(src)

    follow_ups = answer.get("follow_ups") or []
    if follow_ups:
        console.print("\n  [bold]You might also ask[/bold]")
        for fu in follow_ups[:3]:
            console.print(f"  [dim]•[/dim] {fu}")

    console.print()
    agent_log_ok("FileRAG  complete")
    return {
        "last_fix_result": "rag_complete",
        "search_summary": text[:500],
    }