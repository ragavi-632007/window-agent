"""RAG chunking — no eager sentence_transformers import (Windows hang fix)."""
from __future__ import annotations

from typing import List

from langchain_core.documents import Document

_CODE_SEPARATORS = ["\nclass ", "\ndef ", "\nfunction ", "\n\n", "\n", " ", ""]
_PROSE_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def _hard_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    step = max(chunk_size - chunk_overlap, 1)
    return [text[i : i + chunk_size] for i in range(0, len(text), step) if text[i : i + chunk_size]]


def _simple_split(text: str, chunk_size: int, chunk_overlap: int, separators: list[str]) -> list[str]:
    """Minimal recursive splitter — no external ST/sklearn import."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    sep = separators[0] if separators else ""
    rest = separators[1:] if separators else []

    if sep == "":
        return _hard_chunks(text, chunk_size, chunk_overlap)

    parts = text.split(sep)
    chunks: list[str] = []
    buf = ""

    for i, part in enumerate(parts):
        candidate = part if i == 0 else (buf + sep + part if buf else part)
        if i == 0:
            buf = part
            continue
        if len(buf) + len(sep) + len(part) <= chunk_size:
            buf = buf + sep + part
        else:
            if buf:
                if len(buf) > chunk_size and rest:
                    chunks.extend(_simple_split(buf, chunk_size, chunk_overlap, rest))
                elif len(buf) > chunk_size:
                    chunks.extend(_hard_chunks(buf, chunk_size, chunk_overlap))
                else:
                    chunks.append(buf)
            buf = part

    if buf:
        if len(buf) > chunk_size and rest:
            chunks.extend(_simple_split(buf, chunk_size, chunk_overlap, rest))
        elif len(buf) > chunk_size:
            chunks.extend(_hard_chunks(buf, chunk_size, chunk_overlap))
        else:
            chunks.append(buf)

    return chunks


def _get_lc_splitter(is_code: bool, chunk_size: int, chunk_overlap: int):
    """Import only the character submodule — never package __init__ (ST)."""
    seps = _CODE_SEPARATORS if is_code else _PROSE_SEPARATORS
    try:
        from langchain_text_splitters.character import RecursiveCharacterTextSplitter

        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=seps,
        )
    except Exception:
        return None


def split_documents(
    docs: List[Document],
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> List[Document]:
    if not docs:
        return []

    out: List[Document] = []
    for doc in docs:
        ftype = (doc.metadata or {}).get("file_type", "")
        is_code = ftype in {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
            ".c", ".cpp", ".cs", ".html", ".css",
        }

        splitter = _get_lc_splitter(is_code, chunk_size, chunk_overlap)
        if splitter is not None:
            pieces = splitter.split_documents([doc])
            for i, piece in enumerate(pieces):
                meta = dict(piece.metadata or {})
                meta["chunk_index"] = i
                meta["chunk_id"] = f"{meta.get('source', 'unknown')}::{i}"
                piece.metadata = meta
                out.append(piece)
        else:
            seps = _CODE_SEPARATORS if is_code else _PROSE_SEPARATORS
            parts = _simple_split(doc.page_content or "", chunk_size, chunk_overlap, seps)
            for i, part in enumerate(parts):
                meta = dict(doc.metadata or {})
                meta["chunk_index"] = i
                meta["chunk_id"] = f"{meta.get('source', 'unknown')}::{i}"
                out.append(Document(page_content=part, metadata=meta))
    return out