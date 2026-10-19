"""GitPilot — guided UI + autonomous Git Action Graph."""
from __future__ import annotations

__all__ = [
    "run_git_agent",
    "run_git_readonly",
    "build_git_graph",
    "classify_git_query",
    "get_last_repo_path",
]


def __getattr__(name: str):
    if name in ("run_git_agent", "run_git_readonly", "build_git_graph"):
        from gitpilot import graph as _g
        return getattr(_g, name)
    if name == "classify_git_query":
        from gitpilot.classify import classify_git_query
        return classify_git_query
    if name == "get_last_repo_path":
        from gitpilot.shared_state import get_last_repo_path
        return get_last_repo_path
    raise AttributeError(name)
