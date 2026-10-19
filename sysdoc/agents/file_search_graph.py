"""FILE_SEARCH autonomous LangGraph pipeline (isolated domain).

Flow (offline-first, no Gemini required):
  parse_query → search_executor → verifier → supervisor
      ├─ success → rank_results → summarize → END
      ├─ retry   → start_new_cycle → parse_query
      └─ escalate → summarize → END

Match escalation:
  Cycle 1 strict → Cycle 2 any_token → Cycle 3 fuzzy
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from display.animations import (
    agent_log,
    agent_log_ok,
    agent_log_scan,
    agent_log_step,
    agent_log_warn,
)

MAX_SEARCH_CYCLES = 3

_STRATEGY_BY_CYCLE = {
    1: ("strict", "exact multi-token match — all terms must appear"),
    2: ("any_token", "broadened — matching ANY term"),
    3: ("fuzzy", "fuzzy — partial matches and name variants"),
}

_QUERY_FILLER = frozenset({
    "my", "the", "a", "an", "file", "files", "folder", "folders",
    "app", "application", "named", "called", "name", "find", "search",
    "locate", "where", "is", "are", "please", "show", "me", "for",
    "looking", "look", "get", "open",
})

# Prefer user-facing locations when ranking
_PATH_BOOST = (
    ("\\desktop\\", 30),
    ("/desktop/", 30),
    ("\\documents\\", 25),
    ("/documents/", 25),
    ("\\downloads\\", 20),
    ("/downloads/", 20),
    ("\\users\\", 10),
)


class FileSearchState(TypedDict, total=False):
    user_query: str
    search_query: str
    search_tokens: list
    search_strategy: str
    search_results: list
    ranked_results: list
    search_summary: str
    phases_scanned: list
    planning_cycle: int
    attempts_made: list
    cycle_history: list
    verification: dict
    supervisor_decision: dict


def normalize_search_query(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text
    # strip common intent verbs at edges
    words = text.split()
    while words and words[0].lower() in _QUERY_FILLER:
        words.pop(0)
    while words and words[-1].lower() in _QUERY_FILLER:
        words.pop()
    cleaned = " ".join(words).strip()
    return cleaned or text.strip()


def _strategy_for_cycle(cycle: int) -> tuple[str, str]:
    return _STRATEGY_BY_CYCLE.get(cycle, _STRATEGY_BY_CYCLE[MAX_SEARCH_CYCLES])


# ── Nodes ─────────────────────────────────────────────────────────────────

def _parse_query_node(state: dict) -> dict:
    raw = state.get("user_query", "")
    cycle = int(state.get("planning_cycle") or 1)
    mode, mode_desc = _strategy_for_cycle(cycle)

    if cycle == 1:
        agent_log("parser", f'Raw input: "{raw}"')
    else:
        agent_log_warn(f"Supervisor retry — cycle {cycle}/{MAX_SEARCH_CYCLES}")

    normalized = normalize_search_query(raw)
    tokens = [t for t in re.split(r"[\s\-_]+", normalized.lower()) if t and len(t) > 1]

    # On later cycles, widen query slightly (variants)
    query = normalized
    if cycle == 2 and tokens:
        query = " ".join(tokens)  # already any_token mode
    elif cycle >= 3 and tokens:
        # longest token often most distinctive
        tokens_sorted = sorted(tokens, key=len, reverse=True)
        query = tokens_sorted[0]

    agent_log_step(f'Query: "{query}"  |  strategy: {mode}')
    agent_log_step(mode_desc)
    if tokens:
        agent_log_step(f"Tokens: [{', '.join(tokens)}]")

    return {
        "search_query": query,
        "search_tokens": tokens,
        "search_strategy": mode,
        "phases_scanned": [],
    }


def _search_executor_node(state: dict) -> dict:
    from modules import file_finder

    query = state.get("search_query", "")
    mode = state.get("search_strategy", "strict")
    cycle = int(state.get("planning_cycle") or 1)
    phases: list = []
    attempts = list(state.get("attempts_made") or [])
    attempts.append(f"cycle{cycle}:{mode}:{query}")

    agent_log("executor", f'Cycle {cycle} — scanning for "{query}" ({mode})...')

    def on_progress(phase: str, detail: str, found: int) -> None:
        phases.append(phase)
        if phase == "scanning":
            agent_log_scan(detail, found)
        elif phase in ("path", "priority", "drives"):
            agent_log_step(detail)
        elif phase == "done":
            agent_log_ok(detail)

    results = file_finder.search_system(
        query, on_progress=on_progress, match_mode=mode
    )

    agent_log_ok(f"Executor  {len(results)} raw hit(s)")
    return {
        "search_results": results or [],
        "phases_scanned": phases,
        "attempts_made": attempts,
    }


def _verifier_node(state: dict) -> dict:
    results = state.get("search_results") or []
    query = state.get("search_query", "")
    mode = state.get("search_strategy", "strict")
    success = len(results) > 0

    if success:
        agent_log_ok(f"Verified {len(results)} match(es) for \"{query}\" via {mode}")
        summary = f"Found {len(results)} result(s) using {mode}."
    else:
        agent_log_warn(f"No matches for \"{query}\" with {mode}.")
        summary = f"No results with {mode} on cycle {state.get('planning_cycle', 1)}."

    return {
        "verification": {
            "success": success,
            "verification_summary": summary,
            "match_count": len(results),
        }
    }


def _supervisor_decide_node(state: dict) -> dict:
    verification = state.get("verification") or {}
    cycle = int(state.get("planning_cycle") or 1)
    success = bool(verification.get("success"))

    if success:
        action, reason = "finalize_success", (
            f"Search succeeded on cycle {cycle} — "
            f"{verification.get('match_count', 0)} file(s)."
        )
        agent_log_ok(f"Supervisor: {reason}")
    elif cycle < MAX_SEARCH_CYCLES:
        nxt = _STRATEGY_BY_CYCLE.get(cycle + 1, ("fuzzy", "broader"))[0]
        action, reason = "retry_new_cycle", (
            f"Cycle {cycle} empty — retry with {nxt}."
        )
        agent_log_warn(f"Supervisor: {reason}")
    else:
        action, reason = "escalate", (
            f"All {MAX_SEARCH_CYCLES} cycles exhausted — no matches."
        )
        agent_log_warn(f"Supervisor: {reason}")

    history = {
        "cycle": cycle,
        "strategy": state.get("search_strategy"),
        "query": state.get("search_query"),
        "attempts_made": state.get("attempts_made") or [],
        "verification": verification,
    }
    return {
        "supervisor_decision": {"action": action, "reason": reason},
        "cycle_history": (state.get("cycle_history") or []) + [history],
    }


def _route_supervisor(state: dict) -> str:
    action = (state.get("supervisor_decision") or {}).get("action", "escalate")
    if action == "finalize_success":
        return "rank"
    if action == "retry_new_cycle":
        return "retry"
    return "escalate"


def _start_new_cycle_node(state: dict) -> dict:
    cycle = int(state.get("planning_cycle") or 1) + 1
    agent_log_step(f"Starting search cycle {cycle}/{MAX_SEARCH_CYCLES}...")
    return {
        "planning_cycle": cycle,
        "search_results": [],
        "ranked_results": [],
        "verification": None,
        "supervisor_decision": None,
    }


def _score_result(item: dict, query: str, tokens: list) -> float:
    name = (item.get("name") or "").lower()
    path = (item.get("path") or "").lower()
    q = (query or "").lower()
    score = 0.0

    try:
        from modules.file_finder import _fuzzy_score
        score += _fuzzy_score(q, name) * 0.8  # 0–80
        q_compact = re.sub(r"[\s\-_]+", "", q)
        n_compact = re.sub(r"[\s\-_]+", "", name)
        score += _fuzzy_score(q_compact, n_compact) * 0.4
    except Exception:
        if name == q:
            score += 100
        elif q in name:
            score += 60

    if tokens:
        hits = sum(1 for t in tokens if t in name)
        score += hits * 10

    for needle, boost in _PATH_BOOST:
        if needle in path:
            score += boost
            break

    if item.get("type") == "folder":
        score += 5
    if "node_modules" in path or "\\.git\\" in path:
        score -= 40

    return score


def _rank_results_node(state: dict) -> dict:
    results = list(state.get("search_results") or [])
    query = state.get("search_query") or ""
    tokens = state.get("search_tokens") or []

    agent_log_step(f"Ranker  scoring {len(results)} hit(s)...")
    scored = []
    for r in results:
        s = _score_result(r, query, tokens)
        rr = dict(r)
        rr["score"] = round(s, 1)
        scored.append(rr)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    if scored:
        top = scored[0]
        agent_log_ok(
            f"Ranker  top: {top.get('name')} (score={top.get('score')})"
        )
    return {"ranked_results": scored, "search_results": scored}


def _summarize_node(state: dict) -> dict:
    results = state.get("ranked_results") or state.get("search_results") or []
    query = state.get("search_query", "")
    cycle = int(state.get("planning_cycle") or 1)
    decision = state.get("supervisor_decision") or {}

    if not results:
        summary = (
            f'No files or folders matching "{query}" after '
            f"{cycle} search cycle(s)."
        )
        agent_log("summarizer", summary)
    else:
        lines = [
            f'Found {len(results)} result(s) for "{query}" (cycle {cycle}):'
        ]
        for i, r in enumerate(results[:8], 1):
            sc = r.get("score")
            sc_s = f"  score={sc}" if sc is not None else ""
            lines.append(
                f"  {i}. {r.get('name')}  →  {r.get('path')}{sc_s}"
            )
        if len(results) > 8:
            lines.append(f"  ... and {len(results) - 8} more")
        summary = "\n".join(lines)
        agent_log_ok(
            decision.get("reason", f"Search complete — {len(results)} match(es)")
        )
        agent_log("summarizer", summary)

    return {"search_summary": summary}


def build_file_search_graph():
    """Compile FILE_SEARCH graph. Does not touch INSTALL/UPDATE/RAG."""
    g = StateGraph(FileSearchState)
    g.add_node("parse_query", _parse_query_node)
    g.add_node("search_executor", _search_executor_node)
    g.add_node("verifier", _verifier_node)
    g.add_node("supervisor_decide", _supervisor_decide_node)
    g.add_node("start_new_cycle", _start_new_cycle_node)
    g.add_node("rank_results", _rank_results_node)
    g.add_node("summarize", _summarize_node)

    g.add_edge(START, "parse_query")
    g.add_edge("parse_query", "search_executor")
    g.add_edge("search_executor", "verifier")
    g.add_edge("verifier", "supervisor_decide")
    g.add_conditional_edges(
        "supervisor_decide",
        _route_supervisor,
        {
            "rank": "rank_results",
            "retry": "start_new_cycle",
            "escalate": "summarize",
        },
    )
    g.add_edge("start_new_cycle", "parse_query")
    g.add_edge("rank_results", "summarize")
    g.add_edge("summarize", END)
    return g.compile()


def run_file_search(user_query: str) -> dict:
    """Convenience API for main.py — returns final state dict."""
    graph = build_file_search_graph()
    return graph.invoke(
        {
            "user_query": user_query,
            "planning_cycle": 1,
            "attempts_made": [],
            "cycle_history": [],
        }
    )