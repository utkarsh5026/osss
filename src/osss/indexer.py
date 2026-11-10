"""Create OpenSearch indexes and bulk-load documents into them."""

from __future__ import annotations

import threading
import time
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, Iterator, List, Optional, Tuple

from ._progress import make_progress
from ._utils import batched, human_bytes, human_count, human_duration, stable_id
from .chunking import chunk_document
from .config import IndexConfig
from .embeddings import Embedder, get_embedder
from .loaders import Document, MissingDependency, UnsupportedFile, is_supported, load
from .metadata import MetadataLike
from .metadata import resolve as resolve_metadata
from .sources import Source, SourceFile

EventCallback = Callable[[Dict[str, Any]], None]


def build_index_body(cfg: IndexConfig, dimension: Optional[int] = None) -> Dict[str, Any]:
    """Settings + mappings for a new osss index."""
    from . import __version__

    a = cfg.analyzer
    keyword = {"type": "keyword", "ignore_above": 1024}
    props: Dict[str, Any] = {
        "content": {"type": "text", "analyzer": a},
        "title": {"type": "text", "analyzer": a, "fields": {"raw": {"type": "keyword", "ignore_above": 512}}},
        "file_name": {"type": "keyword", "ignore_above": 1024, "fields": {"text": {"type": "text", "analyzer": "simple"}}},
        "path": {"type": "keyword", "ignore_above": 4096, "fields": {"text": {"type": "text", "analyzer": "simple"}}},
        "source": keyword,
        "folder": keyword,
        "file_type": {"type": "keyword"},
        "page": {"type": "integer"},
        "record": {"type": "integer"},
        "chunk": {"type": "integer"},
        # hierarchical chunking: the parent a (child) chunk belongs to. The parent
        # text is only stored, not searched; results return it as context.
        "parent_id": {"type": "keyword"},
        "parent_chunk": {"type": "integer"},
        "parent_content": {"type": "text", "index": False},
        "size": {"type": "long"},
        "modified": {"type": "date"},
        "indexed_at": {"type": "date"},
        "fields": {"type": "object", "dynamic": True},  # CSV/JSON columns; numbers in strings become numeric
        "metadata": {"type": "object", "dynamic": True},  # per-file custom metadata (sidecars / metadata=)
    }
    settings: Dict[str, Any] = {
        "number_of_shards": cfg.shards,
        "number_of_replicas": cfg.replicas,
        "refresh_interval": "-1",  # restored after the initial load
        "mapping": {"ignore_malformed": True, "total_fields": {"limit": 5000}},
    }
    if cfg.semantic:
        if not dimension:
            raise ValueError("Embedding dimension is required for semantic indexes")
        settings["knn"] = True
        props["embedding"] = {
            "type": "knn_vector",
            "dimension": int(dimension),
            "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
        }
    meta = {
        "osss": {
            "version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": cfg.to_dict(),
            "embedding_dimension": dimension,
        }
    }
    return {
        "settings": {"index": settings},
        "mappings": {"_meta": meta, "dynamic": True, "numeric_detection": True, "properties": props},
    }


@dataclass
class IngestReport:
    """Summary of an indexing run (renders as a card in notebooks)."""

    index: str
    source: str
    files_total: int = 0
    files_indexed: int = 0
    documents: int = 0
    chunks: int = 0
    bytes_read: int = 0
    elapsed: float = 0.0
    by_type: Counter = field(default_factory=Counter)
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)
    bulk_errors: List[str] = field(default_factory=list)
    write_error_count: int = 0
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed and not self.bulk_errors and not self.cancelled

    def __repr__(self) -> str:
        return (
            f"<IngestReport {self.index}: {self.files_indexed}/{self.files_total} files, "
            f"{self.chunks} chunks, {len(self.skipped)} skipped, {len(self.failed)} failed, "
            f"{human_duration(self.elapsed)}>"
        )

    def summary(self) -> str:
        return (
            f"Indexed {human_count(self.files_indexed)} of {human_count(self.files_total)} files → "
            f"{human_count(self.chunks)} chunks ({human_bytes(self.bytes_read)}) in {human_duration(self.elapsed)}"
        )

    def _repr_html_(self) -> str:
        from .ui.render import report_card

        return report_card(self)

    def __rich__(self):
        from rich.panel import Panel
        from rich.table import Table

        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold")
        t.add_column()
        t.add_row("Index", self.index)
        t.add_row("Source", self.source)
        t.add_row("Files", f"{human_count(self.files_indexed)} indexed / {human_count(self.files_total)} found")
        t.add_row("Chunks", human_count(self.chunks))
        t.add_row("Data read", human_bytes(self.bytes_read))
        t.add_row("Time", human_duration(self.elapsed))
        if self.by_type:
            t.add_row("Types", ", ".join(f"{k or '?'} ×{v}" for k, v in self.by_type.most_common()))
        if self.skipped:
            t.add_row("Skipped", f"[yellow]{len(self.skipped)}[/] (e.g. {self.skipped[0][0].rsplit('/', 1)[-1]}: {self.skipped[0][1]})")
        if self.failed:
            t.add_row("Failed", f"[red]{len(self.failed)}[/] (e.g. {self.failed[0][0].rsplit('/', 1)[-1]}: {self.failed[0][1]})")
        if self.bulk_errors:
            t.add_row("Write errors", f"[red]{self.write_error_count}[/] {self.bulk_errors[0][:120]}")
        style = "green" if self.ok else ("yellow" if not self.failed else "red")
        title = "✓ Index ready" if self.ok else ("Cancelled" if self.cancelled else "Index built with warnings")
        return Panel(t, title=title, border_style=style, expand=False)


