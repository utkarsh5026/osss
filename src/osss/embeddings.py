"""Embedding providers for semantic search.

* ``sentence-transformers`` — runs locally (CPU or GPU), no API keys.
* ``bedrock`` — Amazon Bedrock (Titan / Cohere) using your AWS credentials;
  ideal on SageMaker where the execution role already has access.
* Any object with ``dimension`` and ``embed_documents`` / ``embed_query``.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Sequence, Tuple


class Embedder:
    name: str = "custom"
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class FunctionEmbedder(Embedder):
    """Wrap any ``fn(list[str]) -> list[list[float]]``."""

    def __init__(self, fn: Callable[[List[str]], List[List[float]]], dimension: Optional[int] = None, name: str = "custom") -> None:
        self.fn = fn
        self.name = name
        self.dimension = dimension or len(fn(["dimension probe"])[0])

    def embed_documents(self, texts):
        return [list(map(float, v)) for v in self.fn(list(texts))]


class SentenceTransformerEmbedder(Embedder):
    # Models that expect instruction prefixes for queries.
    _QUERY_PREFIX = {
        "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
        "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
        "BAAI/bge-large-en-v1.5": "Represent this sentence for searching relevant passages: ",
    }

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2", device: Optional[str] = None, batch_size: int = 64) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "Semantic search with local models needs sentence-transformers:\n"
                "    %pip install 'osss[semantic]'    (or: pip install sentence-transformers)\n"
                "Alternatively use a Bedrock model, e.g. embedding_model='amazon.titan-embed-text-v2:0'."
            ) from e
        self.name = model
        self.batch_size = batch_size
        self.model = SentenceTransformer(model, device=device)
        get_dim = getattr(self.model, "get_embedding_dimension", None) or getattr(
            self.model, "get_sentence_embedding_dimension", None
        )
        self.dimension = int(get_dim() if get_dim else len(self.model.encode(["probe"])[0]))
        if model.startswith("intfloat/e5") or "/e5-" in model:
            self._doc_prefix, self._query_prefix = "passage: ", "query: "
        else:
            self._doc_prefix, self._query_prefix = "", self._QUERY_PREFIX.get(model, "")

    def embed_documents(self, texts):
        vecs = self.model.encode(
            [self._doc_prefix + t for t in texts], batch_size=self.batch_size,
            normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True,
        )
        return vecs.tolist()

    def embed_query(self, text):
        return self.model.encode([self._query_prefix + text], normalize_embeddings=True, show_progress_bar=False)[0].tolist()


class BedrockEmbedder(Embedder):
    def __init__(self, model: str = "amazon.titan-embed-text-v2:0", region: Optional[str] = None, dimensions: Optional[int] = None, max_workers: int = 8) -> None:
        import boto3

        self.name = model
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.max_workers = max_workers
        self._dims = dimensions
        self.is_cohere = model.startswith("cohere.")
        self.dimension = dimensions or len(self.embed_query("dimension probe"))

    def _titan(self, text: str) -> List[float]:
        body: Dict[str, object] = {"inputText": text[:40000]}
        if "v2" in self.name:
            body["normalize"] = True
            if self._dims:
                body["dimensions"] = self._dims
        r = self.client.invoke_model(modelId=self.name, body=json.dumps(body), accept="application/json", contentType="application/json")
        return json.loads(r["body"].read())["embedding"]

    def _cohere(self, texts: List[str], input_type: str) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), 96):
            body = {"texts": [t[:2048] for t in texts[i:i + 96]], "input_type": input_type, "truncate": "END"}
            r = self.client.invoke_model(modelId=self.name, body=json.dumps(body), accept="application/json", contentType="application/json")
            out.extend(json.loads(r["body"].read())["embeddings"])
        return out

    def embed_documents(self, texts):
        if self.is_cohere:
            return self._cohere(list(texts), "search_document")
        with ThreadPoolExecutor(self.max_workers) as pool:
            return list(pool.map(self._titan, texts))

    def embed_query(self, text):
        if self.is_cohere:
            return self._cohere([text], "search_query")[0]
        return self._titan(text)


_CACHE: Dict[Tuple[str, str], Embedder] = {}
_LOCK = threading.Lock()


def get_embedder(provider: str, model: str) -> Embedder:
    """Return a cached embedder (models are loaded once per process)."""
    key = (provider, model)
    with _LOCK:
        if key not in _CACHE:
            if provider == "bedrock":
                _CACHE[key] = BedrockEmbedder(model)
            elif provider in ("sentence-transformers", "st", "local"):
                _CACHE[key] = SentenceTransformerEmbedder(model)
            elif provider == "custom":
                raise LookupError(
                    f"This index was built with the custom embedder {model!r}. Register it in this "
                    "session with osss.register_embedder(my_embedder) or set index.embedder = my_embedder."
                )
            else:
                raise ValueError(f"Unknown embedding provider {provider!r}")
        return _CACHE[key]


def register_embedder(embedder: Embedder, provider: str = "custom") -> None:
    """Make a custom embedder available to indexes that reference its name."""
    with _LOCK:
        _CACHE[(provider, embedder.name)] = embedder
