"""End-to-end tests against a real OpenSearch.

Run with an existing cluster:      OSSS_TEST_URL=http://127.0.0.1:9200 pytest -m integration
Or let osss start one locally:     OSSS_TEST_LOCAL=1 pytest -m integration
"""

import hashlib
import json
import math
import os
import uuid

import pytest

import osss

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cluster():
    url = os.environ.get("OSSS_TEST_URL")
    if url:
        return osss.connect(url)
    if os.environ.get("OSSS_TEST_LOCAL"):
        return osss.start(progress=False)
    pytest.skip("set OSSS_TEST_URL or OSSS_TEST_LOCAL=1")


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "refunds.md").write_text("# Refund policy\nCustomers get a full refund within 30 days.")
    (tmp_path / "vacation.txt").write_text("Employees receive 25 days of paid vacation per year.")
    (tmp_path / "products.csv").write_text("sku,name,category\n1,Tent,camping\n2,Jacket,apparel\n")
    (tmp_path / "tickets.jsonl").write_text("\n".join(json.dumps({"subject": s}) for s in ["login broken", "invoice wrong"]))
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    return tmp_path


@pytest.fixture
def name(cluster):
    n = f"osss-test-{uuid.uuid4().hex[:8]}"
    yield n
    if cluster.exists(n):
        cluster.delete_index(n)


def toy_embedder():
    def embed(texts):
        out = []
        for t in texts:
            v = [0.0] * 32
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 32] += 1
            n = math.sqrt(sum(x * x for x in v)) or 1
            out.append([x / n for x in v])
        return out

    return osss.FunctionEmbedder(embed, name="toy-32")


def test_build_search_add(cluster, corpus, name):
    idx = cluster.create_index(name, corpus, progress=False)
    r = idx.last_report
    assert r.files_indexed == 4 and r.ok and len(r.skipped) == 1
    hits = idx.search("refund 30 days")
    assert hits[0].path == "policies/refunds.md" and "<mark>" in hits[0].snippet
    assert [h.title for h in idx.search("tent", filters={"fields.category": "camping"})] == ["Tent"]
    assert idx.search("vacation", file_type="csv").total == 0
    assert idx.stats()["files"] == 4

    # editing a file and re-adding replaces its chunks instead of duplicating them
    before = idx.count()
    (corpus / "vacation.txt").write_text("Employees now receive 30 days of vacation.")
    idx.add(corpus, progress=False)
    assert idx.count() == before
    assert "30 days" in idx.search("vacation")[0].content

    with pytest.raises(osss.OsssError):
        cluster.create_index(name, corpus, progress=False)
    cluster.create_index(name, corpus, recreate=True, include=["*.md"], progress=False)
    assert cluster.index(name).stats()["files"] == 1


def test_semantic_and_hybrid(cluster, corpus, name):
    if not cluster.has_knn() and cluster.server is None:
        pytest.skip("cluster has no k-NN plugin")
    idx = cluster.create_index(name, corpus, embedder=toy_embedder(), progress=False)
    assert idx.semantic
    assert idx.search("refund within 30 days", mode="semantic", k=1)[0].path == "policies/refunds.md"
    assert len(idx.search("refund", mode="hybrid", k=3)) == 3


