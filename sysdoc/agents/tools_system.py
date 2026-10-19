"""Read-only tools for the SYSTEM Planner.

Note: targeted actions like kill_process(pid) are NOT included here even
though system_health.py has them -- with a deterministic RepairPlan
Executor, a fix_id has to be resolvable at plan time from fix_registry.py,
and "kill this specific PID I just saw in a tool result" only makes sense
as an in-the-moment agentic decision. If you want that capability back,
it belongs in a follow-up (e.g. letting the Planner emit a
target_pid/target_name alongside the plan), not in this refactor.
"""
from __future__ import annotations

from langchain_core.tools import tool


def make_system_tools(system_health_module) -> list:
    @tool
    def get_system_status() -> dict:
        """Current system telemetry: CPU/RAM/GPU usage, CPU temperature,
        power plan. Call again mid-reasoning to refresh."""
        return system_health_module.collect()

    @tool
    def list_processes(top: int = 10, filter_name: str | None = None) -> list:
        """List running processes by RAM usage, optionally filtered by
        name substring. Read-only -- does not terminate anything."""
        return system_health_module.list_processes(top=top, filter_name=filter_name)

    @tool
    def list_browser_tabs(filter_name: str | None = None) -> list:
        """List open browser tabs across Chrome/Edge/Brave via their
        DevTools debugging endpoints, optionally filtered by title/URL
        substring."""
        return system_health_module.list_browser_tabs(filter_name=filter_name)

    return [get_system_status, list_processes, list_browser_tabs]
