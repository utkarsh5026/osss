# Python API

Everything is available from the top-level `osss` package.

```python
import osss
```

## Starting and connecting

| Function | Returns | |
| --- | --- | --- |
| `osss.start(semantic=False, heap="1g", port=9200, backend="auto", version="3.9.0", home=None, progress=True)` | `Cluster` | Start or reconnect to the local OpenSearch |
| `osss.connect(url, username=None, password=None, aws_auth=None, aws_region=None, verify_certs=True)` | `Cluster` | Connect to an existing cluster. SigV4 is used automatically for `*.amazonaws.com`. |
| `osss.ui(cluster=None)` | `App` | The notebook app |
| `osss.current()` | `Cluster` | The cluster from the last `start` / `connect` |
| `osss.status()` | `dict` | Local server status |
| `osss.stop()` | | Stop the local server (data is kept) |

Shortcuts that use `osss.current()`:

```python
osss.create_index("docs", "./docs")      # cluster.create_index(...)
osss.index("docs")                        # cluster.index("docs")
osss.search("docs", "refund")             # cluster.index("docs").search("refund")
```

## `Cluster`

```python
cluster = osss.start()
```

| Member | |
| --- | --- |
| `create_index(name=None, source=None, *, config=None, recreate=False, embedder=None, metadata=None, progress=True, **options)` | Create an index and fill it from `source`. `options` are any [IndexConfig fields](configuration.md). `metadata` is a dict or `fn(SourceFile) -> dict` attached to every chunk ([custom metadata](../guide/metadata.md)). Returns an `Index`. |
| `index(name)` / `cluster[name]` | Open an existing index |
| `indexes()` | List of `{name, docs, size_bytes, health, status}` |
| `index_names()` | List of names |
| `exists(name)` | `bool` |
| `delete_index(name)` | |
| `scan(source, include=(), exclude=None, limit=None)` | Preview a source → `ScanSummary` |
| `info()` | URL, version, health, whether semantic search is available |
| `has_knn()` | Whether the cluster supports vector search |
| `client` | The underlying `opensearchpy.OpenSearch` client |
| `server` | The `LocalServer`, or `None` for remote clusters |
| `ui()` | The app, bound to this cluster |

## `Index`

```python
idx = cluster.index("docs")
```

| Member | |
| --- | --- |
| `search(query="", *, mode=None, k=10, offset=0, filters=None, file_type=None, metadata=None, fuzzy=False, operator="or")` | → `SearchResults`. See [Searching](../guide/searching.md). `idx(query)` is the same. |
| `add(source, *, metadata=None, **overrides)` | Index more files; previously indexed files are replaced → `IngestReport` |
| `sample(n=5)` | A few documents |
| `get(doc_id)` | One chunk's stored fields |
| `count()` | Number of chunks |
| `stats()` | Files, chunks, size, file types, settings |
| `config` | The `IndexConfig` used to build it |
| `semantic` | `True` if built with embeddings |
| `last_report` | `IngestReport` from the last build / add in this session |
| `delete()`, `refresh()` | |

## Results

`SearchResults` behaves like a list of `Hit` objects:

| `SearchResults` | |
| --- | --- |
| `hits`, `total`, `took_ms`, `query`, `mode`, `offset` | |
| `to_pandas()` / `to_list()` | DataFrame / list of dicts |
| `context(max_chars=12000)` | Numbered, cited text for LLM prompts |

| `Hit` | |
| --- | --- |
| `title`, `content`, `snippet` | Snippet is HTML with `<mark>` around matches |
| `path`, `source`, `file_name`, `file_type` | Where it came from |
| `page`, `record`, `chunk` | PDF page, CSV/JSON row, chunk number |
| `score`, `fields`, `metadata`, `id` | `fields` holds CSV/JSON/Parquet columns; `metadata` your custom metadata |
| `parent_id`, `matched` | [Hierarchical](../guide/chunking.md#hierarchical) indexes: `content` is the parent chunk, `matched` the child chunk that matched |

## `IngestReport`

| | |
| --- | --- |
| `files_total`, `files_indexed`, `documents`, `chunks`, `bytes_read`, `elapsed` | Counts |
| `skipped`, `failed` | Lists of `(file, reason)` |
| `bulk_errors`, `write_error_count` | Problems writing to OpenSearch |
| `ok`, `summary()` | |

## Embedders

| Class | |
| --- | --- |
| `SentenceTransformerEmbedder(model="sentence-transformers/all-MiniLM-L6-v2", device=None)` | Local model |
| `BedrockEmbedder(model="amazon.titan-embed-text-v2:0", region=None, dimensions=None)` | Amazon Bedrock |
| `FunctionEmbedder(fn, dimension=None, name="custom")` | Wrap any `fn(list[str]) -> list[list[float]]` |
| `register_embedder(embedder, provider="custom")` | Make a custom embedder available to indexes that use it |

Pass one directly with `cluster.create_index(..., embedder=...)`.

## `LocalServer`

Lower-level control over the local OpenSearch:

```python
server = osss.LocalServer(flavor="min", port=9200, heap="1g", backend="auto")
server.start()
server.status(); server.logs(100); server.url
server.stop()
server.uninstall(keep_data=False)
```

## Sources

```python
from osss import LocalSource, S3Source
cluster.create_index("docs", S3Source("s3://bucket/x/", profile="analytics", region="eu-west-1"))
```

Every object above displays nicely in a notebook: just put it on the last line of a cell.
