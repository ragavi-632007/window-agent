"""NETWORK autonomous domain graph — thin wrapper over build_domain_subgraph."""
from __future__ import annotations

from typing import Any

from agents.graph import build_domain_subgraph
from agents.supervisor import DEFAULT_MAX_PLANNING_CYCLES


# Strategy ladder (planner should escalate in this order on retry)
NETWORK_STRATEGY_CHAIN = [
    "flush_dns",
    "set_public_dns",
    "renew_ip",
    "reset_adapter",
    "tcp_reset",
    "winsock_reset",
]


def build_network_subgraph(
    network_module,
    read_tools: list,
    llm: Any,
    core_executor,
    checkpoint_db_path: str = "sysdoc/memory/fixbot_state.db",
    max_planning_cycles: int = DEFAULT_MAX_PLANNING_CYCLES,
):
    """Compile NETWORK LangGraph: collect → plan → gate → execute → verify → retry."""
    return build_domain_subgraph(
        domain="NETWORK",
        domain_module=network_module,
        read_tools=read_tools,
        llm=llm,
        core_executor=core_executor,
        checkpoint_db_path=checkpoint_db_path,
        max_planning_cycles=max_planning_cycles,
    )
