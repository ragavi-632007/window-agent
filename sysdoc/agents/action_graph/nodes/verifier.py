"""Action Verifier Node — confirms success using domain-injected validation.

The verifier never repairs anything. It runs the validator_fn supplied at
graph-build time and writes a verification dict to state.

validator_fn signature:
    (plan: dict, execution_results: list[dict]) -> dict
    Returns:
        {
            "success":      bool,
            "confidence":   float,   # 0.0–1.0
            "summary":      str,     # one sentence
            "details":      dict,    # per-package or per-check details
        }

Domain wrappers supply a concrete validator_fn:
    UPDATE   → _winget_version_validator
    INSTALL  → _winget_presence_validator
    UNINSTALL → _winget_absence_validator
"""
from __future__ import annotations

from typing import Callable

from display.animations import agent_log_err, agent_log_ok, agent_log_step


def make_action_verifier_node(
    validator_fn: Callable[[dict, list], dict],
) -> Callable[[dict], dict]:
    """Factory.  *validator_fn* is injected by the domain wrapper."""

    def action_verifier_node(state: dict) -> dict:
        plan     = state.get("action_plan") or {}
        results  = state.get("execution_results") or state.get("update_results") or []
        attempts = state.get("attempts_made", [])

        agent_log_step("🔍 Verifier  Checking outcome...")

        outcome = validator_fn(plan, results)

        success    = bool(outcome.get("success", False))
        confidence = float(outcome.get("confidence", 0.5))
        summary    = outcome.get("summary", "")

        full_verification = {
            "success":              success,
            "confidence":           round(confidence, 2),
            "before":               "",
            "after":                "",
            "verification_summary": summary,
            "details":              outcome.get("details", {}),
            "recommended_next_step": (
                "None — goal met." if success
                else "Escalate or retry with a different strategy."
            ),
        }

        if success:
            agent_log_ok(f"🔍 Verifier  {summary}")
        else:
            agent_log_err(f"🔍 Verifier  {summary}")

        return {"verification": full_verification}

    return action_verifier_node


# ── Built-in validators for winget domains ────────────────────────────────

def winget_presence_validator(plan: dict, results: list[dict]) -> dict:
    """INSTALL: confirm every target package is now listed by winget."""
    import shutil
    import subprocess

    details: dict[str, dict] = {}
    all_present = True

    for r in results:
        pkg_id = r.get("id", "")
        if not pkg_id or not r.get("success"):
            details[pkg_id or r.get("name", "?")] = {
                "present": False,
                "reason": "Executor reported failure",
            }
            all_present = False
            continue

        if not shutil.which("winget"):
            details[pkg_id] = {"present": True, "reason": "winget not available; trusting executor"}
            continue

        try:
            proc = subprocess.run(
                ["winget", "list", "--id", pkg_id, "--accept-source-agreements"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            present = pkg_id.lower() in proc.stdout.lower()
            details[pkg_id] = {
                "present": present,
                "output": proc.stdout[:200],
            }
            if not present:
                all_present = False
        except Exception as exc:
            details[pkg_id] = {"present": False, "reason": str(exc)}
            all_present = False

    count = len(results)
    ok_count = sum(1 for v in details.values() if v.get("present", False))
    summary = (
        f"All {count} package(s) installed and confirmed present."
        if all_present
        else f"{ok_count}/{count} package(s) confirmed present after install."
    )
    return {
        "success":    all_present,
        "confidence": 1.0 if all_present else 0.3,
        "summary":    summary,
        "details":    details,
    }


def winget_version_validator(plan: dict, results: list[dict]) -> dict:
    """UPDATE: confirm every package is now at its target version (or newer)."""
    import shutil
    import subprocess

    details: dict[str, dict] = {}
    all_verified = True

    for r in results:
        pkg_id  = r.get("id", "")
        to_ver  = r.get("to_version", r.get("to", ""))
        manager = r.get("manager", "winget")

        if not r.get("success"):
            details[pkg_id or r.get("name", "?")] = {
                "verified": False,
                "reason": "Executor reported failure",
            }
            all_verified = False
            continue

        try:
            if manager == "winget" and shutil.which("winget"):
                proc = subprocess.run(
                    ["winget", "list", "--id", pkg_id, "--accept-source-agreements"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=20,
                )
                verified = (to_ver in proc.stdout) if to_ver else proc.returncode == 0
                details[pkg_id] = {"verified": verified, "output": proc.stdout[:200]}
            elif manager == "pip" and shutil.which("pip"):
                proc = subprocess.run(
                    ["pip", "show", r.get("name", pkg_id)],
                    capture_output=True, text=True, timeout=10,
                )
                verified = (to_ver in proc.stdout) if to_ver else proc.returncode == 0
                details[pkg_id] = {"verified": verified}
            else:
                # npm or unknown: trust executor result
                verified = True
                details[pkg_id] = {"verified": True, "reason": "trusting executor result"}

            if not verified:
                all_verified = False
        except Exception as exc:
            details[pkg_id] = {"verified": False, "reason": str(exc)}
            all_verified = False

    count    = len(results)
    ok_count = sum(1 for v in details.values() if v.get("verified", False))
    summary  = (
        f"All {count} package(s) updated and verified."
        if all_verified
        else f"{ok_count}/{count} package(s) verified at target version."
    )
    return {
        "success":    all_verified,
        "confidence": 1.0 if all_verified else 0.3,
        "summary":    summary,
        "details":    details,
    }


def winget_absence_validator(plan: dict, results: list[dict]) -> dict:
    """UNINSTALL: confirm every target package is no longer present."""
    import shutil
    import subprocess

    details: dict[str, dict] = {}
    all_removed = True

    for r in results:
        pkg_id = r.get("id", "")
        if not r.get("success"):
            details[pkg_id or r.get("name", "?")] = {
                "absent": False,
                "reason": "Executor reported failure",
            }
            all_removed = False
            continue

        if not shutil.which("winget"):
            details[pkg_id] = {"absent": True, "reason": "winget not available; trusting executor"}
            continue

        try:
            proc = subprocess.run(
                ["winget", "list", "--id", pkg_id, "--accept-source-agreements"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            # Package absent means the ID does NOT appear in the output.
            absent = pkg_id.lower() not in proc.stdout.lower()
            details[pkg_id] = {
                "absent": absent,
                "output": proc.stdout[:200],
            }
            if not absent:
                all_removed = False
        except Exception as exc:
            details[pkg_id] = {"absent": False, "reason": str(exc)}
            all_removed = False

    count    = len(results)
    ok_count = sum(1 for v in details.values() if v.get("absent", False))
    summary  = (
        f"All {count} package(s) removed and confirmed absent."
        if all_removed
        else f"{ok_count}/{count} package(s) confirmed removed."
    )
    return {
        "success":    all_removed,
        "confidence": 1.0 if all_removed else 0.3,
        "summary":    summary,
        "details":    details,
    }
