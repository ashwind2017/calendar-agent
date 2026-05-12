"""RAG layer: indexing user-provided Drive docs + simple retrieval.

For initial scope we use simple cosine similarity over OpenAI/Anthropic embeddings.
If embeddings are unavailable, we fall back to keyword scoring.
"""
import json
import math
import os
import re
from typing import List, Dict, Optional
from config import config


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """Naive chunker by character count."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i : i + chunk_size])
        i += chunk_size - overlap
    return chunks


def _tokenize(s: str) -> List[str]:
    return [w for w in re.split(r"\W+", s.lower()) if w]


def _keyword_score(query: str, chunk: str) -> float:
    qt = set(_tokenize(query))
    ct = _tokenize(chunk)
    if not qt or not ct:
        return 0.0
    overlap = sum(1 for w in ct if w in qt)
    return overlap / max(len(ct), 1)


class RAGIndex:
    """A per-session index of {chunk, source, embedding?}."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.path = os.path.join(config.CACHE_DIR, f"rag_{session_id}.json")
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        self.entries: List[Dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self.entries = json.load(f)
            except Exception:
                self.entries = []

    def _persist(self):
        with open(self.path, "w") as f:
            json.dump(self.entries, f)

    def add_document(self, source: str, text: str, embed_fn=None):
        """Chunk + (optionally) embed + store."""
        chunks = _chunk_text(text)
        for chunk in chunks:
            entry = {"source": source, "chunk": chunk}
            if embed_fn:
                try:
                    entry["embedding"] = embed_fn(chunk)
                except Exception:
                    entry["embedding"] = None
            self.entries.append(entry)
        self._persist()

    def clear(self):
        self.entries = []
        if os.path.exists(self.path):
            os.remove(self.path)

    def retrieve(self, query: str, k: int = 5, embed_fn=None) -> List[Dict]:
        """Return top k chunks for the query."""
        if not self.entries:
            return []

        scored = []
        q_emb = None
        if embed_fn:
            try:
                q_emb = embed_fn(query)
            except Exception:
                q_emb = None

        for entry in self.entries:
            if q_emb and entry.get("embedding"):
                score = _cosine(q_emb, entry["embedding"])
            else:
                score = _keyword_score(query, entry["chunk"])
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"chunk": e["chunk"], "source": e["source"], "score": s}
            for s, e in scored[:k]
        ]

    def all_text(self) -> str:
        """Return all indexed text concatenated. Useful when data fits in context (context injection)."""
        return "\n\n".join(f"[{e['source']}]\n{e['chunk']}" for e in self.entries)


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def get_embed_fn():
    """Return an embedding function if OpenAI is configured, else None.

    Anthropic does not currently expose embeddings; OpenAI is the cheap path.
    Without embeddings we fall back to keyword scoring which is fine for small corpora.
    """
    if not config.OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)

        def embed(text: str) -> List[float]:
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return resp.data[0].embedding
        return embed
    except Exception:
        return None


_indexes: Dict[str, RAGIndex] = {}


def get_index(session_id: str) -> RAGIndex:
    if session_id not in _indexes:
        _indexes[session_id] = RAGIndex(session_id)
    return _indexes[session_id]
