"""User-facing configuration for building an index."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ANALYZERS = {
    "standard": "Standard (any language)",
    "english": "English (stemming + stop words)",
    "simple": "Simple (lowercase letters only)",
    "whitespace": "Whitespace (exact tokens, good for code/IDs)",
    "french": "French",
    "german": "German",
    "spanish": "Spanish",
    "italian": "Italian",
    "portuguese": "Portuguese",
    "dutch": "Dutch",
    "hindi": "Hindi",
    "cjk": "Chinese / Japanese / Korean",
}

#: Embedding models offered in the UI. Any sentence-transformers model id or
#: Bedrock embedding model id works through the Python API.
EMBEDDING_MODELS = {
    "sentence-transformers/all-MiniLM-L6-v2": ("sentence-transformers", "MiniLM-L6 · fast, runs locally (384d)"),
    "BAAI/bge-small-en-v1.5": ("sentence-transformers", "BGE small · better quality, local (384d)"),
    "sentence-transformers/all-mpnet-base-v2": ("sentence-transformers", "MPNet base · high quality, local (768d)"),
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": ("sentence-transformers", "Multilingual MiniLM · 50+ languages (384d)"),
    "amazon.titan-embed-text-v2:0": ("bedrock", "Amazon Titan v2 · Bedrock API (1024d)"),
    "cohere.embed-english-v3": ("bedrock", "Cohere English v3 · Bedrock API (1024d)"),
    "cohere.embed-multilingual-v3": ("bedrock", "Cohere Multilingual v3 · Bedrock API (1024d)"),
}

DEFAULT_EXCLUDE = [
    ".*",
    "*/.*",
    "__pycache__/*",
    "*/__pycache__/*",
    "node_modules/*",
    "*/node_modules/*",
    ".ipynb_checkpoints/*",
    "*/.ipynb_checkpoints/*",
    "~$*",
]


@dataclass
class IndexConfig:
    """Everything that controls how files become searchable documents.

    Attributes:
        name: Index name (lowercase letters, digits, ``-`` and ``_``).
        include: Glob patterns to keep, e.g. ``["*.pdf", "reports/**"]``. Empty = all.
        exclude: Glob patterns to skip (hidden files and caches by default).
        file_types: Only these extensions (``["pdf", "md"]``). ``None`` = every supported type.
        chunk_size: Max characters per chunk. ``0`` indexes each document whole.
        chunk_overlap: Characters shared between consecutive chunks.
        analyzer: Text analyzer, see :data:`ANALYZERS`.
        semantic: Also store embeddings for semantic / hybrid search.
        embedding_model: Model id (sentence-transformers or Bedrock).
        embedding_provider: ``"auto"``, ``"sentence-transformers"`` or ``"bedrock"``.
        text_fields: For CSV/JSON/Parquet: columns to search. ``None`` = all text columns.
        title_field: For CSV/JSON/Parquet: column used as the result title.
        id_field: For CSV/JSON/Parquet: column used as a stable document id.
        metadata_files: Read ``<file>.metadata.json`` sidecars (the Amazon Bedrock
            Knowledge Base format) and attach their attributes to every chunk.
        max_file_mb: Skip files larger than this.
        shards / replicas: OpenSearch index settings.
        batch_size: Documents per bulk request.
        workers: Parallel file readers (S3 downloads benefit the most).
    """

    name: str
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    file_types: Optional[List[str]] = None
    chunk_size: int = 1000
    chunk_overlap: int = 150
    analyzer: str = "standard"
    semantic: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_provider: str = "auto"
    text_fields: Optional[List[str]] = None
    title_field: Optional[str] = None
    id_field: Optional[str] = None
    metadata_files: bool = True
    max_file_mb: float = 100.0
    shards: int = 1
    replicas: int = 0
    batch_size: int = 256
    workers: int = 8

    def __post_init__(self) -> None:
        from ._utils import sanitize_index_name

        clean = sanitize_index_name(self.name)
        if clean != self.name:
            raise ValueError(f"Invalid index name {self.name!r}; try {clean!r}")
        if self.analyzer not in ANALYZERS:
            raise ValueError(f"Unknown analyzer {self.analyzer!r}; choose from {sorted(ANALYZERS)}")
        if self.chunk_size < 0 or self.chunk_overlap < 0:
            raise ValueError("chunk_size and chunk_overlap must be >= 0")
        if self.chunk_size and self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.file_types is not None:
            self.file_types = [t.lower().lstrip(".") for t in self.file_types]
        for attr in ("include", "exclude", "text_fields"):
            v = getattr(self, attr)
            if isinstance(v, str):
                setattr(self, attr, [v])
        if self.embedding_provider == "auto":
            known = EMBEDDING_MODELS.get(self.embedding_model)
            if known:
                self.embedding_provider = known[0]
            elif self.embedding_model.startswith(("amazon.", "cohere.")):
                self.embedding_provider = "bedrock"
            else:
                self.embedding_provider = "sentence-transformers"

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IndexConfig":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def replace(self, **changes: Any) -> "IndexConfig":
        return dataclasses.replace(self, **changes)
