# RAG tools
"""Read-only tools for the FILE_RAG Planner / Reasoner.

These tools never mutate the filesystem. They only:
  - locate files/folders (via file_finder)
  - estimate indexing scope
  - load & preview content
  - retrieve chunks from the session index
  - list project structure for architecture questions

Mutation (indexing) is done by the ingester node, not via tool calls.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool


def make_rag_tools(thread_id: str = "default") -> list:
    """Build the tool list for a single RAG graph run.

    *thread_id* scopes the in-memory FAISS index so concurrent sessions
    do not collide.
    """

    @tool
    def search_local_files(query: str, match_mode: str = "any_token") -> List[Dict[str, Any]]:
        """Search the local machine for files or folders matching *query*.

        Returns a list of hits with keys: name, path, type (file|folder), size.
        Use this first to resolve a human name like "Code99" or "thesis report"
        into concrete paths before loading content.
        """
        from modules.file_finder import search_system

        mode = match_mode if match_mode in ("strict", "any_token", "fuzzy") else "any_token"
        results = search_system(query, match_mode=mode)
        # Normalise shape for the LLM
        out: List[Dict[str, Any]] = []
        for r in (results or [])[:15]:
            out.append({
                "name": r.get("name") or Path(r.get("path", "")).name,
                "path": r.get("path") or r.get("full_path") or "",
                "type": r.get("type") or ("folder" if r.get("is_dir") else "file"),
                "size": r.get("size") or r.get("size_str") or "",
            })
        return out

    @tool
    def estimate_index_scope(path: str, max_files: int = 80) -> Dict[str, Any]:
        """Estimate how many files / how much data would be indexed under *path*.

        Call this before proposing a full folder analysis so the permission
        gate can show the user a realistic size. Returns files, mb, sample paths.
        """
        from agents.rag.loaders import estimate_scope

        return estimate_scope(path, max_files=max_files)

    @tool
    def list_project_tree(path: str, max_depth: int = 3, max_entries: int = 80) -> str:
        """Return a compact directory tree for a project folder.

        Useful for architecture / structure questions. Skips node_modules,
        .git, __pycache__, venv, dist, build, etc.
        """
        from agents.rag.loaders import _SKIP_DIR_NAMES

        root = Path(path)
        if not root.is_dir():
            return f"Not a directory: {path}"

        lines: List[str] = [str(root)]
        count = 0

        def _walk(current: Path, prefix: str, depth: int) -> None:
            nonlocal count
            if depth > max_depth or count >= max_entries:
                return
            try:
                entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except Exception:
                return
            # prune
            entries = [
                e for e in entries
                if e.name not in _SKIP_DIR_NAMES and not e.name.startswith(".")
            ]
            for i, entry in enumerate(entries):
                if count >= max_entries:
                    lines.append(prefix + "…")
                    return
                connector = "└── " if i == len(entries) - 1 else "├── "
                lines.append(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))
                count += 1
                if entry.is_dir():
                    extension = "    " if i == len(entries) - 1 else "│   "
                    _walk(entry, prefix + extension, depth + 1)

        _walk(root, "", 1)
        return "\n".join(lines)

    @tool
    def preview_file(path: str, max_chars: int = 3000) -> str:
        """Load a single file and return a short text preview (not full index).

        Supports text, code, PDF, and DOCX. Use for quick checks before
        deciding to index a whole folder. Returns plain text or an error string.
        """
        from agents.rag.loaders import load_single

        docs = load_single(path)
        if not docs:
            return f"Could not load or extract text from: {path}"
        text = "\n\n".join(d.page_content for d in docs)
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n[... truncated — showing first {max_chars} chars]"
        return text

    @tool
    def retrieve_chunks(query: str, k: int = 8) -> List[Dict[str, Any]]:
        """Semantic search over the *already indexed* session documents.

        Only works after the ingester node has built an index for this thread.
        Returns top-*k* chunks with source path, optional page, and snippet.
        """
        from agents.rag.indexer import retrieve

        hits = retrieve(query, thread_id=thread_id, k=k)
        out: List[Dict[str, Any]] = []
        for item in hits:
            if isinstance(item, tuple) and len(item) == 2:
                h, score = item
            else:
                h, score = item, 1.0
            meta = getattr(h, "metadata", None) or {}
            out.append({
                "source": meta.get("source", "?"),
                "page": meta.get("page"),
                "chunk_id": meta.get("chunk_id"),
                "file_type": meta.get("file_type"),
                "score": float(score),
                "snippet": (getattr(h, "page_content", None) or "")[:500],
            })
        return out

    @tool
    def get_indexed_stats() -> Dict[str, Any]:
        """Return whether an index exists for this session and basic stats."""
        from agents.rag import indexer as idx_mod

        vs = idx_mod._INDEX_CACHE.get(thread_id)
        if vs is None:
            return {"indexed": False, "thread_id": thread_id, "vectors": 0}
        try:
            n = vs.index.ntotal  # FAISS
        except Exception:
            n = -1
        return {"indexed": True, "thread_id": thread_id, "vectors": n}

    return [
        search_local_files,
        estimate_index_scope,
        list_project_tree,
        preview_file,
        retrieve_chunks,
        get_indexed_stats,
    ]