def _bounded_map(fn, items: Iterator[Any], workers: int) -> Iterator[Tuple[Any, Any]]:
    """Like ``ThreadPoolExecutor.map`` but with a bounded number of in-flight tasks."""
    window = max(2, workers * 3)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="osss-read") as pool:
        pending: Deque[Tuple[Any, Future]] = deque()
        for item in items:
            pending.append((item, pool.submit(fn, item)))
            if len(pending) >= window:
                it, fut = pending.popleft()
                yield it, fut
        while pending:
            yield pending.popleft()


def _make_actions(
    index: str, f: SourceFile, docs: List[Document], cfg: IndexConfig,
    metadata: Optional[Dict[str, Any]] = None, embedder: Optional[Embedder] = None,
) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    modified = f.modified.isoformat() if f.modified else None
    embed = embedder.embed_documents if embedder is not None else None
    actions = []
    for d in docs:
        key = ("key", d.doc_key) if d.doc_key else (d.page, d.record)
        for ci, piece in enumerate(chunk_document(d.text, cfg, embed)):
            src: Dict[str, Any] = {
                "content": piece.text,
                "title": d.title or f.name,
                "file_name": f.name,
                "path": f.rel_path,
                "source": f.uri,
                "folder": f.folder,
                "file_type": f.ext,
                "chunk": ci,
                "size": f.size,
                "modified": modified,
                "indexed_at": now,
            }
            if d.page is not None:
                src["page"] = d.page
            if d.record is not None:
                src["record"] = d.record
            if d.fields:
                src["fields"] = d.fields
            if metadata:
                src["metadata"] = metadata
            if piece.parent is not None:
                src["parent_id"] = stable_id(f.uri, *key, "parent", piece.parent)
                src["parent_chunk"] = piece.parent
                src["parent_content"] = piece.parent_text
                doc_id = stable_id(f.uri, *key, "child", ci)
            else:
                doc_id = stable_id(f.uri, *key, ci)
            actions.append({"_index": index, "_id": doc_id, "_source": src})
    return actions


