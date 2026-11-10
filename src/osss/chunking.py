"""Split long text into overlapping, boundary-aware chunks."""

from __future__ import annotations

import re
from typing import List

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
