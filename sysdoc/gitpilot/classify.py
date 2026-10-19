"""Groq-fast GIT intent classify (fallback: rules)."""
from __future__ import annotations

from typing import Literal

GitKind = Literal[
    "readonly",
    "push",
    "commit",
    "pull",
    "branch",
    "merge",
    "stash",
    "clone",
    "coach",
    "unknown",
]


def classify_git_query_rules(query: str) -> GitKind:
    q = (query or "").lower().strip()
    if q in ("fixgit", "gitpilot", "git pilot", "open gitpilot"):
        return "coach"
    if any(w in q for w in ("clone ", "git clone", "clone repo", "clone the")):
        return "clone"
    if any(w in q for w in ("merge ", "git merge")):
        return "merge"
    if any(w in q for w in ("stash",)):
        return "stash"
    if any(w in q for w in ("create branch", "new branch", "make branch", "switch branch", "checkout ")):
        return "branch"
    if any(w in q for w in ("pull", "sync from remote", "update from remote")):
        return "pull"
    if any(w in q for w in ("push", "github", "upload to origin")):
        return "push"
    if any(w in q for w in ("commit",)):
        return "commit"
    if any(
        w in q
        for w in (
            "status",
            "log",
            "diff",
            "remote",
            "what branch",
            "repo status",
            "git status",
            "git log",
            "git diff",
            "git branch",
            "git remote",
            "branches",
        )
    ):
        return "readonly"
    return "unknown"


def classify_git_query(query: str) -> GitKind:
    """Try Groq JSON classify; fall back to rules."""
    rules = classify_git_query_rules(query)
    try:
        from core.groq_client import groq_client

        if not getattr(groq_client, "available", False):
            return rules
        prompt = (
            "Classify this git-related user request into ONE label:\n"
            "readonly, push, commit, pull, branch, merge, stash, clone, coach, unknown\n"
            "Return ONLY the label.\n\n"
            f"User: {query}"
        )
        text = (groq_client.ask(prompt) or "").strip().lower()
        for label in (
            "readonly",
            "push",
            "commit",
            "pull",
            "branch",
            "merge",
            "stash",
            "clone",
            "coach",
            "unknown",
        ):
            if label in text.split():
                return label  # type: ignore
            if text == label:
                return label  # type: ignore
    except Exception:
        pass
    return rules


def is_mutating(kind: GitKind) -> bool:
    return kind in ("push", "commit", "pull", "branch", "merge", "stash", "clone")
