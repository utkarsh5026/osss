"""osss — OpenSearch in your notebook.

Quick start::

    import osss

    cluster = osss.start()                                   # local OpenSearch, no Docker needed
    idx = cluster.create_index("docs", "s3://bucket/docs/")  # or a local folder
    idx.search("how do refunds work?")                       # rich results in the notebook

    osss.ui()                                                # point-and-click app
"""

from __future__ import annotations

from typing import Any, Optional

__version__ = "0.1.0"

from .api import Cluster, Index, OsssError  # noqa: E402
from .config import ANALYZERS, EMBEDDING_MODELS, IndexConfig  # noqa: E402
from .embeddings import (  # noqa: E402
    BedrockEmbedder,
    Embedder,
    FunctionEmbedder,
    SentenceTransformerEmbedder,
    register_embedder,
)
from .indexer import IngestReport  # noqa: E402
from .search import Hit, SearchResults  # noqa: E402
from .server import DEFAULT_VERSION, LocalServer, ServerError  # noqa: E402
from .sources import LocalSource, S3Source  # noqa: E402

_current: Optional[Cluster] = None


def start(
    *,
    semantic: bool = False,
    version: str = DEFAULT_VERSION,
    port: int = 9200,
    heap: str = "1g",
    backend: str = "auto",
    home: Optional[str] = None,
    progress: bool = True,
) -> Cluster:
    """Start (or reconnect to) a local OpenSearch and return a :class:`Cluster`.

    The first call downloads OpenSearch (~250 MB, or ~1 GB with ``semantic=True``,
    which adds the k-NN plugin for vector search). Later calls — even after a
    kernel restart — reuse the running server in about a second.
    """
    global _current
    server = LocalServer(
        version=version, flavor="full" if semantic else "min", port=port, heap=heap,
        backend=backend, home=home,
    )
    server.start(progress=progress)
    _current = Cluster(server.client(), server=server)
    return _current


def connect(url: str = "http://127.0.0.1:9200", **kwargs: Any) -> Cluster:
    """Connect to an existing cluster (self-hosted, Amazon OpenSearch Service, Serverless).

    ``*.amazonaws.com`` endpoints are signed with SigV4 using your AWS credentials
    (the SageMaker execution role works automatically). Pass ``username=`` /
    ``password=`` for basic auth.
    """
    global _current
    from .client import connect as _connect

    client = _connect(url, **kwargs)
    client.info()  # fail fast with a clear error
    _current = Cluster(client, url=url)
    return _current


def current() -> Cluster:
    """The cluster from the last :func:`start`/:func:`connect`, or a running local server."""
    global _current
    if _current is None:
        server = LocalServer()
        if not server.is_running():
            raise OsssError("No cluster yet. Call osss.start() or osss.connect(url) first.")
        _current = Cluster(server.client(), server=server)
    return _current


def stop() -> None:
    """Stop the local OpenSearch server (indexes stay on disk)."""
    global _current
    LocalServer().stop()
    _current = None


def status() -> dict:
    """Status of the local server managed by osss."""
    return LocalServer().status()


def create_index(name: Optional[str] = None, source: Any = None, **options: Any) -> Index:
    """Shortcut for ``osss.current().create_index(...)``."""
    return current().create_index(name, source, **options)


def index(name: str) -> Index:
    """Shortcut for ``osss.current().index(name)``."""
    return current().index(name)


def search(index_name: str, query: str = "", **kwargs: Any) -> SearchResults:
    """Shortcut for ``osss.index(name).search(query, ...)``."""
    return current().index(index_name).search(query, **kwargs)


def ui(cluster: Optional[Cluster] = None):
    """Launch the interactive notebook app (create indexes, search, manage)."""
    from .ui import App

    if cluster is None:
        try:
            cluster = current()
        except OsssError:
            cluster = None
    return App(cluster)


__all__ = [
    "ANALYZERS", "BedrockEmbedder", "Cluster", "DEFAULT_VERSION", "EMBEDDING_MODELS", "Embedder",
    "FunctionEmbedder", "Hit", "Index", "IndexConfig", "IngestReport", "LocalServer", "LocalSource",
    "OsssError", "S3Source", "SearchResults", "SentenceTransformerEmbedder", "ServerError",
    "connect", "create_index", "current", "index", "register_embedder", "search", "start",
    "status", "stop", "ui", "__version__",
]
