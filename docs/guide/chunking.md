# Chunking strategies

Before anything is searchable, every document (a file, a PDF page or a CSV row) is split into **chunks**. Each chunk is one search result. How you split decides what a result contains, so osss offers four strategies. They follow the [Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking.html) names, so Bedrock settings carry over.

| `chunking=` | How it splits | A search result is | Good for |
| --- | --- | --- | --- |
| `"fixed"` *(default)* | At paragraph, then sentence boundaries, up to `chunk_size` characters, with overlap | The matching chunk | Most collections |
| `"hierarchical"` | Into large **parents**, then each parent into small **children** | The **parent** of the child that matched | RAG: precise matching, plenty of context |
| `"semantic"` | Where the **topic changes** between sentences (uses an embedding model) | The matching chunk | Documents that cover many topics |
| `"none"` | Doesn't | The whole file, page or row | Short records, tickets, product rows |

```python
cluster.create_index("handbook", "./handbook", chunking="hierarchical")
```

The strategy is fixed when the index is created. To change it, rebuild with `recreate=True`. `idx.add()` always uses the index's own strategy.

## Fixed size

The default. Text is cut at paragraph boundaries first, then lines, sentences and words, into chunks of at most `chunk_size` characters. Each chunk starts with the last `chunk_overlap` characters of the previous one, so a sentence that spans a boundary can still be found.

```python
cluster.create_index("handbook", "./handbook", chunk_size=800, chunk_overlap=120)
```

## Hierarchical

Small chunks match queries precisely, but a 300-character chunk is often too little for a reader, or an LLM, to act on. Large chunks carry context but match vaguely, because their many topics dilute the match. Hierarchical chunking uses both sizes:

1. Each document is split into **parent** chunks of up to `parent_chunk_size` characters.
2. Each parent is split into overlapping **child** chunks of up to `chunk_size` characters. Children never cross parent boundaries.
3. Only the children are searched, by keyword and by vector. Each child stores its parent's text.
4. Search returns the **parent**, once, even when several of its children match.

```python
idx = cluster.create_index(
    "handbook", "s3://bucket/handbook/",
    chunking="hierarchical",
    chunk_size=400,            # children: what gets matched
    chunk_overlap=60,
    parent_chunk_size=3000,    # parents: what you get back
)

res = idx.search("carry over unused leave")
hit = res[0]
hit.content      # the parent chunk: the context to read or send to an LLM
hit.matched      # the child chunk that matched
hit.snippet      # highlighted text from the child
hit.parent_id    # the same for every child of this parent
res.context()    # RAG context built from parents
```

| Option | Default | |
| --- | --- | --- |
| `chunk_size` | `1000` | Child size. `300`–`500` gives the sharpest matches. |
| `chunk_overlap` | `150` | Overlap between children of the same parent |
| `parent_chunk_size` | `4000` | Parent size. Must be larger than `chunk_size`. |

!!! info "How results are counted"
    Keyword search groups children by parent inside OpenSearch, so paging and `res.total` count parents. Semantic and hybrid search fetch extra children and keep the best one per parent, so `res.total` there is the number of parents found among the top matches.

## Semantic

Fixed-size chunks end wherever the size limit falls, so one chunk can end halfway through a new topic. Semantic chunking puts the boundaries where the meaning changes instead:

1. The text is split into sentences (and lines).
2. Each sentence is embedded together with `sentence_buffer` neighbours on each side, which smooths out short or noisy sentences.
3. osss measures the cosine distance between each pair of consecutive sentences.
4. A chunk ends wherever that distance is above the `breakpoint_percentile` of all distances in the document, and also before it would exceed `chunk_size` characters.

```python
idx = cluster.create_index(
    "reports", "./reports",
    chunking="semantic",
    chunk_size=1500,               # upper limit per chunk
    breakpoint_percentile=90,      # lower = more, smaller chunks
    embedding_model="BAAI/bge-small-en-v1.5",
)
```

| Option | Default | |
| --- | --- | --- |
| `chunk_size` | `1000` | Maximum characters per chunk. Text no longer than this stays whole. |
| `breakpoint_percentile` | `95` | Split at the largest 5% of topic shifts. Try `80`–`90` for more, smaller chunks. |
| `sentence_buffer` | `1` | Neighbouring sentences embedded with each sentence (`0` = each sentence alone) |
| `embedding_model` | `all-MiniLM-L6-v2` | The model that measures meaning. Any local or Bedrock model works. |

Semantic chunks don't overlap, so `chunk_overlap` is ignored.

**Vector search isn't required.** Semantic chunking only uses the model while indexing. A keyword-only index (`semantic=False`) built with `chunking="semantic"` doesn't need the k-NN plugin. Add `semantic=True` to also search by meaning. The same model then does both jobs.

!!! warning "Indexing cost"
    Every sentence is embedded once to find the boundaries. With a local model on a CPU, this roughly doubles indexing time. With Bedrock, it adds one embedding request per sentence for Titan; Cohere models embed sentences in batches. If a file's sentences can't be embedded (for example when Bedrock throttles requests), that file is listed in `report.failed` and the rest of the build continues.

## From the app and the terminal

In the app, choose a strategy in **Chunking** in step 02 of [New index](app.md#02-configure). With *Hierarchical*, a **Parent size** slider appears. With *Semantic*, so does the embedding model picker.

```bash
osss index ./handbook --chunking hierarchical --chunk-size 400 --parent-chunk-size 3000
osss index ./reports  --chunking semantic --breakpoint-percentile 90 --model BAAI/bge-small-en-v1.5
```

## Choosing a strategy

- **Not sure?** Keep `fixed`. It's fast, and it works well with `chunk_size` around 500–1,000.
- **Building RAG**, or results feel too short to answer the question: use `hierarchical` with children of 300–500 characters and parents of 2,000–4,000.
- **Long documents that switch topics** (reports, transcripts, meeting notes): use `semantic`.
- **Short records** that are already a good unit: use `none`.

<div class="next" markdown>
[Searching →](searching.md){ .md-button .md-button--primary }
</div>
