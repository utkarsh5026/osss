# All options

## Index options (`IndexConfig`)

Pass these to `cluster.create_index(...)` as keyword arguments, build an `osss.IndexConfig`, or set them in the app's **＋ New index** tab.

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | str | from the source | Lowercase letters, digits, `-` and `_` |
| `include` | list[str] | `[]` (all) | Glob patterns to keep. Patterns without `/` match the file name. |
| `exclude` | list[str] | hidden files, `__pycache__`, `node_modules` | Glob patterns to skip (replaces the defaults) |
| `file_types` | list[str] \| None | `None` (all supported) | Extensions to index, e.g. `["pdf", "md"]` |
| `chunking` | str | `"fixed"` | [Chunking strategy](../guide/chunking.md): `fixed`, `hierarchical`, `semantic` or `none`. Bedrock names (`FIXED_SIZE`, …) work too. |
| `chunk_size` | int | `1000` | Max characters per chunk; `0` = no chunking. For `hierarchical`, the child size. |
| `chunk_overlap` | int | `150` | Characters shared between neighbouring chunks (not used by `semantic`) |
| `parent_chunk_size` | int | `4000` | `hierarchical`: max characters per parent chunk, returned as the result |
| `breakpoint_percentile` | float | `95` | `semantic`: split where the distance between sentences is above this percentile |
| `sentence_buffer` | int | `1` | `semantic`: neighbouring sentences embedded with each sentence |
| `analyzer` | str | `"standard"` | `standard`, `english`, `french`, `german`, `spanish`, `italian`, `portuguese`, `dutch`, `hindi`, `cjk`, `simple`, `whitespace` |
| `semantic` | bool | `False` | Also store embeddings for semantic and hybrid search |
| `embedding_model` | str | `"sentence-transformers/all-MiniLM-L6-v2"` | Any sentence-transformers or Bedrock model id |
| `embedding_provider` | str | `"auto"` | `sentence-transformers`, `bedrock` or `custom`; `auto` infers it from the model id |
| `text_fields` | list[str] \| None | `None` (all text columns) | CSV/JSON/Parquet columns to search |
| `title_field` | str \| None | auto | Column used as the result title |
| `id_field` | str \| None | `None` | Column used as a stable ID |
| `metadata_files` | bool | `True` | Read `<file>.metadata.json` sidecars ([Bedrock format](../guide/metadata.md)) and attach them to every chunk |
| `max_file_mb` | float | `100` | Skip larger files |
| `workers` | int | `8` | Files read in parallel |
| `batch_size` | int | `256` | Chunks per bulk request and embedding batch |
| `shards` | int | `1` | OpenSearch primary shards |
| `replicas` | int | `0` | OpenSearch replicas |

## Server options (`osss.start`)

| Option | Default | Description |
| --- | --- | --- |
| `semantic` | `False` | Include the k-NN plugin |
| `heap` | `"1g"` | Java heap size |
| `port` | `9200` | HTTP port; the next free one is used if it's taken |
| `backend` | `"auto"` | `docker`, `tarball`, or `auto` (Docker if available) |
| `version` | `"3.9.0"` | OpenSearch version |
| `home` | `OSSS_HOME` | Where binaries and data are stored |
| `progress` | `True` | Show progress bars |

## Environment variables

| Variable | |
| --- | --- |
| `OSSS_HOME` | Data and binaries directory (default `~/.osss`, or `/opt/osss` as root) |
| `OSSS_DOCKER_IMAGE` | Docker image to use instead of the official one |
| `OSSS_DEBUG` | Show full tracebacks from the CLI |
| `AWS_PROFILE`, `AWS_REGION` | Used for S3, Bedrock and Amazon OpenSearch |

## What gets stored for each chunk

| Field | |
| --- | --- |
| `content` | The chunk text (searched) |
| `title` | Document title (searched, boosted) |
| `file_name`, `path`, `folder`, `source`, `file_type` | Where it came from |
| `page`, `record`, `chunk` | Position within the file |
| `parent_id`, `parent_chunk`, `parent_content` | `hierarchical` only: the parent chunk this chunk belongs to. `parent_content` is stored but not searched. |
| `size`, `modified`, `indexed_at` | File metadata |
| `fields.*` | CSV/JSON/Parquet columns. Numeric strings are stored as numbers. |
| `metadata.*` | [Custom metadata](../guide/metadata.md) from sidecar files or `metadata=` |
| `embedding` | The vector (semantic indexes only; for `hierarchical`, the child's vector) |

Each index also stores the settings it was built with, so `idx.add()` and searches use the same options later.