def ingest(
    client,
    cfg: IndexConfig,
    source: Source,
    *,
    embedder: Optional[Embedder] = None,
    metadata: MetadataLike = None,
    replace_existing: bool = False,
    progress: bool = True,
    on_event: Optional[EventCallback] = None,
    cancel: Optional[threading.Event] = None,
) -> IngestReport:
    """Read every matching file from ``source`` and index it into ``cfg.name``.

    ``replace_existing`` deletes previously indexed chunks of each file before
    writing the new ones (used when adding to an existing index, so edited
    files don't leave stale chunks behind).

    ``embedder`` computes the stored vectors of a ``semantic`` index, and also
    finds the boundaries for ``chunking="semantic"`` (loaded from the config's
    model when not given).
    """
    from opensearchpy import helpers

    if cfg.chunking == "semantic" and embedder is None:
        embedder = get_embedder(cfg.embedding_provider, cfg.embedding_model)
    vectors = embedder if cfg.semantic else None  # only semantic indexes store embeddings

    t0 = time.time()
    report = IngestReport(index=cfg.name, source=source.uri)
    bar = make_progress(progress)

    def emit(stage: str, **kw: Any) -> None:
        if on_event:
            try:
                on_event({
                    "stage": stage, "files_done": report.files_indexed + len(report.skipped) + len(report.failed),
                    "files_total": report.files_total, "chunks": report.chunks,
                    "errors": len(report.failed) + report.write_error_count, "elapsed": time.time() - t0, **kw,
                })
            except Exception:
                pass

    # 1. discover ------------------------------------------------------------
    emit("scan", message=f"Listing files in {source.uri}")
    bar.start(None, "Scanning " + source.uri)
    files: List[SourceFile] = []
    max_bytes = int(cfg.max_file_mb * 1024 * 1024)
    for f in source.iter_files(cfg.include, cfg.exclude):
        if cfg.file_types is not None and f.ext not in cfg.file_types:
            continue
        if cfg.file_types is None and not is_supported(f.ext) and f.ext:
            report.skipped.append((f.uri, f"unsupported type .{f.ext}"))
            continue
        if f.size > max_bytes:
            report.skipped.append((f.uri, f"larger than {cfg.max_file_mb:g} MB"))
            continue
        files.append(f)
        if len(files) % 500 == 0:
            bar.note(f"{len(files):,} files found")
    report.files_total = len(files) + len(report.skipped)
    bar.close(f"{len(files):,} files to index")

    # 2. read + parse in parallel, 3. chunk, embed and bulk-write ---------------
    def read_and_parse(f: SourceFile):
        meta = resolve_metadata(f, metadata, sidecars=cfg.metadata_files)
        data = f.read()
        return len(data), load(f, cfg, data), meta

    buffer: List[Dict[str, Any]] = []
    pending_sources: List[str] = []

    def flush() -> None:
        if not buffer:
            return
        if replace_existing and pending_sources:
            try:
                client.delete_by_query(
                    index=cfg.name, body={"query": {"terms": {"source": pending_sources}}},
                    conflicts="proceed", refresh=True,
                )
            except Exception:
                pass
        for part in batched(buffer, max(1, cfg.batch_size)):
            if vectors is not None:
                vecs = vectors.embed_documents([a["_source"]["content"] for a in part])
                for a, v in zip(part, vecs):
                    a["_source"]["embedding"] = v
            _, errors = helpers.bulk(
                client, part, raise_on_error=False, raise_on_exception=False,
                stats_only=False, request_timeout=120,
            )
            for e in errors or []:
                op = next(iter(e.values()), {}) if isinstance(e, dict) else {}
                err = op.get("error", e) if isinstance(op, dict) else e
                msg = err.get("reason", str(err)) if isinstance(err, dict) else str(err)
                report.write_error_count += 1
                if len(report.bulk_errors) < 50:
                    report.bulk_errors.append(f"{op.get('_id', '?')}: {msg}")
        buffer.clear()
        pending_sources.clear()

    bar = make_progress(progress)
    bar.start(len(files), f"Indexing into '{cfg.name}'", unit="files")
    emit("index", message="Reading files")
    done = 0
    try:
        for f, fut in _bounded_map(read_and_parse, iter(files), max(1, cfg.workers)):
            if cancel is not None and cancel.is_set():
                fut.cancel()
                report.cancelled = True
                continue
            try:
                nbytes, docs, meta = fut.result()
                actions = _make_actions(cfg.name, f, docs, cfg, meta, embedder)
            except (UnsupportedFile, MissingDependency) as e:
                report.skipped.append((f.uri, str(e)))
            except Exception as e:  # read / parse / chunking failure; keep going
                report.failed.append((f.uri, f"{type(e).__name__}: {e}"[:300]))
            else:
                report.bytes_read += nbytes
                report.documents += len(docs)
                report.chunks += len(actions)
                report.files_indexed += 1
                report.by_type[f.ext] += 1
                buffer.extend(actions)
                pending_sources.append(f.uri)
                if len(buffer) >= cfg.batch_size:
                    emit("write", current=f.name, message="Embedding & writing" if vectors else "Writing")
                    flush()
            done += 1
            bar.update(done, f.name)
            emit("index", current=f.name, message=f"Indexed {f.name}")
        flush()
    except BaseException as e:
        bar.close(f"stopped: {e}", ok=False)
        raise
    finally:
        try:
            client.indices.put_settings(index=cfg.name, body={"index": {"refresh_interval": "1s"}})
            client.indices.refresh(index=cfg.name)
        except Exception:
            pass
    report.elapsed = time.time() - t0
    bar.close(f"{human_count(report.chunks)} chunks · {human_duration(report.elapsed)}", ok=report.ok or not report.failed)
    emit("done", report=report, message=report.summary())
    return report
