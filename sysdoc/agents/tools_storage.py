"""Read-only tools for the STORAGE Planner.

find_duplicate_files is the one tool that writes to graph state (via
Command) rather than just returning a value -- the full duplicate map is
too large to usefully repeat back through the LLM, and plan_executor.py
needs it later if "delete_duplicates" is the fix that gets approved.
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command


def make_storage_tools(storage_module) -> list:
    @tool
    def get_storage_status() -> dict:
        """Current storage telemetry: drive usage per volume, recycle bin
        size, largest files. Call again mid-reasoning to refresh."""
        return storage_module.collect()

    @tool
    def get_cache_sizes() -> dict:
        """Breakdown of cache size by browser (Chrome/Edge/Brave/Firefox)
        and by OS system cache."""
        return storage_module.get_cache_sizes()

    @tool
    def find_duplicate_files(
        scan_dirs: list[str],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Scan the given directories for duplicate files by MD5 hash.
        Stores the full duplicate map in graph state for later use --
        only propose 'delete_duplicates' as a fix (primary or fallback)
        after calling this and seeing that duplicates were actually found."""
        result = storage_module.find_duplicates(scan_dirs)
        total = sum(len(v) for v in result.values())
        return Command(
            update={
                "last_duplicate_scan": result,
                "messages": [
                    ToolMessage(
                        f"Found {total} duplicate files across {len(result)} groups.",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    return [get_storage_status, get_cache_sizes, find_duplicate_files]
