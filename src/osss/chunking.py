"""Split documents into searchable chunks.

Strategies (see :data:`STRATEGIES`):

* ``fixed``: overlapping, boundary-aware chunks of at most ``chunk_size`` characters.
* ``hierarchical``: small child chunks are searched; each carries the larger
  parent chunk it came from, which is what search results return.
* ``semantic``: chunk boundaries go where the meaning shifts between sentences,
  measured with the index's embedding model.
* ``none``: each document (file, page or record) is one chunk.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from .config import IndexConfig

_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]


def _split(text: str, size: int, seps: List[str]) -> List[str]:
    """Recursively split ``text`` into pieces no longer than ``size``."""
    if len(text) <= size:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            pieces = text.split(sep)
            out: List[str] = []
            for j, piece in enumerate(pieces):
                # keep the separator attached so we can re-join faithfully
                piece = piece + sep if j < len(pieces) - 1 else piece
                if len(piece) > size:
                    out.extend(_split(piece, size, seps[i + 1:]))
                elif piece:
                    out.append(piece)
            return out
    return [text[k:k + size] for k in range(0, len(text), size)]


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 150) -> List[str]:
    """Split ``text`` into chunks of at most ``chunk_size`` characters.

    Splits prefer paragraph, then line, sentence and word boundaries. Each chunk
    starts with up to ``overlap`` characters from the end of the previous one so
    that sentences spanning a boundary remain findable.
    """
    text = text.strip()
    if not text:
        return []
    if chunk_size <= 0 or len(text) <= chunk_size:
        return [text]
    overlap = max(0, min(overlap, chunk_size // 2))
    body = chunk_size - overlap
    pieces = _split(text, body, _SEPARATORS)

    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) > body:
            chunks.append(current)
            current = ""
        current += piece
    if current.strip():
        chunks.append(current)

    if overlap and len(chunks) > 1:
        out = [chunks[0].strip()]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev[-overlap:]
            # start the overlap on a word boundary
            m = re.search(r"\s", tail)
            if m and m.start() < len(tail) - 1:
                tail = tail[m.start() + 1:]
            out.append((tail + cur).strip())
        chunks = out
    else:
        chunks = [c.strip() for c in chunks]
    return [c for c in chunks if c]


# ------------------------------------------------------------------ strategies
#: Chunking strategies (names follow Amazon Bedrock Knowledge Bases).
STRATEGIES = {
    "fixed": "Fixed size: split at paragraph / sentence boundaries",
    "hierarchical": "Hierarchical: match small chunks, return their larger parent",
    "semantic": "Semantic: split where the topic changes (uses the embedding model)",
    "none": "None: index each file / page / record whole",
}
_ALIASES = {"fixed_size": "fixed", "default": "fixed", "whole": "none", "no_chunking": "none"}


def normalize_strategy(name: str) -> str:
    """``"FIXED_SIZE"`` / ``"Hierarchical"`` → ``"fixed"`` / ``"hierarchical"``."""
    key = str(name or "fixed").strip().lower().replace("-", "_").replace(" ", "_")
    key = _ALIASES.get(key, key)
    if key not in STRATEGIES:
        raise ValueError(f"Unknown chunking strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return key


@dataclass
class Chunk:
    """One searchable piece of a document.

    For hierarchical chunking ``parent`` is the parent's position in the
    document and ``parent_text`` its full text; both are ``None`` otherwise.
    """

    text: str
    parent: Optional[int] = None
    parent_text: Optional[str] = None


def hierarchical_chunks(text: str, parent_size: int, child_size: int, overlap: int = 0) -> List[Chunk]:
    """Split ``text`` into parents of ``parent_size`` characters, then each parent
    into overlapping children of ``child_size``. Children never cross parents."""
    out: List[Chunk] = []
    for pi, parent in enumerate(chunk_text(text, parent_size, 0)):
        for child in chunk_text(parent, child_size, overlap):
            out.append(Chunk(child, pi, parent))
    return out


# Sentence ends (followed by whitespace) and line breaks. The boundary is the
# end of the match, so sentences keep their punctuation and trailing space.
_SENTENCE_END = re.compile(r"[.!?。！？]+[\"'”’)\]]*\s+|\n+")


def split_sentences(text: str) -> List[str]:
    """Split into sentences / lines. ``"".join(result) == text``."""
    out: List[str] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        piece = text[start:m.end()]
        if out and not piece.strip():
            out[-1] += piece
        else:
            out.append(piece)
        start = m.end()
    if start < len(text):
        tail = text[start:]
        if out and not tail.strip():
            out[-1] += tail
        else:
            out.append(tail)
    return out


def _cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 1.0
    return 1.0 - dot / (na * nb)


def _percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile (like ``numpy.percentile``)."""
    s = sorted(values)
    if not s:
        return 0.0
    pos = (len(s) - 1) * p / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def semantic_chunks(
    text: str,
    embed: Callable[[List[str]], List[List[float]]],
    max_size: int = 1000,
    breakpoint_percentile: float = 95.0,
    buffer: int = 1,
) -> List[str]:
    """Split ``text`` where the meaning shifts.

    Each sentence is embedded together with ``buffer`` neighbours on each side.
    The cosine distance between consecutive sentences is measured, and a chunk
    ends wherever it is above the ``breakpoint_percentile`` of all distances in
    the document. A chunk also ends before it would exceed ``max_size``
    characters; a single sentence longer than that is split by :func:`chunk_text`.
    Text no longer than ``max_size`` is returned whole.
    """
    text = text.strip()
    if not text:
        return []
    if max_size <= 0 or len(text) <= max_size:
        return [text]
    sentences = split_sentences(text)
    breaks: set = set()
    if len(sentences) > 2:
        b = max(0, int(buffer))
        windows = ["".join(sentences[max(0, i - b):i + b + 1]).strip() for i in range(len(sentences))]
        vecs = embed(windows)
        dists = [_cosine_distance(vecs[i], vecs[i + 1]) for i in range(len(vecs) - 1)]
        threshold = _percentile(dists, breakpoint_percentile)
        # a break *before* sentence i + 1
        breaks = {i + 1 for i, d in enumerate(dists) if d > threshold}

    chunks: List[str] = []
    current = ""
    for i, sentence in enumerate(sentences):
        if current and (i in breaks or len(current) + len(sentence.rstrip()) > max_size):
            chunks.append(current)
            current = ""
        if len(sentence.strip()) > max_size:
            chunks.extend(chunk_text(sentence, max_size, 0))
            continue
        current += sentence
    if current.strip():
        chunks.append(current)
    return [c.strip() for c in chunks if c.strip()]


def chunk_document(
    text: str,
    cfg: "IndexConfig",
    embed: Optional[Callable[[List[str]], List[List[float]]]] = None,
) -> List[Chunk]:
    """Split a document's text with the strategy configured in ``cfg``."""
    strategy = cfg.chunking
    if strategy == "none" or not cfg.chunk_size:
        text = text.strip()
        return [Chunk(text)] if text else []
    if strategy == "hierarchical":
        return hierarchical_chunks(text, cfg.parent_chunk_size, cfg.chunk_size, cfg.chunk_overlap)
    if strategy == "semantic":
        if embed is None:
            raise ValueError("Semantic chunking needs an embedding model")
        pieces = semantic_chunks(text, embed, cfg.chunk_size, cfg.breakpoint_percentile, cfg.sentence_buffer)
        return [Chunk(p) for p in pieces]
    return [Chunk(p) for p in chunk_text(text, cfg.chunk_size, cfg.chunk_overlap)]
