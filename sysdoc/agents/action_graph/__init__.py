"""Action Graph package — lazy export (avoids circular imports)."""
from __future__ import annotations

__all__ = ["build_action_graph"]


def __getattr__(name: str):
    if name == "build_action_graph":
        from action_graph.builder import build_action_graph
        return build_action_graph
    raise AttributeError(name)
