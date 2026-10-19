"""Error Analyzer — classify failures; default = recoverable force_install."""
from __future__ import annotations

import re
from typing import Callable, Optional

from display.animations import agent_log, agent_log_ok, agent_log_step, agent_log_warn

_PATTERN_RULES = [
    ("user_scope_admin", True, "uninstall_user_scope", [
        r"user scope cannot be uninstalled",
        r"when running with administrator privileges",
        r"installed for user scope",
    ]),
    ("hash_mismatch", True, "force_install", [
        r"hash", r"SHA256", r"checksum", r"does not match",
    ]),
    ("agreements", True, "accept_agreements", [
        r"agreements", r"license agreement", r"terms of service",
    ]),
    ("already_installed", True, "force_install", [
        r"already installed", r"No available upgrade",
    ]),
    ("not_found", True, "replan", [
        r"No package found", r"no packages? found", r"Unknown package",
    ]),
    ("network", True, "retry_same", [
        r"timed out", r"timeout", r"network", r"connection", r"SSL", r"proxy",
    ]),
    ("blocked_process", True, "force_install", [
        r"Access to the path", r"Access is denied", r"is the app still running",
        r"being used by another process", r"in use", r"denied",
    ]),
    ("installer_failed", True, "force_install", [
        r"Installation has failed", r"Installer failed", r"exit code: 1",
        r"FAILED", r"failed with exit",
    ]),
    ("source_error", True, "choco_install", [
        r"source", r"Failed when searching source",
    ]),
    ("disk_space", False, "escalate", [
        r"not enough space", r"disk full", r"insufficient disk",
    ]),
]


def _match(text: str):
    low = text.lower()
    for category, recoverable, recommended, patterns in _PATTERN_RULES:
        for pat in patterns:
            if re.search(pat, low, re.IGNORECASE):
                return category, recoverable, recommended, pat
    return None


def _summary(category: str, recommended: str) -> str:
    tips = {
        "user_scope_admin": (
            "Package is per-user but Fixbot is Admin. "
            "Retry uninstall in user scope (non-elevated winget)."
        ),
        "hash_mismatch": "Hash mismatch — retrying with force install.",
        "agreements": "Agreements blocked install — retrying with accept flags.",
        "already_installed": "Already present — force/repair install.",
        "not_found": "Package not found — will replan ID.",
        "network": "Network error — retrying same command.",
        "blocked_process": "Files locked (app running?) — kill app + force install.",
        "installer_failed": "Installer failed — trying force_install next.",
        "source_error": "Winget source issue — try Chocolatey.",
        "disk_space": "Disk full — cannot continue.",
    }
    return tips.get(category, f"Failure ({category}). Next: {recommended}.")


def make_error_analyzer_node(
    llm=None,
    domain_strategy_chain: Optional[list] = None,
) -> Callable[[dict], dict]:
    valid = set(domain_strategy_chain or [])

    def error_analyzer_node(state: dict) -> dict:
        verification = state.get("verification") or {}
        results = (
            state.get("execution_results")
            or state.get("action_results")
            or state.get("update_results")
            or []
        )

        if verification.get("success"):
            agent_log_ok("Error Analyzer  skipped — verification succeeded")
            return {
                "error_analysis": {
                    "category": "none",
                    "recoverable": False,
                    "recommended_strategy": "finalize",
                    "summary": "No error — action succeeded.",
                    "raw_signal": "",
                }
            }

        agent_log_step("Error Analyzer  classifying failure...")
        blobs = []
        for r in results:
            if r.get("success"):
                continue
            blobs.append(
                f"[{r.get('name')} / {r.get('strategy_used')}]\n"
                f"{r.get('stdout','')}\n{r.get('stderr','')}\n{r.get('output','')}"
            )
        combined = "\n".join(blobs) or str(
            verification.get("summary") or "unknown failure"
        )

        domain = (state.get("domain") or "").upper()
        chain = list(domain_strategy_chain or valid or [])

        matched = _match(combined)
        if matched:
            category, recoverable, recommended, signal = matched
            summary = _summary(category, recommended)
        else:
            if domain == "UNINSTALL":
                recommended = "force_uninstall" if "force_uninstall" in chain else "purge_uninstall"
                if "force_uninstall" not in chain and chain:
                    recommended = chain[-1] if chain else "purge_uninstall"
                summary = "Uninstall failed - trying stronger uninstall strategy."
            elif domain == "UPDATE":
                recommended = "force_upgrade" if "force_upgrade" in chain else "replan"
                summary = "Update failed - trying force upgrade."
            else:
                recommended = "force_install" if "force_install" in chain else "replan"
                summary = "Install failed - retrying with force_install."
            category, recoverable, signal = "unknown", True, "default"

        if valid and recommended not in valid and recommended not in (
            "retry_same", "replan", "escalate", "abort", "finalize",
        ):
            recommended = "force_install" if "force_install" in valid else "replan"

        agent_log("error", summary)
        agent_log_warn(
            f"Error Analyzer  → next: {recommended} (recoverable={recoverable})"
        )

        return {
            "error_analysis": {
                "category": category,
                "recoverable": recoverable,
                "recommended_strategy": recommended,
                "summary": summary,
                "raw_signal": signal,
                "output_excerpt": combined[:800],
            }
        }

    return error_analyzer_node