"""Planner Agent.

Owns diagnosis only:
  - inspect telemetry with read-only tools
  - determine root_cause
  - produce exactly ONE RepairPlan, with fallbacks ranked

Planner Agent must NEVER execute fixes and NEVER retry or re-plan itself --
if the Supervisor decides a new planning cycle is needed after a whole
plan is exhausted, this same node runs again, but that's the Supervisor's
call (via supervisor.py's start_new_cycle_node), not something the
Planner initiates on its own.

Uses langchain.agents.create_agent (requires the `langchain` package,
verified against a real install -- see IMPLEMENTATION_PLAN.md). The older
langgraph.prebuilt.create_react_agent still works identically for this
use case (same response_format kwarg, same structured_response output
key) but is deprecated as of langgraph>=1.x in favor of this one.
"""
from __future__ import annotations

from typing import Callable

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from agents.fix_registry import known_fix_ids
from agents.models import FixCandidate, RepairPlan
from display.animations import log_ok, log_step

PLANNER_SYSTEM_PROMPT = """You are the {domain} diagnostic planner for Fixbot.

You have read-only tools to inspect current system telemetry. Use them as
needed to understand the problem, determine the root_cause, then produce
exactly ONE RepairPlan: a primary_fix and a ranked list of fallbacks to
try if the primary one doesn't resolve things. Assign each fix a risk
level (low/medium/high) honestly.

Known fix_ids for this domain: {known_fixes}. Only use fix_ids from this
list for primary_fix.id and fallbacks[].id -- do not invent new ones.

List one or more verification check names in `verification` that would
confirm the repair goal was actually met (e.g. 'dns_lookup').

Do not execute anything yourself. Do not ask the user questions -- make
your best judgment from the telemetry and report your confidence
honestly. If a system message tells you a previous planning cycle
already failed, take that into account -- diagnose the root cause
differently rather than repeating the same plan."""


