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
