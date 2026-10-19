"""Permission Gate — always a LangGraph interrupt.

Two display modes:
    "standard"   — single y/n prompt showing goal + strategy + risk level.
                   Used by INSTALL and UPDATE.
    "high_risk"  — per-package preview requiring explicit y/n for each item.
                   Used by UNINSTALL.  Only approved packages proceed.

The node itself does no console work — it simply pauses the graph via
langgraph.types.interrupt() and hands a payload out to main.py's resume loop.
main.py calls the appropriate display helper, collects input, and resumes
the graph with Command(resume=<choice>).

For high-risk mode, the resume value is a dict keyed by package ID mapping to
"y" or "n".  For standard mode it is a single letter: "y", "n", or "t".
"""
from __future__ import annotations

from typing import Callable, Literal

from langgraph.types import interrupt


# ── Standard gate (INSTALL, UPDATE) ──────────────────────────────────────

def action_permission_gate_node(state: dict) -> dict:
    """Standard single-prompt permission gate.

    Interrupts with:
        {
            "domain":      str,
            "action_plan": dict,      # ActionPlan.model_dump()
            "gate_mode":   "standard",
        }

    Resume with a single letter: "y" | "n" | "t" (ticket).
    """
    choice = interrupt(
        {
            "domain":      state.get("domain", ""),
            "action_plan": state.get("action_plan"),
            "gate_mode":   "standard",
        }
    )
    return {"gate_choice": choice, "gate_approved": choice == "y"}


# ── High-risk gate (UNINSTALL) ────────────────────────────────────────────

def make_high_risk_gate_node() -> Callable[[dict], dict]:
    """Per-package confirmation gate for high-risk operations like UNINSTALL.

    Interrupts with:
        {
            "domain":      str,
            "action_plan": dict,
            "gate_mode":   "high_risk",
            "packages":    list[dict],   # UninstallTarget dicts
        }

    Resume with a dict mapping package ID -> "y" | "n":
        {"Discord.Discord": "y", "Spotify.Spotify": "n", ...}

    The resolve node below filters action_plan["packages"] to only those
    approved, so the Executor never sees rejected packages.
    """

    def high_risk_gate_node(state: dict) -> dict:
        plan = state.get("action_plan") or {}
        packages = plan.get("packages", [])
        choices: dict = interrupt(
            {
                "domain":      state.get("domain", ""),
                "action_plan": plan,
                "gate_mode":   "high_risk",
                "packages":    packages,
            }
        )
        # choices is {pkg_id: "y"|"n"}
        # If user said "n" to all, gate_approved = False.
        any_approved = any(v == "y" for v in choices.values())
        return {
            "gate_choice":       "y" if any_approved else "n",
            "gate_approved":     any_approved,
            "_gate_pkg_choices": choices,    # consumed by resolve node
        }

    return high_risk_gate_node


# ── Resolve gate choice ───────────────────────────────────────────────────

def make_resolve_gate_choice_node(
    permission_display: Literal["standard", "high_risk"],
) -> Callable[[dict], dict]:
    """Translate the raw gate output into approved packages / fix id.

    For standard mode: sets gate_approved based on the letter choice.
    For high_risk mode: filters action_plan["packages"] to only those
    where the user said "y", and writes approved_packages to state.
    """

    def resolve_gate_choice_node(state: dict) -> dict:
        choice = state.get("gate_choice", "n")

        if permission_display == "standard":
            if choice == "y":
                return {"gate_approved": True}
            # "n" or "t" — caller checks gate_approved to route
            return {"gate_approved": False}

        # high_risk: filter packages
        pkg_choices: dict = state.get("_gate_pkg_choices") or {}
        plan = state.get("action_plan") or {}

        if hasattr(plan, "packages"):
            all_packages = plan.packages
        elif isinstance(plan, dict):
            all_packages = plan.get("packages", [])
        else:
            all_packages = []

        approved = [
            p for p in all_packages
            if (pkg_choices.get(p.get("id", ""), "n") == "y" if isinstance(p, dict) else pkg_choices.get(getattr(p, "id", ""), "n") == "y")
        ]
        # Patch action_plan with only approved packages so Executor sees the
        # trimmed list without needing to re-read _gate_pkg_choices.
        if hasattr(plan, "model_copy"):
            patched_plan = plan.model_copy(update={"packages": approved})
        elif isinstance(plan, dict):
            patched_plan = {**plan, "packages": approved}
        else:
            patched_plan = plan
            
        any_approved = bool(approved)

        return {
            "gate_approved":    any_approved,
            "action_plan":      patched_plan,
            "approved_packages": approved,
        }

    return resolve_gate_choice_node
