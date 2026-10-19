"""Git Action Graph — LangGraph pipeline for mutating git ops."""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from gitpilot.nodes import (
    error_analyzer_node,
    executor_node,
    inspect_node,
    permission_gate_node,
    planner_node,
    report_node,
    resolve_repo_node,
    route_supervisor,
    supervisor_node,
    verifier_node,
)


class GitAgentState(TypedDict, total=False):
    user_query: str
    git_kind: str
    repo_path: str
    preferred_path: str
    clone_dest: str
    repo_ok: bool
    inspect: dict
    inspect_after: dict
    git_plan: dict
    commit_message: str
    approved: bool
    gate_choice: str
    auto_approve: bool
    last_approved_sig: str
    step_results: list
    last_error: str
    executor_ok: bool
    verification: dict
    error_analysis: dict
    supervisor_decision: dict
    strategy_hint: str
    planning_cycle: int
    attempts_made: list
    report: dict
    messages: list


def build_git_graph():
    g = StateGraph(GitAgentState)
    g.add_node("resolve_repo", resolve_repo_node)
    g.add_node("inspect", inspect_node)
    g.add_node("planner", planner_node)
    g.add_node("permission_gate", permission_gate_node)
    g.add_node("executor", executor_node)
    g.add_node("verifier", verifier_node)
    g.add_node("error_analyzer", error_analyzer_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("report", report_node)

    g.add_edge(START, "resolve_repo")
    g.add_edge("resolve_repo", "inspect")
    g.add_edge("inspect", "planner")
    g.add_edge("planner", "permission_gate")
    g.add_edge("permission_gate", "executor")
    g.add_edge("executor", "verifier")
    g.add_edge("verifier", "error_analyzer")
    g.add_edge("error_analyzer", "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "retry": "planner",  # Analyzer did not execute
            "report": "report",
        },
    )
    g.add_edge("report", END)
    return g.compile()


def run_git_agent(
    user_query: str,
    repo_path: Optional[str] = None,
    auto_approve: bool = False,
    git_kind: Optional[str] = None,
) -> dict[str, Any]:
    from gitpilot.classify import classify_git_query

    graph = build_git_graph()
    kind = git_kind or classify_git_query(user_query)
    initial: dict[str, Any] = {
        "user_query": user_query,
        "git_kind": kind,
        "planning_cycle": 1,
        "attempts_made": [],
        "auto_approve": auto_approve,
    }
    if repo_path:
        initial["repo_path"] = repo_path
        initial["preferred_path"] = repo_path
    return graph.invoke(initial)


def run_git_readonly(user_query: str, repo_path: Optional[str] = None) -> str:
    """Fast path: status / log / branch / remote / diff — no graph."""
    import os

    from gitpilot import git_ops
    from gitpilot import shared_state

    path = os.path.abspath(
        os.path.expanduser(
            repo_path or shared_state.get_last_repo_path() or os.getcwd()
        )
    )
    if not git_ops.is_git_repo(path):
        cur = path
        for _ in range(10):
            if git_ops.is_git_repo(cur):
                path = cur
                break
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    if not git_ops.is_git_repo(path):
        return f"Not a git repository: {path}"

    shared_state.set_last_repo_path(path)
    q = user_query.lower()
    lines = [f"Repo: {path}", f"Branch: {git_ops.get_branch(path)}"]

    if any(w in q for w in ("log", "history", "commits")):
        out, err, code = git_ops.get_log(path, n=10)
        lines.append(out or err or f"exit {code}")
    elif any(w in q for w in ("diff", "changes")):
        out, err, code = git_ops.get_diff_stat(path)
        lines.append(out or err or "no diff")
    elif "remote" in q:
        out, err, code = git_ops.get_remote(path)
        lines.append(out or err or "no remotes")
    elif any(w in q for w in ("branch", "branches")):
        lines.append("Branches: " + ", ".join(git_ops.get_local_branches(path) or []))
    else:
        out, err, code = git_ops.get_status(path)
        lines.append(out or err or f"exit {code}")

    return "\n".join(lines)
