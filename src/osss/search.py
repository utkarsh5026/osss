"""Query building and result objects."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

from .embeddings import Embedder

MODES = ("keyword", "semantic", "hybrid")
FilterValue = Union[str, int, float, bool, Sequence[Any], Dict[str, Any]]

_KEYWORD_FIELDS = ["title^3", "content", "file_name.text^2", "path.text"]
_RRF_K = 60


@dataclass
class Hit:
    id: str
    score: float
    title: str
    snippet: str  # HTML-safe, matches wrapped in <mark>
    content: str
    source: str
    path: str
    file_name: str
    file_type: str
    page: Optional[int] = None
    record: Optional[int] = None
    chunk: Optional[int] = None
    fields: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    #: Hierarchical indexes: ``content`` is the parent chunk (the context to use),
    #: ``matched`` the smaller child chunk that matched the query.
    parent_id: Optional[str] = None
    matched: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def location(self) -> str:
        bits = [self.path or self.source]
        if self.page is not None:
            bits.append(f"page {self.page}")
        if self.record is not None:
            bits.append(f"row {self.record + 1}")
        return " · ".join(bits)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "score": self.score, "title": self.title, "content": self.content,
            "source": self.source, "path": self.path, "file_type": self.file_type,
            "page": self.page, "record": self.record, "chunk": self.chunk,
            **({"parent_id": self.parent_id, "matched": self.matched} if self.parent_id else {}),
            **{f"metadata.{k}": v for k, v in self.metadata.items()},
            **{f"fields.{k}": v for k, v in self.fields.items()},
        }


@dataclass
class SearchResults:
    """Search results. Display in a notebook for rich cards; iterate for :class:`Hit`."""

    query: str
    mode: str
    index: str
    hits: List[Hit]
    total: int
    took_ms: int
    offset: int = 0
    facets: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def __iter__(self) -> Iterator[Hit]:
        return iter(self.hits)

    def __len__(self) -> int:
        return len(self.hits)

    def __getitem__(self, i):
        return self.hits[i]

    def __bool__(self) -> bool:
        return bool(self.hits)

    def __repr__(self) -> str:
        lines = [f"<SearchResults {self.mode} {self.query!r} in {self.index}: {len(self.hits)} of {self.total} ({self.took_ms} ms)>"]
        for i, h in enumerate(self.hits[:10], start=1 + self.offset):
            lines.append(f"  {i:>2}. [{h.score:.3f}] {h.title}  — {h.location}")
        return "\n".join(lines)

    def _repr_html_(self) -> str:
        from .ui.render import results_html

        return results_html(self)

    def __rich__(self):
        import re

        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text

        items = [Text.assemble((f"{self.total:,} results", "bold"), f" for “{self.query}” · {self.mode} · {self.took_ms} ms", style="dim")]
        for i, h in enumerate(self.hits, start=1 + self.offset):
            snippet = Text()
            for part in re.split(r"(<mark>.*?</mark>)", h.snippet):
                if part.startswith("<mark>"):
                    snippet.append(html.unescape(part[6:-7]), style="bold black on yellow")
                else:
                    snippet.append(html.unescape(part))
            head = Text.assemble((f"{i}. ", "dim"), (h.title, "bold cyan"), (f"  {h.score:.3f}", "dim"))
            items.append(Panel(Group(head, Text(h.location, style="green"), snippet), border_style="grey37", padding=(0, 1)))
        return Group(*items)

    def to_list(self) -> List[Dict[str, Any]]:
        return [h.to_dict() for h in self.hits]

    def to_pandas(self):
        import pandas as pd

        return pd.DataFrame(self.to_list())

    def context(self, max_chars: int = 12000) -> str:
        """Concatenate hit texts with citations — handy as RAG context for an LLM."""
        out, used = [], 0
        for i, h in enumerate(self.hits, start=1):
            block = f"[{i}] {h.title} ({h.location})\n{h.content}\n"
            if used + len(block) > max_chars:
                break
            out.append(block)
            used += len(block)
        return "\n".join(out)


# ---------------------------------------------------------------- query parts
def build_filters(filters: Optional[Dict[str, FilterValue]]) -> List[Dict[str, Any]]:
    """``{"file_type": ["pdf", "md"], "fields.year": {"gte": 2020}}`` → DSL clauses.

    String values on dynamic fields (``fields.*`` and ``metadata.*``) match the
    exact value via their ``.keyword`` sub-field. On a list-valued attribute a
    value matches when the list contains it.
    """
    out: List[Dict[str, Any]] = []
    for key, value in (filters or {}).items():
        if value is None or value == [] or value == "":
            continue
        if isinstance(value, dict):
            out.append({"range": {key: value}})
            continue
        values = list(value) if isinstance(value, (list, tuple, set)) else [value]
        field_name = key
        if (key.startswith(("fields.", "metadata.")) and not key.endswith(".keyword")
                and all(isinstance(v, str) for v in values)):
            field_name = key + ".keyword"
        out.append({"terms": {field_name: values}})
    return out


def _keyword_query(query: str, operator: str, fuzzy: bool) -> Dict[str, Any]:
    if not query.strip() or query.strip() == "*":
        return {"match_all": {}}
    should: List[Dict[str, Any]] = [
        {"simple_query_string": {
            "query": query, "fields": _KEYWORD_FIELDS, "default_operator": operator,
            "lenient": True, "boost": 2.0,
        }},
        {"match_phrase": {"content": {"query": query, "slop": 2, "boost": 1.5}}},
    ]
    if fuzzy:
        should.append({"match": {"content": {"query": query, "fuzziness": "AUTO", "prefix_length": 1, "boost": 0.5}}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def _highlight(query: str) -> Dict[str, Any]:
    hl: Dict[str, Any] = {
        "encoder": "html",
        "pre_tags": ["<mark>"],
        "post_tags": ["</mark>"],
        "fields": {
            "content": {"fragment_size": 240, "number_of_fragments": 2, "no_match_size": 280},
            "title": {"number_of_fragments": 0},
        },
    }
    if query.strip() and query.strip() != "*":
        hl["highlight_query"] = {"match": {"content": {"query": query}}}
    return hl


def _to_hit(h: Dict[str, Any], score: Optional[float] = None) -> Hit:
    s = h.get("_source", {})
    hl = h.get("highlight", {})
    content = s.get("content", "")
    parent = s.get("parent_content")
    if hl.get("content"):
        snippet = " … ".join(hl["content"])
    else:
        snippet = html.escape(content[:280]) + ("…" if len(content) > 280 else "")
    title = s.get("title") or s.get("file_name") or h.get("_id")
    return Hit(
        id=h.get("_id"), score=float(score if score is not None else (h.get("_score") or 0.0)),
        title=str(title), snippet=snippet, content=parent or content, source=s.get("source", ""),
        path=s.get("path", ""), file_name=s.get("file_name", ""), file_type=s.get("file_type", ""),
        page=s.get("page"), record=s.get("record"), chunk=s.get("chunk"), fields=s.get("fields") or {},
        metadata=s.get("metadata") or {}, parent_id=s.get("parent_id"),
        matched=content if parent else "", raw=h,
    )


def _facet_aggs() -> Dict[str, Any]:
    return {"file_type": {"terms": {"field": "file_type", "size": 30}}}


def _read_facets(resp: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    aggs = resp.get("aggregations") or {}
    return {name: {b["key"]: b["doc_count"] for b in agg["buckets"]} for name, agg in aggs.items() if "buckets" in agg}


def run_search(
    client,
    index: str,
    query: str,
    *,
    mode: str = "keyword",
    k: int = 10,
    offset: int = 0,
    filters: Optional[Dict[str, FilterValue]] = None,
    embedder: Optional[Embedder] = None,
    operator: str = "or",
    fuzzy: bool = False,
    facets: bool = False,
    group_by: Optional[str] = None,
) -> SearchResults:
    """Run a keyword, semantic or hybrid search.

    ``group_by`` (e.g. ``"parent_id"`` for hierarchical indexes) returns only the
    best-ranked chunk of each group, so one parent shows up once.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode != "keyword" and embedder is None:
        raise ValueError(f"'{mode}' search needs an index built with semantic=True")
    flt = build_filters(filters)
    base = {"_source": {"excludes": ["embedding"]}, "highlight": _highlight(query), "track_total_hits": True}

    def keyword(size: int, frm: int) -> Dict[str, Any]:
        q = _keyword_query(query, operator, fuzzy)
        if flt:
            q = {"bool": {"must": [q], "filter": flt}}
        body = {**base, "query": q, "size": size, "from": frm}
        if facets:
            body["aggs"] = _facet_aggs()
        if group_by and size:
            body["collapse"] = {"field": group_by}
            body.setdefault("aggs", {})["_groups"] = {"cardinality": {"field": group_by}}
        return client.search(index=index, body=body)

    def group_key(h: Dict[str, Any]) -> str:
        if group_by:
            v = h.get("_source", {}).get(group_by)
            if v is not None:
                return str(v)
        return h["_id"]

    def dedupe(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set = set()
        out = []
        for h in hits:
            g = group_key(h)
            if g not in seen:
                seen.add(g)
                out.append(h)
        return out

    def semantic(size: int) -> Dict[str, Any]:
        vec = embedder.embed_query(query)  # type: ignore[union-attr]
        knn: Dict[str, Any] = {"vector": vec, "k": size}
        if flt:
            knn["filter"] = {"bool": {"filter": flt}}
        body = {**base, "query": {"knn": {"embedding": knn}}, "size": size}
        if facets:
            body["aggs"] = _facet_aggs()
        return client.search(index=index, body=body)

    if mode == "keyword" and not query.strip() and not flt:
        # Browsing: one chunk per file so the listing shows the variety of the index.
        body = {
            "_source": {"excludes": ["embedding"]}, "query": {"bool": {"filter": flt}} if flt else {"match_all": {}},
            "collapse": {"field": "source"}, "sort": [{"path": "asc"}, {"chunk": "asc"}],
            "size": k, "from": offset, "aggs": {"files": {"cardinality": {"field": "source"}}},
        }
        if facets:
            body["aggs"].update(_facet_aggs())
        r = client.search(index=index, body=body)
        hits = [_to_hit(h, score=0.0) for h in r["hits"]["hits"]]
        total = int(r["aggregations"]["files"]["value"])
        facets_out = {n: v for n, v in _read_facets(r).items() if n != "files"}
        return SearchResults(query, mode, index, hits, total, r.get("took", 0), offset, facets_out)

    if mode == "keyword":
        r = keyword(k, offset)
        hits = [_to_hit(h) for h in r["hits"]["hits"]]
        total = r["hits"]["total"]["value"]
        if group_by:
            total = int(((r.get("aggregations") or {}).get("_groups") or {}).get("value", total))
        return SearchResults(query, mode, index, hits, total, r.get("took", 0), offset, _read_facets(r))

    # several children of one parent can match, so fetch extra before grouping
    widen = 3 if group_by else 1

    if mode == "semantic":
        r = semantic((offset + k) * widen)
        found = dedupe(r["hits"]["hits"])
        hits = [_to_hit(h) for h in found[offset:offset + k]]
        total = min(len(found), offset + k) if group_by else min(r["hits"]["total"]["value"], offset + k)
        return SearchResults(query, mode, index, hits, total, r.get("took", 0), offset, _read_facets(r))

    # hybrid: reciprocal rank fusion of BM25 and k-NN results (per group, if grouping)
    depth = max(50, (offset + k) * 3)
    rk, rs = keyword(depth, 0), semantic(depth * widen)
    fused: Dict[str, float] = {}
    docs: Dict[str, Dict[str, Any]] = {}
    for resp in (rk, rs):
        for rank, h in enumerate(dedupe(resp["hits"]["hits"]), start=1):
            g = group_key(h)
            fused[g] = fused.get(g, 0.0) + 1.0 / (_RRF_K + rank)
            prev = docs.get(g)
            if prev is None or (h.get("highlight") and not prev.get("highlight")):
                docs[g] = h
    order = sorted(fused, key=fused.get, reverse=True)  # type: ignore[arg-type]
    hits = [_to_hit(docs[i], fused[i]) for i in order[offset:offset + k]]
    return SearchResults(
        query, mode, index, hits, len(order), rk.get("took", 0) + rs.get("took", 0), offset,
        _read_facets(rk),
    )
