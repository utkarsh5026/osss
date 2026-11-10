"""High-level, notebook-friendly API: :class:`Cluster` and :class:`Index`."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

from ._utils import sanitize_index_name
from .config import IndexConfig
from .embeddings import Embedder, get_embedder, register_embedder
from .indexer import EventCallback, IngestReport, build_index_body, ingest
from .search import SearchResults, run_search
from .server import LocalServer
from .sources import ScanSummary, SourceLike, resolve_source


class OsssError(RuntimeError):
    pass


def default_index_name(source: SourceLike) -> str:
    s = source if isinstance(source, str) else getattr(source, "uri", str(source))
    if isinstance(source, (list, tuple)):
        s = str(source[0])
    s = os.fspath(s).rstrip("/")
    base = s.rsplit("/", 1)[-1] or s.replace("s3://", "")
    base = base.rsplit(".", 1)[0] if "." in base and not base.startswith(".") else base
    return sanitize_index_name(base or "my-index")


class Index:
    """A searchable index. Get one from :meth:`Cluster.index` or :meth:`Cluster.create_index`."""

    def __init__(self, cluster: "Cluster", name: str) -> None:
        self.cluster = cluster
        self.name = name
        self.last_report: Optional[IngestReport] = None
        self._meta: Optional[Dict[str, Any]] = None
        self._embedder: Optional[Embedder] = None

    @property
    def client(self):
        return self.cluster.client

    # ----------------------------------------------------------- metadata
    @property
    def meta(self) -> Dict[str, Any]:
        if self._meta is None:
            m = self.client.indices.get_mapping(index=self.name)
            mapping = next(iter(m.values()))["mappings"]
            self._meta = (mapping.get("_meta") or {}).get("osss", {})
            self._meta["_has_vectors"] = "embedding" in mapping.get("properties", {})
        return self._meta

    @property
    def config(self) -> Optional[IndexConfig]:
        cfg = self.meta.get("config")
        try:
            return IndexConfig.from_dict(cfg) if cfg else None
        except Exception:
            return None

    @property
    def semantic(self) -> bool:
        return bool(self.meta.get("_has_vectors"))

    @property
    def embedder(self) -> Optional[Embedder]:
        if self._embedder is None and self.semantic and self.config is not None:
            self._embedder = get_embedder(self.config.embedding_provider, self.config.embedding_model)
        return self._embedder

    @embedder.setter
    def embedder(self, value: Embedder) -> None:
        self._embedder = value

    # ----------------------------------------------------------- search
    def search(
        self,
        query: str = "",
        *,
        mode: Optional[str] = None,
        k: int = 10,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        file_type: Optional[Any] = None,
        fuzzy: bool = False,
        operator: str = "or",
        facets: bool = False,
    ) -> SearchResults:
        """Search the index.

        Args:
            query: Free text. Supports ``"exact phrases"``, ``-exclude``, ``prefix*`` and ``a | b``.
            mode: ``"keyword"`` (BM25), ``"semantic"`` (vectors) or ``"hybrid"`` (both, fused).
                Defaults to hybrid for semantic indexes, keyword otherwise.
            k: Number of results. ``offset`` pages through them.
            filters: e.g. ``{"file_type": ["pdf"], "folder": "reports", "fields.year": {"gte": 2020}}``.
            file_type: Shortcut for ``filters={"file_type": ...}``.
            fuzzy: Tolerate typos.
            operator: ``"or"`` (any word) or ``"and"`` (all words).
        """
        if mode is None:
            mode = "hybrid" if self.semantic and query.strip() else "keyword"
        filters = dict(filters or {})
        if file_type:
            filters["file_type"] = file_type
        return run_search(
            self.client, self.name, query, mode=mode, k=k, offset=offset, filters=filters,
            embedder=self.embedder if mode != "keyword" else None, operator=operator,
            fuzzy=fuzzy, facets=facets,
        )

    __call__ = search

    def sample(self, n: int = 5) -> SearchResults:
        """A few documents from the index (no query)."""
        return self.search("", k=n, mode="keyword")

    def get(self, doc_id: str) -> Dict[str, Any]:
        return self.client.get(index=self.name, id=doc_id)["_source"]

    # ----------------------------------------------------------- write
    def add(self, source: SourceLike, *, progress: bool = True, on_event: Optional[EventCallback] = None,
            cancel: Optional[threading.Event] = None, **overrides: Any) -> IngestReport:
        """Index more files (or re-index changed ones) using this index's settings."""
        cfg = self.config or IndexConfig(name=self.name)
        if overrides:
            cfg = cfg.replace(**overrides)
        report = ingest(
            self.client, cfg, resolve_source(source), embedder=self.embedder, replace_existing=True,
            progress=progress, on_event=on_event, cancel=cancel,
        )
        self.last_report = report
        return report

    def delete(self) -> None:
        self.client.indices.delete(index=self.name)

    def refresh(self) -> None:
        self.client.indices.refresh(index=self.name)

    # ----------------------------------------------------------- stats
    def count(self) -> int:
        """Number of chunks (searchable documents)."""
        return int(self.client.count(index=self.name)["count"])

    def stats(self) -> Dict[str, Any]:
        r = self.client.search(index=self.name, body={
            "size": 0, "track_total_hits": True,
            "aggs": {
                "files": {"cardinality": {"field": "source"}},
                "types": {"terms": {"field": "file_type", "size": 50}},
                "modified": {"max": {"field": "indexed_at"}},
            },
        })
        size = 0
        try:
            st = self.client.indices.stats(index=self.name, metric="store")
            size = st["indices"][self.name]["total"]["store"]["size_in_bytes"]
        except Exception:
            pass
        cfg = self.config
        return {
            "name": self.name,
            "chunks": r["hits"]["total"]["value"],
            "files": r["aggregations"]["files"]["value"],
            "file_types": {b["key"]: b["doc_count"] for b in r["aggregations"]["types"]["buckets"]},
            "size_bytes": size,
            "semantic": self.semantic,
            "embedding_model": cfg.embedding_model if (cfg and self.semantic) else None,
            "analyzer": cfg.analyzer if cfg else None,
            "chunk_size": cfg.chunk_size if cfg else None,
            "created_at": self.meta.get("created_at"),
            "last_indexed": r["aggregations"]["modified"].get("value_as_string"),
            "managed": bool(self.meta),
        }

    def file_types(self) -> Dict[str, int]:
        return self.stats()["file_types"]

    def __repr__(self) -> str:
        return f"<Index {self.name!r}{' semantic' if self.semantic else ''}>"

    def _repr_html_(self) -> str:
        from .ui.render import index_card

        return index_card(self.stats())


