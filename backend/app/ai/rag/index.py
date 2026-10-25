"""Local, dependency-free RAG over the project's own documentation.

Why not a vector database: the corpus is a few dozen Markdown files.  A TF-IDF
index is small, fully reproducible, needs no service, no embedding API and no
extra dependency, and it keeps every byte inside the deployment.  It is also
easy to explain to a reviewer, which matters more here than recall on a large
corpus.

The index is a plain JSON file.  Rebuild it with::

    python -m backend.app.ai.rag.index

The build is deterministic: documents are processed in sorted path order, so the
same inputs always produce the same index (apart from the recorded timestamp).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DOC_GLOBS = ("*.md",)


_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё_]{2,}")

_HEADING = re.compile(r"^(#{1,4})\s+(.*)$")


_STEM_LENGTH = 6

MAX_CHUNK_CHARS = 1400
MIN_CHUNK_CHARS = 40


def tokenize(text: str) -> list[str]:
    tokens = []
    for match in _TOKEN.finditer(text.lower()):
        token = match.group(0)
        tokens.append(token[:_STEM_LENGTH] if len(token) > _STEM_LENGTH else token)
    return tokens


@dataclass(frozen=True)
class Chunk:
    id: str
    doc: str
    title: str
    text: str
    score: float = 0.0

    def as_dict(self) -> dict:
        return {"id": self.id, "doc": self.doc, "title": self.title, "text": self.text}


def chunk_markdown(text: str, *, doc: str) -> list[Chunk]:
    """Split one Markdown document into heading-scoped chunks."""

    chunks: list[Chunk] = []
    heading = Path(doc).stem
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if len(body) < MIN_CHUNK_CHARS:
            return
        index = len(chunks)
        chunks.append(Chunk(id=f"{doc}#{index}", doc=doc, title=heading, text=body))

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            buffer = []
            heading = match.group(2).strip() or heading
            buffer.append(f"{match.group(1)} {heading}")
            continue
        buffer.append(line)
        if sum(len(item) for item in buffer) >= MAX_CHUNK_CHARS:
            flush()
            buffer = []
    flush()
    return chunks


def build_index(*, docs_path: Path, output_path: Path) -> dict:
    """Build and persist the TF-IDF index. Returns the index payload."""

    files = sorted(path for glob in DOC_GLOBS for path in docs_path.rglob(glob) if path.is_file())
    chunks: list[Chunk] = []
    for path in files:
        relative = path.relative_to(docs_path).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        chunks.extend(chunk_markdown(text, doc=relative))

    document_frequency: dict[str, int] = {}
    term_frequency: list[dict[str, int]] = []
    for chunk in chunks:
        counts: dict[str, int] = {}
        for token in tokenize(f"{chunk.title}\n{chunk.text}"):
            counts[token] = counts.get(token, 0) + 1
        term_frequency.append(counts)
        for token in counts:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    total = max(1, len(chunks))
    idf = {token: math.log((1 + total) / (1 + df)) + 1.0 for token, df in document_frequency.items()}

    vectors = []
    for counts in term_frequency:
        vector = {token: count * idf.get(token, 1.0) for token, count in counts.items()}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        vectors.append({token: value / norm for token, value in vector.items()})

    payload = {
        "version": 1,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "docsPath": docs_path.as_posix(),
        "documents": [path.relative_to(docs_path).as_posix() for path in files],
        "chunkCount": len(chunks),
        "idf": idf,
        "chunks": [
            {**chunk.as_dict(), "vector": vectors[index]} for index, chunk in enumerate(chunks)
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


class Retriever:
    """Read-only TF-IDF retriever over a previously built index."""

    def __init__(self, index_path: Path):
        self.index_path = index_path
        self._payload: dict | None = None
        self._vectors: list[dict] | None = None

    def _load(self) -> dict | None:
        if self._payload is not None:
            return self._payload
        try:
            self._payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._payload = None
        if self._payload:
            self._vectors = [chunk.get("vector") or {} for chunk in self._payload.get("chunks", [])]
        return self._payload

    @property
    def ready(self) -> bool:
        payload = self._load()
        return bool(payload and payload.get("chunks"))

    @property
    def chunk_count(self) -> int:
        payload = self._load()
        return int(payload.get("chunkCount", 0)) if payload else 0

    def search(self, query: str, *, top_k: int = 4, max_chars: int = 2400) -> list[Chunk]:
        """Return the most relevant chunks, capped by a total character budget."""

        payload = self._load()
        if not payload or top_k <= 0:
            return []
        idf: dict[str, float] = payload.get("idf") or {}
        query_counts: dict[str, int] = {}
        for token in tokenize(query):
            query_counts[token] = query_counts.get(token, 0) + 1
        if not query_counts:
            return []
        query_vector = {token: count * idf.get(token, 1.0) for token, count in query_counts.items()}
        norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0
        query_vector = {token: value / norm for token, value in query_vector.items()}

        scored: list[tuple[float, dict]] = []
        for index, chunk in enumerate(payload.get("chunks", [])):
            vector = self._vectors[index] if self._vectors else {}
            score = sum(weight * vector.get(token, 0.0) for token, weight in query_vector.items())
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))

        results: list[Chunk] = []
        budget = max_chars
        for score, chunk in scored:
            if len(results) >= top_k or budget <= 0:
                break
            text = chunk["text"][:budget]
            budget -= len(text)
            results.append(Chunk(id=chunk["id"], doc=chunk["doc"], title=chunk.get("title", ""), text=text, score=round(score, 4)))
        return results


def main() -> int:
    import argparse

    from ..config import ai_settings

    settings = ai_settings()
    parser = argparse.ArgumentParser(description="Build the local RAG index for the AI Analyst")
    parser.add_argument("--docs", default=settings.docs_path)
    parser.add_argument("--out", default=settings.rag_index_path)
    args = parser.parse_args()

    payload = build_index(docs_path=Path(args.docs), output_path=Path(args.out))
    print(
        f"indexed {payload['chunkCount']} chunks from {len(payload['documents'])} documents "
        f"-> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