def test_metadata_sidecars_and_filters(cluster, corpus, name):
    (corpus / "policies" / "refunds.md.metadata.json").write_text(json.dumps({"metadataAttributes": {
        "department": "finance",
        "year": {"value": {"type": "NUMBER", "numberValue": 2024}},
        "tags": ["customers", "money"],
        "public": True,
    }}))
    (corpus / "vacation.txt.metadata.json").write_text('{"metadataAttributes": {"department": "hr", "year": 2022}}')
    idx = cluster.create_index(name, corpus, metadata=lambda f: {"top": f.folder or "root"}, progress=False)
    assert idx.last_report.files_indexed == 4  # sidecars aren't documents

    [hit] = idx.search("refund", metadata={"department": "finance"})
    assert hit.metadata == {"department": "finance", "year": 2024, "tags": ["customers", "money"],
                            "public": True, "top": "policies"}
    assert [h.path for h in idx.search("", metadata={"year": {"gte": 2023}})] == ["policies/refunds.md"]
    assert [h.path for h in idx.search("", metadata={"tags": "money", "public": True})] == ["policies/refunds.md"]
    assert {h.path for h in idx.search("", metadata={"department": ["hr", "finance"]})} == {"policies/refunds.md", "vacation.txt"}
    assert idx.search("refund", metadata={"department": "hr"}).total == 0
    assert idx.search("tent", metadata={"top": "root"}).total == 1  # CSV rows get file metadata too

    # editing a sidecar and re-adding the file updates its chunks
    (corpus / "vacation.txt.metadata.json").write_text('{"metadataAttributes": {"department": "people"}}')
    idx.add(corpus / "vacation.txt", progress=False)
    assert idx.search("vacation")[0].metadata == {"department": "people"}

    if cluster.has_knn() or cluster.server is not None:
        sem = cluster.create_index(name + "-sem", corpus, embedder=toy_embedder(), progress=False)
        try:
            for mode in ("semantic", "hybrid"):
                res = sem.search("days", mode=mode, metadata={"department": "people"})
                assert [h.path for h in res] == ["vacation.txt"]
        finally:
            cluster.delete_index(sem.name)


TOPICS = (
    " ".join(f"Cats purr and nap in the sunny window, cat {i} said." for i in range(10))
    + "\n\n"
    + " ".join(f"Money in the bank earns interest every month, account {i} said." for i in range(10))
)


def test_hierarchical_chunking(cluster, tmp_path, name):
    (tmp_path / "long.txt").write_text(TOPICS)
    (tmp_path / "short.md").write_text("# Short\nA cat note.")
    idx = cluster.create_index(name, tmp_path, chunking="hierarchical", chunk_size=150, chunk_overlap=0,
                               parent_chunk_size=600, progress=False)
    assert idx.chunking == "hierarchical" and idx.stats()["chunking"] == "hierarchical"
    assert idx.count() > 4  # children are what gets stored

    res = idx.search("cat", k=20)
    parents = [h.parent_id for h in res]
    assert len(parents) == len(set(parents)) == res.total  # each parent once, total counts parents
    long_hit = next(h for h in res if h.path == "long.txt")
    assert len(long_hit.content) > len(long_hit.matched) and long_hit.matched in long_hit.content
    assert "<mark>" in long_hit.snippet
    # the parent text is stored, not searched: words only in the parent don't match its children
    child_only = idx.search('"account 9 said"', k=5)
    assert child_only.total == 1 and "account 9" in child_only[0].matched

    with pytest.raises(osss.OsssError):
        idx.add(tmp_path, chunking="fixed", progress=False)
    before = idx.count()
    idx.add(tmp_path, progress=False)
    assert idx.count() == before  # re-adding replaces children

    if cluster.has_knn() or cluster.server is not None:
        sem = cluster.create_index(name + "-sem", tmp_path, chunking="hierarchical", chunk_size=150, chunk_overlap=0,
                                   parent_chunk_size=600, embedder=toy_embedder(), progress=False)
        try:
            for mode in ("semantic", "hybrid"):
                res = sem.search("cats purr in the window", mode=mode, k=10)
                ids = [h.parent_id for h in res]
                assert ids and len(ids) == len(set(ids)) and all(h.matched in h.content for h in res)
        finally:
            cluster.delete_index(sem.name)


def test_semantic_chunking_keyword_index(cluster, tmp_path, name):
    (tmp_path / "long.txt").write_text(TOPICS)
    idx = cluster.create_index(name, tmp_path, chunking="semantic", chunk_size=700, breakpoint_percentile=90,
                               embedder=toy_embedder(), semantic=False, progress=False)
    assert not idx.semantic  # boundaries came from the model, but no vectors were stored
    assert idx.last_report.ok and idx.last_report.chunks >= 2
    chunks = [h.content for h in idx.search("said", k=20)]
    assert all(len(c) <= 700 for c in chunks)
    assert any("Cats" in c and "Money" not in c for c in chunks)
    assert any("Money" in c and "Cats" not in c for c in chunks)
    before = idx.count()
    idx.add(tmp_path, progress=False)
    assert idx.count() == before
