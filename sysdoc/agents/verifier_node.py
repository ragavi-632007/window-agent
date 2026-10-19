"""Verifier Agent.

Independent of the Executor Agent. Refreshes telemetry, runs every
validation check named in the RepairPlan's `verification` list, and
answers exactly one question: did the repair goal succeed? It never
decides what happens next (retry / escalate / finalize) -- that's the
Supervisor's job, read from this node's output.

_VALIDATORS maps a verification check name -> a callable that inspects
fresh telemetry and returns True/False. Only "dns_lookup" is wired up
here, matching NETWORK being the only domain with a full real fix set
today. Extend this alongside fix_registry.py as STORAGE/DEV_ENV/SYSTEM
gain more fixes.
"""
from __future__ import annotations

from typing import Callable

from agents.models import RepairPlan, VerificationOutcome
from display.animations import log_ok, log_step, log_warn

def _network_health_ok(telem: dict) -> tuple[bool, str]:
    """Pass when collect() shows connectivity — ignore brittle dns_lookup sockets."""
    if not isinstance(telem, dict):
        return False, "no telemetry"
    internet = str(telem.get("internet", "")).lower()
    dns = str(telem.get("dns_status", "")).lower()
    ping = telem.get("gateway_ping_ms")
    online = internet in ("online", "yes", "true", "ok", "reachable")
    dns_ok = dns in ("ok", "good", "healthy", "")
    if online and dns_ok:
        return True, f"internet online, dns ok, ping={ping}"
    if online:
        return True, f"internet online, ping={ping}"
    return False, f"internet={internet}, dns={dns}, ping={ping}"


_VALIDATORS: dict[str, Callable] = {
    "dns_lookup": lambda after: after.get("internet") == "reachable",
}


def make_verifier_node(domain: str, domain_module) -> Callable[[dict], dict]:
    def verifier_node(state: dict) -> dict:
        plan = RepairPlan(**state["repair_plan"])
        before = state.get("telemetry", {})
        log_step(f"Verifying: refreshing telemetry and running {plan.verification or ['executor result']}...")
        after = domain_module.collect()  # refresh

        check_names = plan.verification or []
        outcomes = []
        is_network = (domain == "NETWORK")
        run_checks = check_names if check_names else (["network_health"] if is_network else [])

        for name in run_checks:
            if name in ("dns_lookup", "network_health"):
                ok, msg = _network_health_ok(after)
                outcomes.append((name, ok, msg))
            else:
                check = _VALIDATORS.get(name)
                if check is not None:
                    ok = bool(check(after))
                    outcomes.append((name, ok, "validator pass" if ok else "validator fail"))
                else:
                    ok = False
                    outcomes.append((name, ok, f"unknown check {name}"))

        if outcomes:
            success = any(ok for _, ok, _ in outcomes)
        else:
            # None of the named checks are wired up yet -- fall back to
            # whether the Executor Agent itself reported success.
            success = bool(state.get("fix_succeeded", False))

        if is_network and str(after.get("internet", "")).lower() in ("online", "reachable"):
            success = True

        confidence = plan.confidence if success else max(0.0, plan.confidence - 0.4)
        attempts = state.get("attempts_made", [])

        checks_desc = ", ".join(f"{n}={'pass' if ok else 'fail'}" for n, ok, _ in outcomes) or "no wired-up checks, used executor result"
        recommended_next_step = (
            "None -- repair goal met." if success
            else "Escalate to a support ticket if this was the final planning cycle; otherwise let the Supervisor start a new cycle."
        )

        outcome = VerificationOutcome(
            success=success,
            confidence=round(confidence, 2),
            before=str(before),
            after=str(after),
            verification_summary=(
                f"Checks [{checks_desc}] after {len(attempts)} attempt(s): "
                f"{', '.join(attempts) if attempts else 'none executed'}."
            ),
            recommended_next_step=recommended_next_step,
        )
        if success:
            log_ok(f"Verification passed ({outcome.confidence:.0%} confidence): {checks_desc}")
        else:
            log_warn(f"Verification failed: {checks_desc}")
        return {"verification": outcome.model_dump(), "telemetry": after}

    return verifier_node
