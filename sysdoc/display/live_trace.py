"""Live trace of graph execution -- the "watch the agents work" experience.

Node-level narration (which fix is being tried, pass/fail, cycle
transitions) lives directly inside each node -- see the log_step/log_ok/
log_warn/log_err calls added to plan_executor.py, verifier_node.py, and
supervisor.py. Those need no help from here; they print as a normal side
effect of the node running.

What CAN'T be reported that way is the LLM's actual reasoning text as
it's generated token by token -- that only exists inside create_agent's
internal execution, observable only via the graph's own message
streaming. This module's only job is surfacing that.

stream_graph_with_trace() is a drop-in replacement for:
    graph.stream(inputs, config, stream_mode="updates")
It yields the exact same shape (bare {node_name: update} dicts), so any
existing __interrupt__-handling loop keeps working completely unchanged.
The only difference is it also prints live reasoning tokens as a side
effect while it runs.
"""
from __future__ import annotations

import sys
from typing import Iterator

from display.animations import _ANSI_COLORS, _ANSI_RESET, BlinkingCursor

_REASONING_COLOR = "cyan"


def stream_graph_with_trace(graph, inputs_or_command, config) -> Iterator[dict]:
    ansi = _ANSI_COLORS.get(_REASONING_COLOR, "")
    streaming_node: str | None = None
    cursor: BlinkingCursor | None = None
    cursor_active = False

    for mode, chunk in graph.stream(inputs_or_command, config, stream_mode=["updates", "messages"]):
        if mode == "messages":
            msg_chunk, metadata = chunk
            content = getattr(msg_chunk, "content", "")
            if not content or not isinstance(content, str):
                continue  # skip tool-call-only chunks and non-text content

            node = metadata.get("langgraph_node")
            if node != streaming_node:
                if streaming_node is not None:
                    sys.stdout.write("\n")
                sys.stdout.write(f"  [{node}] ")
                sys.stdout.flush()
                streaming_node = node
                cursor = BlinkingCursor(color=_REASONING_COLOR)
                cursor.start()
                cursor_active = True

            if cursor_active and cursor is not None:
                cursor.stop()
                cursor_active = False

            for char in content:
                sys.stdout.write(f"{ansi}{char}{_ANSI_RESET}")
                sys.stdout.flush()

        else:  # mode == "updates"
            if streaming_node is not None:
                sys.stdout.write("\n")
                sys.stdout.flush()
                streaming_node = None
                cursor = None
            yield chunk
