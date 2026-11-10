"""Hierarchical and semantic chunking (no OpenSearch needed)."""

from datetime import datetime, timezone

import pytest

from osss.api import Index, OsssError
from osss.chunking import (
    STRATEGIES, chunk_document, hierarchical_chunks, normalize_strategy, semantic_chunks, split_sentences,
)
from osss.config import IndexConfig
from osss.indexer import _make_actions, build_index_body
from osss.loaders import Document
from osss.search import run_search
from osss.sources import LocalSource, SourceFile

CATS = [f"Cats purr and nap in the sun, cat number {i} said." for i in range(12)]
MONEY = [f"Money in the bank earns interest, account number {i} said." for i in range(12)]
TWO_TOPICS = " ".join(CATS + MONEY)


class TopicEmbedder:
    """Tiny deterministic 'model': one dimension per topic word."""

    name, dimension = "topics", 3

    def __init__(self):
        self.calls = 0

    def embed_documents(self, texts):
        self.calls += 1
        return [[t.lower().count("cat"), t.lower().count("money"), 0.1] for t in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


def sf(name: str, data: bytes = b"") -> SourceFile:
    return SourceFile(uri=f"/x/{name}", rel_path=name, size=len(data), modified=datetime.now(timezone.utc), _reader=lambda: data)


# ------------------------------------------------------------------ config
def test_strategy_names_and_validation():
    assert set(STRATEGIES) == {"fixed", "hierarchical", "semantic", "none"}
    assert normalize_strategy("FIXED_SIZE") == "fixed"
    assert normalize_strategy("Hierarchical") == "hierarchical"
    assert IndexConfig(name="t", chunking="SEMANTIC").chunking == "semantic"
    assert IndexConfig(name="t").chunking == "fixed"
    with pytest.raises(ValueError):
        IndexConfig(name="t", chunking="paragraphs")
    with pytest.raises(ValueError):
        IndexConfig(name="t", chunking="hierarchical", chunk_size=1000, parent_chunk_size=800)
    with pytest.raises(ValueError):
        IndexConfig(name="t", chunking="hierarchical", chunk_size=0)
    with pytest.raises(ValueError):
        IndexConfig(name="t", chunking="semantic", chunk_size=0)
    with pytest.raises(ValueError):
        IndexConfig(name="t", breakpoint_percentile=100)
    # configs saved by older versions (no chunking key) still load as fixed
    old = {k: v for k, v in IndexConfig(name="t").to_dict().items() if k not in ("chunking", "parent_chunk_size")}
    assert IndexConfig.from_dict(old).chunking == "fixed"


# ------------------------------------------------------------------ hierarchical
def test_hierarchical_children_stay_inside_parents():
    text = "\n\n".join(" ".join(f"Paragraph {p} sentence {s} is here." for s in range(12)) for p in range(10))
    chunks = hierarchical_chunks(text, parent_size=1200, child_size=300, overlap=50)
    parents = {c.parent: c.parent_text for c in chunks}
    assert len(parents) > 2 and len(chunks) > len(parents)
    assert all(len(p) <= 1200 for p in parents.values())
    assert all(len(c.text) <= 300 and c.text in c.parent_text for c in chunks)
    assert [c.parent for c in chunks] == sorted(c.parent for c in chunks)
    assert "Paragraph 9 sentence 11" in chunks[-1].text  # nothing lost


def test_hierarchical_actions_carry_parent():
    cfg = IndexConfig(name="t", chunking="hierarchical", chunk_size=300, chunk_overlap=0, parent_chunk_size=1200)
    doc = Document(text=TWO_TOPICS, title="T")
    acts = _make_actions("t", sf("a.md"), [doc], cfg)
    again = _make_actions("t", sf("a.md"), [doc], cfg)
    assert [a["_id"] for a in acts] == [a["_id"] for a in again]  # stable ids
    assert len({a["_id"] for a in acts}) == len(acts)
    srcs = [a["_source"] for a in acts]
    assert all(s["content"] in s["parent_content"] for s in srcs)
    by_parent = {}
    for s in srcs:
        by_parent.setdefault(s["parent_id"], set()).add(s["parent_content"])
    assert len(by_parent) > 1 and all(len(v) == 1 for v in by_parent.values())
    assert [s["chunk"] for s in srcs] == list(range(len(srcs)))
    # fixed chunking writes no parent fields
    assert "parent_id" not in _make_actions("t", sf("a.md"), [doc], IndexConfig(name="t", chunk_size=300, chunk_overlap=0))[0]["_source"]


def test_index_body_maps_parent_fields():
    props = build_index_body(IndexConfig(name="t", chunking="hierarchical", chunk_size=300))["mappings"]["properties"]
    assert props["parent_id"]["type"] == "keyword"
    assert props["parent_content"]["index"] is False  # stored for results, never matched


# ------------------------------------------------------------------ semantic
def test_split_sentences_round_trip():
    text = "First one. Second one!  Third?\nA line without a stop\n\nNext para “quoted.” End"
    parts = split_sentences(text)
    assert "".join(parts) == text
    assert parts[0] == "First one. " and parts[-1] == "End"
    assert split_sentences("") == []


def test_semantic_chunks_split_at_topic_change():
    emb = TopicEmbedder()
    chunks = semantic_chunks(TWO_TOPICS, emb.embed_documents, max_size=1000, breakpoint_percentile=90, buffer=0)
    assert len(chunks) == 2
    assert "cat" in chunks[0].lower() and "money" not in chunks[0].lower()
    assert "money" in chunks[1].lower() and "cat" not in chunks[1].lower()
    assert emb.calls == 1  # all sentences embedded in one batch


def test_semantic_chunks_respect_max_size_and_short_text():
    emb = TopicEmbedder()
    chunks = semantic_chunks(TWO_TOPICS, emb.embed_documents, max_size=300, buffer=1)
    assert len(chunks) > 2 and all(len(c) <= 300 for c in chunks)
    assert not any("cat" in c.lower() and "money" in c.lower() for c in chunks)
    # short documents stay whole and cost no embedding calls
    emb2 = TopicEmbedder()
    assert semantic_chunks("Cats purr. Money talks.", emb2.embed_documents, max_size=1000) == ["Cats purr. Money talks."]
    assert emb2.calls == 0
    # one huge "sentence" is still split to fit
    assert all(len(c) <= 100 for c in semantic_chunks("word " * 200, emb.embed_documents, max_size=100))


def test_chunk_document_dispatch():
    emb = TopicEmbedder()
    sem = IndexConfig(name="t", chunking="semantic", chunk_size=1000, breakpoint_percentile=90, sentence_buffer=0)
    assert len(chunk_document(TWO_TOPICS, sem, emb.embed_documents)) == 2
    with pytest.raises(ValueError):
        chunk_document(TWO_TOPICS, sem)  # needs a model
    assert [c.text for c in chunk_document(" x " * 2000, IndexConfig(name="t", chunking="none"))] == [("x  " * 2000).strip()]


def test_ingest_semantic_chunking_without_vectors(tmp_path, monkeypatch):
    from opensearchpy import helpers

    from osss.indexer import ingest

    (tmp_path / "a.txt").write_text(TWO_TOPICS)
    written = []
    monkeypatch.setattr(helpers, "bulk", lambda client, actions, **kw: (written.extend(actions) or (len(actions), [])))

    class C:
        class indices:
            put_settings = refresh = staticmethod(lambda **kw: None)

    emb = TopicEmbedder()
    cfg = IndexConfig(name="t", chunking="semantic", chunk_size=1000, breakpoint_percentile=90, sentence_buffer=0)
    report = ingest(C(), cfg, LocalSource(tmp_path), embedder=emb, progress=False)
    assert report.ok and report.chunks == 2
    assert all("embedding" not in a["_source"] for a in written)  # keyword index: no vectors stored

    written.clear()
    report = ingest(C(), cfg.replace(semantic=True), LocalSource(tmp_path), embedder=emb, progress=False)
    assert report.chunks == 2 and all(len(a["_source"]["embedding"]) == 3 for a in written)


def test_ingest_reports_chunking_failures(tmp_path, monkeypatch):
    from opensearchpy import helpers

    from osss.indexer import ingest

    (tmp_path / "a.txt").write_text(TWO_TOPICS)
    monkeypatch.setattr(helpers, "bulk", lambda client, actions, **kw: (len(actions), []))

    class Broken(TopicEmbedder):
        def embed_documents(self, texts):
            raise RuntimeError("throttled")

    class C:
        class indices:
            put_settings = refresh = staticmethod(lambda **kw: None)

    cfg = IndexConfig(name="t", chunking="semantic", chunk_size=500)
    report = ingest(C(), cfg, LocalSource(tmp_path), embedder=Broken(), progress=False)
    assert report.files_indexed == 0 and "throttled" in report.failed[0][1]


# ------------------------------------------------------------------ search over hierarchical indexes
class FakeClient:
    def __init__(self, hits, groups=None):
        self.hits, self.groups, self.bodies = hits, groups, []

    def search(self, index, body):
        self.bodies.append(body)
        r = {"took": 1, "hits": {"total": {"value": len(self.hits)}, "hits": self.hits}}
        if self.groups is not None:
            r["aggregations"] = {"_groups": {"value": self.groups}}
        return r


def _child(i, parent):
    return {"_id": f"c{i}", "_score": 1.0 / (i + 1), "_source": {
        "content": f"child {i}", "parent_id": parent, "parent_content": f"parent {parent} text", "title": "T", "path": "p",
    }}


def test_keyword_search_collapses_on_parent():
    c = FakeClient([_child(0, "A"), _child(2, "B")], groups=2)
    r = run_search(c, "i", "q", mode="keyword", group_by="parent_id")
    body = c.bodies[0]
    assert body["collapse"] == {"field": "parent_id"}
    assert r.total == 2 and r.facets == {}
    assert r[0].content == "parent A text" and r[0].matched == "child 0" and r[0].parent_id == "A"
    assert r.to_list()[0]["parent_id"] == "A"
    assert "parent A text" in r.context()


def test_semantic_and_hybrid_return_each_parent_once():
    hits = [_child(0, "A"), _child(1, "A"), _child(2, "B"), _child(3, "A"), _child(4, "C")]
    emb = TopicEmbedder()
    r = run_search(FakeClient(hits), "i", "q", mode="semantic", k=10, embedder=emb, group_by="parent_id")
    assert [h.parent_id for h in r] == ["A", "B", "C"] and r[0].matched == "child 0"
    r = run_search(FakeClient(hits), "i", "q", mode="hybrid", k=10, embedder=emb, group_by="parent_id")
    assert sorted(h.parent_id for h in r) == ["A", "B", "C"] and r.total == 3
    # without grouping every child is its own result
    assert len(run_search(FakeClient(hits), "i", "q", mode="semantic", k=10, embedder=emb)) == 5


class FakeCluster:
    def __init__(self, client):
        self.client = client


def _index(cfg, client=None, vectors=False):
    idx = Index(FakeCluster(client), cfg.name)
    idx._meta = {"config": cfg.to_dict(), "_has_vectors": vectors}
    return idx


def test_index_search_groups_hierarchical_and_guards_chunking():
    c = FakeClient([_child(0, "A")], groups=1)
    idx = _index(IndexConfig(name="h", chunking="hierarchical", chunk_size=300), c)
    assert idx.chunking == "hierarchical"
    idx.search("q")
    assert c.bodies[0]["collapse"] == {"field": "parent_id"}
    with pytest.raises(OsssError):
        idx.add("/nowhere", chunking="fixed")

    c2 = FakeClient([_child(0, "A")])
    plain = _index(IndexConfig(name="f"), c2)
    plain.search("q")
    assert "collapse" not in c2.bodies[0]
    # semantic chunking alone doesn't make an index searchable by vectors
    sem_chunked = _index(IndexConfig(name="s", chunking="semantic"), FakeClient([]))
    sem_chunked.embedder = TopicEmbedder()
    with pytest.raises(ValueError):
        sem_chunked.search("q", mode="semantic")


def test_cli_chunking_flags():
    from osss.cli import build_parser

    a = build_parser().parse_args(["index", "./docs", "--chunking", "hierarchical", "--chunk-size", "400",
                                   "--parent-chunk-size", "3000"])
    assert a.chunking == "hierarchical" and a.parent_chunk_size == 3000 and a.chunk_size == 400
