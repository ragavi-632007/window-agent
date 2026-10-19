"""Permission gate as a LangGraph interrupt.

This node itself does no UI work -- it just pauses the graph and hands the
RepairPlan out. main.py's resume loop catches the interrupt, calls the
existing PermissionGate.ask_permission() (RepairPlan-aware, see
core/permission_gate.py), and resumes the graph with whatever letter the
human picked via Command(resume=<letter>).
"""
from __future__ import annotations

from langgraph.types import interrupt


def permission_gate_node(state: dict) -> dict:
    # repair_plan is already a plain dict in state (see planner.py) -- no
    # .model_dump() needed here.
    choice = interrupt(
        {
            "domain": state["domain"],
            "repair_plan": state["repair_plan"],
        }
    )
    # choice is one of: "y" (approve primary_fix), a domain-specific letter
    # like "x"/"p" for STORAGE overriding to a different known fix, "d"
    # (show details -- caller re-enters this node), "t" (ticket), "n" (skip)
    return {"gate_choice": choice}


def resolve_gate_choice(state: dict) -> dict:
    """Translate the raw letter into an approved_fix_id, or leave it unset
    for skip/ticket so the graph's conditional edge can route accordingly."""
    from agents.fix_registry import FIX_REGISTRY

    plan = state["repair_plan"]
    choice = state["gate_choice"]
    domain = state["domain"]

    if choice == "y":
        return {"approved_fix_id": plan["primary_fix"]["id"]}
    if choice in ("n", "t", "d"):
        return {"approved_fix_id": None}

    # Domain-specific override letters (e.g. STORAGE's "x"/"p") map to a
    # specific fix_id via the same registry the menu labels came from.
    override_map = {
        "x": "delete_duplicates",
        "p": "partition_wizard",
    }
    override = override_map.get(choice)
    if override and override in FIX_REGISTRY.get(domain, {}):
        return {"approved_fix_id": override}

    return {"approved_fix_id": None}
