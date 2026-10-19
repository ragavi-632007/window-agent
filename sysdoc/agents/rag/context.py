"""Context assembly — AnythingLLM-style multi-source context for ChatGPT-like answers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def assemble_context(
    *,
    retrieved_chunks: List[Dict[str, Any]],
    attached_text: str = "",
    pinned_snippets: Optional[List[Dict[str, Any]]] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
    max_history_turns: int = 4,
    max_chars: int = 28000,
) -> str:
    """
    Build a single Context block for the reasoner.

    Order (highest priority first):
      1. Pinned / always-include snippets (e.g. README)
      2. Full attached document (small-file path)
      3. Retrieved chunks
      4. Recent chat turns about this workspace
    """
    parts: List[str] = []

    if pinned_snippets:
        pin_blocks = []
        for p in pinned_snippets:
            src = p.get("source", "pinned")
            body = (p.get("text") or "")[:4000]
            if body.strip():
                pin_blocks.append(f"[PINNED: {src}]\n{body}")
        if pin_blocks:
            parts.append("### Pinned materials\n\n" + "\n\n---\n\n".join(pin_blocks))

    if attached_text and attached_text.strip():
        parts.append("### Full document\n\n" + attached_text.strip()[:12000])

    if retrieved_chunks:
        chunk_blocks = []
        for c in retrieved_chunks:
            src = c.get("source", "?")
            page = c.get("page")
            label = f"{src}" + (f" p.{page}" if page else "")
            snippet = (c.get("text") or c.get("snippet") or "")[:2000]
            if snippet.strip():
                chunk_blocks.append(f"[{label}]\n{snippet}")
        if chunk_blocks:
            parts.append("### Retrieved excerpts\n\n" + "\n\n---\n\n".join(chunk_blocks))

    if chat_history:
        turns = chat_history[-max_history_turns * 2 :]
        hist_lines = []
        for t in turns:
            role = (t.get("role") or "user").upper()
            content = (t.get("content") or "").strip()
            if content:
                hist_lines.append(f"{role}: {content[:800]}")
        if hist_lines:
            parts.append("### Recent conversation\n\n" + "\n".join(hist_lines))

    if not parts:
        return ""

    assembled = "\n\n".join(parts)
    if len(assembled) > max_chars:
        assembled = assembled[:max_chars] + "\n\n[... context truncated for length ...]"
    return assembled


def pick_attach_vs_rag(doc_count: int, total_chars: int, threshold_chars: int = 40000) -> str:
    """Return 'attach' for small single docs, else 'rag'."""
    if doc_count <= 1 and total_chars <= threshold_chars:
        return "attach"
    return "rag"