def make_planner_node(domain: str, read_tools: list, llm) -> Callable[[dict], dict]:
    valid_ids = known_fix_ids(domain)

    sys_prompt = PLANNER_SYSTEM_PROMPT.format(domain=domain, known_fixes=sorted(valid_ids))
    if domain == "NETWORK":
        sys_prompt += (
            "\n\nNETWORK fix escalation order (use next on retry):\n"
            "1 flush_dns\n"
            "2 set_public_dns\n"
            "3 renew_ip\n"
            "4 reset_adapter\n"
            "5 tcp_reset\n"
            "6 winsock_reset (last resort; may need reboot)\n\n"
            "Always call get_network_status first.\n"
            "Use get_active_interface before recommending adapter resets.\n"
            "After a fix, verification should show improved ping/dns/internet."
        )

    if llm is not None:
        agent = create_agent(
            model=llm,
            tools=read_tools,
            response_format=RepairPlan,
            system_prompt=sys_prompt,
        )
    else:
        agent = None

    def _offline_network_plan(state: dict) -> dict:
        from agents.models import FixCandidate, RepairPlan
        from agents.fix_registry import known_fix_ids
        from display.animations import agent_log_step, agent_log_ok, agent_log_warn

        telem = state.get("telemetry") or {}
        cycle = int(state.get("planning_cycle") or 1)

        try:
            valid = known_fix_ids("NETWORK")
        except Exception:
            valid = set()
        if not valid:
            valid = {
                "flush_dns", "set_public_dns", "renew_ip",
                "reset_adapter", "tcp_reset", "winsock_reset",
            }

        ladder = [
            x for x in (
                "flush_dns",
                "set_public_dns",
                "renew_ip",
                "reset_adapter",
                "tcp_reset",
                "winsock_reset",
            )
            if x in valid
        ] or list(valid)

        # Already-tried fix ids
        tried = set()
        for hist in state.get("cycle_history") or []:
            if not isinstance(hist, dict):
                continue
            rp = hist.get("repair_plan") or {}
            if isinstance(rp, dict):
                pf = rp.get("primary_fix") or {}
                if isinstance(pf, dict) and pf.get("id"):
                    tried.add(pf["id"])
                elif rp.get("id"):
                    tried.add(rp["id"])
            pf2 = hist.get("primary_fix")
            if isinstance(pf2, dict) and pf2.get("id"):
                tried.add(pf2["id"])
            elif isinstance(pf2, str):
                tried.add(pf2)

        prev = state.get("repair_plan") or {}
        if isinstance(prev, dict):
            pf = prev.get("primary_fix") or {}
            if isinstance(pf, dict) and pf.get("id"):
                tried.add(pf["id"])

        for a in state.get("attempts_made") or []:
            if isinstance(a, str) and a:
                tried.add(a.split(":")[0] if ":" in a else a)

        pick = None
        for fid in ladder:
            if fid not in tried:
                pick = fid
                break
        if not pick:
            pick = ladder[min(max(cycle - 1, 0), len(ladder) - 1)]

        internet = str(telem.get("internet") or "").lower()
        dns = str(telem.get("dns_status") or "").lower()
        try:
            loss = float(telem.get("packet_loss_pct") or 0)
        except Exception:
            loss = 0.0

        agent_log_warn("NETWORK Planner  using offline rules (no Gemini wait)")
        agent_log_step(
            f"Selected fix: {pick} (cycle {cycle}, tried={sorted(tried) or 'none'})"
        )

        plan = RepairPlan(
            goal="Improve Wi-Fi / network performance",
            root_cause=(
                f"internet={internet}, dns={dns}, loss={loss}%, "
                f"ping={telem.get('gateway_ping_ms')}, ssid={telem.get('wifi_ssid')}"
            ),
            confidence=0.75,
            primary_fix=FixCandidate(id=pick, risk="low"),
            fallbacks=[
                FixCandidate(id=x, risk="low")
                for x in ladder
                if x != pick
            ][:3],
            verification=["network_health"],
            reasoning=(
                f"Offline rules chose {pick} on cycle {cycle}. "
                f"Already tried: {sorted(tried) or 'none'}."
            ),
            max_attempts=3,
            planning_cycle=cycle,
        )
        pdata = plan.model_dump()
        agent_log_ok(f"🧠 Planner  NETWORK offline plan — {pick}")
        return {
            "messages": state.get("messages") or [],
            "repair_plan": pdata,
            "action_plan": {**pdata, "domain": "NETWORK"},
            "attempts_made": list(state.get("attempts_made") or []) + [pick],
        }

    def planner_node(state: dict) -> dict:
        from display.animations import agent_log_step, agent_log_warn, agent_log_ok

        if domain == "NETWORK":
            return _offline_network_plan(state)

        agent_log_step(f"{domain} Planner analyzing telemetry...")

        import concurrent.futures
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(lambda: agent.invoke({"messages": state["messages"]}))
            result = fut.result(timeout=20)

            plan = result.get("structured_response") if isinstance(result, dict) else None
            if plan is None:
                raise RuntimeError("Planner returned no structured_response")

            # Normalize possible None fields from Gemini function_call-only replies
            if getattr(plan, "goal", None) is None:
                plan.goal = f"Stabilize {domain}"
            if getattr(plan, "root_cause", None) is None:
                plan.root_cause = "Telemetry analysis incomplete"
            if getattr(plan, "reasoning", None) is None:
                plan.reasoning = "Model returned empty text; using telemetry defaults."
            if getattr(plan, "fallbacks", None) is None:
                plan.fallbacks = []

            # Any string field the code later .lower()'s — guard here
            for attr in ("goal", "root_cause", "reasoning"):
                val = getattr(plan, attr, None)
                if val is not None and not isinstance(val, str):
                    setattr(plan, attr, str(val))

            # Defensive validation: drop any fix_id the LLM hallucinated that
            # isn't actually registered for this domain.
            plan.fallbacks = [f for f in plan.fallbacks if f.id in valid_ids]
            if plan.primary_fix.id not in valid_ids:
                if plan.fallbacks:
                    plan.primary_fix, plan.fallbacks = plan.fallbacks[0], plan.fallbacks[1:]
                elif valid_ids:
                    # Last resort: nothing the model proposed is valid. Fall
                    # back to *some* known fix rather than crash the Executor
                    # Agent, but this should be rare enough to be worth logging.
                    plan.primary_fix = FixCandidate(id=sorted(valid_ids)[0], risk="low")
                    plan.reasoning += " [fallback: planner proposed an unknown fix_id]"

            plan.planning_cycle = state.get("planning_cycle", 1)
            agent_log_ok(f"Repair plan ready — primary fix: {plan.primary_fix.id} (confidence {plan.confidence:.0%})")

            # Stored as a plain dict, not the Pydantic object -- the
            # checkpointer's msgpack serializer doesn't have RepairPlan
            # registered and warns it'll be a hard error in a future
            # langgraph version. Every consuming node reconstructs
            # RepairPlan(**state["repair_plan"]) where it wants attribute access.
            return {"messages": result["messages"], "repair_plan": plan.model_dump()}
        except Exception as exc:
            agent_log_warn(f"Planner failed ({exc})")
            if domain == "NETWORK":
                return _offline_network_plan(state)
            raise
        finally:
            # critical: don't join stuck Gemini HTTP thread
            pool.shutdown(wait=False, cancel_futures=True)

    return planner_node
