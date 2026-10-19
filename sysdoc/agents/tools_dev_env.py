"""Read-only tools for the DEV_ENV Planner."""
from __future__ import annotations

from langchain_core.tools import tool


def make_dev_env_tools(dev_env_module) -> list:
    @tool
    def get_dev_env_status() -> dict:
        """Current dev environment telemetry: Python installs found on
        disk, active venv state, PATH entries, pip health. Call again
        mid-reasoning to refresh."""
        return dev_env_module.collect()

    return [get_dev_env_status]
