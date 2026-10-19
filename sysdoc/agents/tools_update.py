"""Read-only LangChain tools for the UPDATE Planner agent.

The Planner uses these to inspect available updates and search for packages
by name, so it can produce an UpdatePlan with the correct package IDs.
These tools never modify the system — all write operations are in
update_executor.py.
"""
from __future__ import annotations

from langchain_core.tools import tool


def make_update_tools(updater) -> list:
    @tool
    def scan_all_updates() -> list:
        """Scan winget, pip, and npm for all available package updates.
        Returns a list of dicts with keys: name, id, from, to, source, manager."""
        return updater.scan_all()

    @tool
    def scan_winget_updates() -> list:
        """Scan only winget for available updates."""
        return updater.scan_winget()

    @tool
    def scan_pip_updates() -> list:
        """Scan only pip for outdated Python packages."""
        return updater.scan_pip()

    @tool
    def search_package(query: str) -> list:
        """Search winget for packages matching a name query (fuzzy match).
        Use this when the user asks to update a specific app by name —
        resolve the human name to the canonical winget package ID.
        Returns list of dicts with keys: name, id, version, source."""
        return updater.search_package(query)

    @tool
    def get_package_info(package_id: str) -> dict:
        """Get current installed version info for a specific package by its
        winget ID (e.g. 'Microsoft.Edge'). Useful to confirm what's installed
        before planning an update."""
        from sysdoc.modules.updater import UpdateScanner
        ok, out = UpdateScanner._run_cmd(
            ["winget", "list", "--id", package_id, "--accept-source-agreements"]
        )
        return {"id": package_id, "found": ok, "output": out}

    return [scan_all_updates, scan_winget_updates, scan_pip_updates,
            search_package, get_package_info]
