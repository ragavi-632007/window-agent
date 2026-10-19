"""Session-scoped vector index + score-aware retrieve.

Embedding priority:
  1. Hugging Face sentence-transformers (local, free, no API 404s)
  2. Gemini embeddings (if key + model available)
  3. Hash embedder (always works offline)

Env:
  FIXBOT_EMBED_BACKEND = auto | huggingface | gemini | hash
  FIXBOT_HF_EMBED_MODEL = sentence-transformers/all-MiniLM-L6-v2 (default)
"""
from __future__ import annotations

import hashlib
import os
from typing import List, Optional, Tuple

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

_INDEX_CACHE: dict = {}
_EMBEDDINGS_SINGLETON: Optional[Embeddings] = None
_EMBED_BACKEND_USED: str = "none"

_GEMINI_EMBED_MODELS = (
    "models/text-embedding-004",
    "text-embedding-004",
    "models/embedding-001",
    "embedding-001",
    "models/text-embedding-005",
    "text-embedding-005",
)

_DEFAULT_HF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class _HashEmbeddings(Embeddings):
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._vec(text)

    def _vec(self, text: str, dim: int = 128) -> List[float]:
        acc = [0.0] * dim
        tokens = (text or "").lower().split()
        seeds = [text or ""] + tokens[:64]
        for s in seeds:
            h = hashlib.sha256(s.encode("utf-8", errors="replace")).digest()
            for i in range(dim):
                acc[i] += h[i % len(h)] / 255.0
        norm = sum(x * x for x in acc) ** 0.5 or 1.0
        return [x / norm for x in acc]


def _try_hf_embeddings() -> Optional[Embeddings]:
    model_name = os.environ.get("FIXBOT_HF_EMBED_MODEL", _DEFAULT_HF_MODEL)
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        emb = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        emb.embed_query("ping")
        return emb
    except Exception:
        pass
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        emb = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        emb.embed_query("ping")
        return emb
    except Exception:
        return None


def _try_gemini_embeddings() -> Optional[Embeddings]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
    except ImportError:
        return None
    for model in _GEMINI_EMBED_MODELS:
        try:
            emb = GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)
            emb.embed_query("ping")
            return emb
        except Exception:
            continue
    return None


def _get_embeddings() -> Embeddings:
    global _EMBEDDINGS_SINGLETON, _EMBED_BACKEND_USED
    if _EMBEDDINGS_SINGLETON is not None:
        return _EMBEDDINGS_SINGLETON

    prefer = (os.environ.get("FIXBOT_EMBED_BACKEND") or "auto").lower().strip()
    if prefer == "huggingface":
        order = ["huggingface", "hash"]
    elif prefer == "gemini":
        order = ["gemini", "huggingface", "hash"]
    elif prefer == "hash":
        order = ["hash"]
    else:
        order = ["huggingface", "gemini", "hash"]

    for backend in order:
        if backend == "huggingface":
            emb = _try_hf_embeddings()
            if emb is not None:
                _EMBEDDINGS_SINGLETON = emb
                _EMBED_BACKEND_USED = "huggingface"
                return emb
        elif backend == "gemini":
            emb = _try_gemini_embeddings()
            if emb is not None:
                _EMBEDDINGS_SINGLETON = emb
                _EMBED_BACKEND_USED = "gemini"
                return emb
        elif backend == "hash":
            _EMBEDDINGS_SINGLETON = _HashEmbeddings()
            _EMBED_BACKEND_USED = "hash"
            return _EMBEDDINGS_SINGLETON

    _EMBEDDINGS_SINGLETON = _HashEmbeddings()
    _EMBED_BACKEND_USED = "hash"
    return _EMBEDDINGS_SINGLETON


def get_embed_backend() -> str:
    if _EMBED_BACKEND_USED == "none":
        _get_embeddings()
    return _EMBED_BACKEND_USED


def build_index(docs: List[Document], thread_id: str = "default"):
    if not docs:
        _INDEX_CACHE.pop(thread_id, None)
        return None

    raw_fallback = {"_docs": docs}
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError:
        _INDEX_CACHE[thread_id] = raw_fallback
        return raw_fallback

    try:
        embeddings = _get_embeddings()
        vs = FAISS.from_documents(docs, embeddings)
        try:
            vs._raw_docs = docs  # type: ignore[attr-defined]
        except Exception:
            pass
        _INDEX_CACHE[thread_id] = vs
        return vs
    except Exception:
        _INDEX_CACHE[thread_id] = raw_fallback
        return raw_fallback


def retrieve(
    query: str,
    thread_id: str = "default",
    k: int = 8,
    score_threshold: float = 0.0,
) -> List[Tuple[Document, float]]:
    vs = _INDEX_CACHE.get(thread_id)
    if vs is None:
        return []

    if isinstance(vs, dict) and "_docs" in vs:
        return _keyword_retrieve(vs["_docs"], query, k=k, score_threshold=score_threshold)

    try:
        pairs = vs.similarity_search_with_score(query, k=k)
        out: List[Tuple[Document, float]] = []
        for doc, dist in pairs:
            sim = 1.0 / (1.0 + float(dist))
            if sim >= score_threshold:
                out.append((doc, sim))
        if out:
            return out
    except Exception:
        pass

    docs = getattr(vs, "_raw_docs", None)
    if docs:
        return _keyword_retrieve(docs, query, k=k, score_threshold=score_threshold)

    try:
        docs2 = vs.similarity_search(query, k=k)
        return [(d, 1.0) for d in docs2]
    except Exception:
        return []


def _keyword_retrieve(
    docs: List[Document],
    query: str,
    k: int = 8,
    score_threshold: float = 0.0,
) -> List[Tuple[Document, float]]:
    q_tokens = [t for t in query.lower().split() if len(t) > 1]
    if not q_tokens:
        return [(d, 0.5) for d in docs[:k]]

    scored: List[Tuple[Document, float]] = []
    for d in docs:
        text = (d.page_content or "").lower()
        hits = sum(1 for tok in q_tokens if tok in text)
        if not hits:
            continue
        sim = hits / len(q_tokens)
        if sim >= score_threshold:
            scored.append((d, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


def clear_index(thread_id: str = "default") -> None:
    _INDEX_CACHE.pop(thread_id, None)