class Cluster:
    """A connection to OpenSearch, local (``osss.start()``) or remote (``osss.connect()``)."""

    def __init__(self, client, server: Optional[LocalServer] = None, url: Optional[str] = None) -> None:
        self.client = client
        self.server = server
        self.url = url or (server.url if server else "")

    # ----------------------------------------------------------- info
    def info(self) -> Dict[str, Any]:
        i = self.client.info()
        h = self.client.cluster.health()
        return {
            "url": self.url, "version": i.get("version", {}).get("number"),
            "distribution": i.get("version", {}).get("distribution", "opensearch"),
            "health": h.get("status"), "local": self.server is not None,
            "semantic": self.has_knn(), "flavor": self.server.flavor if self.server else None,
        }

    def has_knn(self) -> bool:
        try:
            plugins = self.client.cat.plugins(format="json")
            return any("knn" in (p.get("component") or "") for p in plugins)
        except Exception:
            return False

    def indexes(self, all: bool = False) -> List[Dict[str, Any]]:
        """Indexes on the cluster (system indexes hidden unless ``all=True``)."""
        rows = self.client.cat.indices(format="json", bytes="b")
        out = []
        for r in rows:
            name = r.get("index", "")
            if not all and name.startswith("."):
                continue
            out.append({
                "name": name, "docs": int(r.get("docs.count") or 0), "size_bytes": int(r.get("store.size") or 0),
                "health": r.get("health"), "status": r.get("status"),
            })
        return sorted(out, key=lambda r: r["name"])

    def index_names(self) -> List[str]:
        return [r["name"] for r in self.indexes()]

    def exists(self, name: str) -> bool:
        return bool(self.client.indices.exists(index=name))

    def index(self, name: str) -> Index:
        if not self.exists(name):
            raise KeyError(f"No index named {name!r}. Existing: {', '.join(self.index_names()) or 'none'}")
        return Index(self, name)

    __getitem__ = index

    def delete_index(self, name: str) -> None:
        self.client.indices.delete(index=name)

    # ----------------------------------------------------------- create
    def scan(self, source: SourceLike, include=(), exclude=None, limit: Optional[int] = None) -> ScanSummary:
        """Preview what a source contains, without indexing anything."""
        from .config import DEFAULT_EXCLUDE

        return resolve_source(source).scan(include, DEFAULT_EXCLUDE if exclude is None else exclude, limit)

    def _ensure_knn(self, progress: bool) -> None:
        if self.has_knn():
            return
        if self.server is not None:
            # Upgrade the local server to the distribution that includes k-NN.
            self.server.flavor = "full"
            self.server.start(progress=progress)
            from .client import connect

            self.client = connect(self.server.url)
            self.url = self.server.url
            if self.has_knn():
                return
        raise OsssError(
            "Semantic search needs the OpenSearch k-NN plugin, which this cluster does not have. "
            "Use osss.start(semantic=True) or an Amazon OpenSearch Service domain."
        )

    def create_index(
        self,
        name: Optional[str] = None,
        source: Optional[SourceLike] = None,
        *,
        config: Optional[IndexConfig] = None,
        recreate: bool = False,
        embedder: Optional[Embedder] = None,
        progress: bool = True,
        on_event: Optional[EventCallback] = None,
        cancel: Optional[threading.Event] = None,
        **options: Any,
    ) -> Index:
        """Create an index and (optionally) fill it from a folder or S3 prefix.

        ``options`` are :class:`~osss.config.IndexConfig` fields, e.g.
        ``chunk_size=800, include=["*.pdf"], semantic=True, analyzer="english"``.

        Example::

            idx = cluster.create_index("reports", "s3://my-bucket/reports/", include=["*.pdf"])
        """
        if name is None:
            if source is None:
                raise ValueError("Give an index name or a source")
            name = default_index_name(source)
        if config is None:
            if embedder is not None:
                options.setdefault("semantic", True)
                options.setdefault("embedding_model", embedder.name)
                options.setdefault("embedding_provider", "custom")
            config = IndexConfig(name=name, **options)
        elif options:
            config = config.replace(name=name, **options)
        cfg = config

        if self.exists(cfg.name):
            if not recreate:
                raise OsssError(
                    f"Index {cfg.name!r} already exists. Pass recreate=True to rebuild it, "
                    f"or use cluster.index({cfg.name!r}).add(source) to add files."
                )
            self.delete_index(cfg.name)

        dim = None
        if cfg.semantic:
            self._ensure_knn(progress)
            if embedder is None:
                embedder = get_embedder(cfg.embedding_provider, cfg.embedding_model)
            dim = embedder.dimension
        self.client.indices.create(index=cfg.name, body=build_index_body(cfg, dim))
        idx = Index(self, cfg.name)
        if embedder is not None:
            idx.embedder = embedder
            if cfg.embedding_provider == "custom":
                register_embedder(embedder, "custom")
        if source is not None:
            idx.last_report = ingest(
                self.client, cfg, resolve_source(source), embedder=embedder,
                progress=progress, on_event=on_event, cancel=cancel,
            )
        else:
            self.client.indices.put_settings(index=cfg.name, body={"index": {"refresh_interval": "1s"}})
        return idx

    # ----------------------------------------------------------- misc
    def stop(self) -> None:
        if self.server is None:
            raise OsssError("This cluster is not managed by osss (connected with osss.connect).")
        self.server.stop()

    def ui(self):
        from .ui import App

        return App(self)

    def __repr__(self) -> str:
        return f"<Cluster {self.url}{' (local)' if self.server else ''}>"

    def _repr_html_(self) -> str:
        from .ui.render import cluster_card

        try:
            info = self.info()
            rows = self.indexes()
        except Exception as e:  # pragma: no cover - connection problems
            info, rows = {"url": self.url, "error": str(e)}, []
        return cluster_card(info, rows)
