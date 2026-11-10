"""Fast tests that need no OpenSearch."""

import io
import json
from datetime import datetime, timezone

import pytest

from osss._utils import sanitize_index_name, stable_id
from osss.chunking import chunk_text
from osss.config import IndexConfig
from osss.indexer import _make_actions, build_index_body
from osss.loaders import UnsupportedFile, load
from osss.search import build_filters, run_search
from osss.sources import LocalSource, S3Source, SourceFile, keep, resolve_source


def sf(name: str, data: bytes) -> SourceFile:
    return SourceFile(uri=f"/x/{name}", rel_path=name, size=len(data), modified=datetime.now(timezone.utc), _reader=lambda: data)


CFG = IndexConfig(name="t")


# ------------------------------------------------------------------ utils / config
def test_sanitize_index_name():
    assert sanitize_index_name("My Reports 2024") == "my-reports-2024"
    assert sanitize_index_name("s3://bucket/x") == "s3-bucket-x"
    assert sanitize_index_name("__x") == "x"
    assert sanitize_index_name("") == "my-index"


def test_config_validation():
    with pytest.raises(ValueError):
        IndexConfig(name="Bad Name")
    with pytest.raises(ValueError):
        IndexConfig(name="ok", chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        IndexConfig(name="ok", analyzer="klingon")
    c = IndexConfig(name="ok", file_types=[".PDF"], include="*.md", embedding_model="amazon.titan-embed-text-v2:0")
    assert c.file_types == ["pdf"] and c.include == ["*.md"] and c.embedding_provider == "bedrock"
    assert IndexConfig.from_dict({**c.to_dict(), "unknown": 1}).name == "ok"


def test_stable_id_is_deterministic():
    assert stable_id("a", 1, None) == stable_id("a", 1, None)
    assert stable_id("a", 1) != stable_id("a", 2)


# ------------------------------------------------------------------ chunking
def test_chunking_respects_size_and_overlap():
    text = " ".join(f"Sentence number {i} is here." for i in range(400))
    chunks = chunk_text(text, 500, 100)
    assert len(chunks) > 5
    assert all(len(c) <= 500 for c in chunks)
    # overlap: the start of each chunk appears at the end of the previous one
    assert chunks[1][:20] in chunks[0]
    # nothing lost
    assert "Sentence number 399" in chunks[-1]


def test_chunking_small_and_disabled():
    assert chunk_text("short", 1000, 100) == ["short"]
    assert chunk_text("x" * 5000, 0, 0) == ["x" * 5000]
    assert chunk_text("   ", 100, 10) == []
    assert all(len(c) <= 300 for c in chunk_text("a" * 1000, 300, 0))


# ------------------------------------------------------------------ loaders
def test_markdown_title_and_front_matter():
    md = b"---\ntitle: Refunds\n---\n# Heading\nBody text"
    [d] = load(sf("r.md", md), CFG)
    assert d.title == "Refunds" and "title:" not in d.text and "Body text" in d.text


def test_html_strips_scripts():
    html = b"<html><head><title>T</title><script>evil()</script></head><body><p>Hello &amp; bye</p></body></html>"
    [d] = load(sf("a.html", html), CFG)
    assert d.title == "T" and "evil" not in d.text and "Hello & bye" in d.text


def test_csv_records_and_fields():
    data = b"id,name,notes\n1,Tent,Very light\n2,Lamp,Bright\n"
    cfg = IndexConfig(name="t", id_field="id", text_fields=["notes"], title_field="name")
    docs = load(sf("p.csv", data), cfg)
    assert [d.title for d in docs] == ["Tent", "Lamp"]
    assert docs[0].text == "Very light" and docs[0].fields["id"] == "1" and docs[0].doc_key == "1"


def test_json_list_wrapped_in_dict_and_jsonl():
    data = json.dumps({"items": [{"title": "A", "x": 1}, {"title": "B", "x": 2}]}).encode()
    assert [d.title for d in load(sf("a.json", data), CFG)] == ["A", "B"]
    jl = b'{"q": "one"}\nnot json\n{"q": "two"}\n'
    assert len(load(sf("a.jsonl", jl), CFG)) == 2


def test_ipynb_and_docx():
    nb = {"cells": [{"cell_type": "markdown", "source": ["# Churn\n", "text"]}, {"cell_type": "code", "source": "x = 1"}]}
    [d] = load(sf("n.ipynb", json.dumps(nb).encode()), CFG)
    assert d.title == "Churn" and "x = 1" in d.text
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_heading("Policy", 1)
    doc.add_paragraph("Use 2FA.")
    buf = io.BytesIO()
    doc.save(buf)
    [d] = load(sf("s.docx", buf.getvalue()), CFG)
    assert d.title == "Policy" and "Use 2FA." in d.text


def test_parquet():
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(pa.table({"title": ["x", "y"], "n": [1, 2]}), buf)
    docs = load(sf("d.parquet", buf.getvalue()), CFG)
    assert [d.fields["n"] for d in docs] == [1, 2]


def test_binary_and_unknown():
    with pytest.raises(UnsupportedFile):
        load(sf("img.png", b"\x89PNG\x00\x00"), CFG)
    [d] = load(sf("LICENSE", b"MIT License text"), CFG)
    assert "MIT" in d.text


# ------------------------------------------------------------------ sources
def test_local_source_excludes(tmp_path):
    (tmp_path / "a.md").write_text("a")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / "node_modules" / "p").mkdir(parents=True)
    (tmp_path / "node_modules" / "p" / "i.js").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.pdf").write_bytes(b"x")
    files = list(LocalSource(tmp_path).iter_files(exclude=IndexConfig(name="t").exclude))
    assert sorted(f.rel_path for f in files) == ["a.md", "sub/b.pdf"]
    only_pdf = list(LocalSource(tmp_path).iter_files(include=["*.pdf"]))
    assert [f.rel_path for f in only_pdf] == ["sub/b.pdf"]


def test_keep_patterns():
    assert keep("docs/a.md", ["docs/**"])
    assert not keep("other/a.md", ["docs/**"])
    assert not keep("x/.hidden", (), ["*/.*"])


def test_resolve_source(tmp_path):
    assert isinstance(resolve_source(str(tmp_path)), LocalSource)
    assert isinstance(resolve_source("s3://bucket/prefix/"), S3Source)
    with pytest.raises(FileNotFoundError):
        resolve_source(str(tmp_path / "missing"))


def test_s3_source_with_moto():
    moto = pytest.importorskip("moto")
    import boto3

    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="osss-bucket")
        s3.put_object(Bucket="osss-bucket", Key="docs/a.md", Body=b"# A\nhello")
        s3.put_object(Bucket="osss-bucket", Key="docs/sub/b.txt", Body=b"world")
        s3.put_object(Bucket="osss-bucket", Key="docs/sub/", Body=b"")
        s3.put_object(Bucket="osss-bucket", Key="other/c.txt", Body=b"nope")
        src = S3Source("s3://osss-bucket/docs", client=s3)
        files = list(src.iter_files())
        assert sorted(f.rel_path for f in files) == ["a.md", "sub/b.txt"]
        assert files[0].read().startswith(b"# A")
        single = list(S3Source("s3://osss-bucket/docs/a.md", client=s3).iter_files())
        assert [f.rel_path for f in single] == ["a.md"]
        assert src.scan().by_type == {"md": 1, "txt": 1}


def test_browse_local(tmp_path):
    from osss.sources import browse

    for d in ("beta/inner", "Alpha", ".git"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "b.md").write_text("bb")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / ".env").write_text("x")
    (tmp_path / "beta" / "inner" / "deep.md").write_text("x")

    ls = browse(str(tmp_path))
    assert ls.location == str(tmp_path.resolve())
    assert [f.name for f in ls.folders] == ["Alpha", "beta"]  # not recursive, hidden skipped, case-insensitive
    assert [(f.name, f.size) for f in ls.files] == [("a.txt", 1), ("b.md", 2)]
    assert ls.parent == str(tmp_path.resolve().parent)
    assert ls.crumbs[-1] == (tmp_path.name, str(tmp_path.resolve()))
    assert not ls.is_s3 and not ls.truncated

    assert [f.name for f in browse(str(tmp_path), show_hidden=True).folders] == [".git", "Alpha", "beta"]
    inner = browse(ls.folders[1].location)
    assert [f.name for f in inner.folders] == ["inner"] and inner.parent == ls.location
    # a file or a path that doesn't exist (yet) opens the nearest folder
    assert browse(str(tmp_path / "b.md")).location == ls.location
    assert browse(str(tmp_path / "missing" / "deeper")).location == ls.location
    assert browse(str(tmp_path), limit=2).truncated


def test_browse_s3_with_moto():
    moto = pytest.importorskip("moto")
    import boto3

    from osss.sources import browse

    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        for b in ("zeta-bucket", "alpha-bucket"):
            s3.create_bucket(Bucket=b)
        for key in ("docs/a.md", "docs/sub/b.txt", "docs/sub/", "docs/.hidden/x", "top.txt"):
            s3.put_object(Bucket="alpha-bucket", Key=key, Body=b"xyz")

        root = browse("s3://", s3_client=s3)
        assert [f.name for f in root.folders] == ["alpha-bucket", "zeta-bucket"]
        assert root.parent is None and root.folders[0].location == "s3://alpha-bucket/"

        bucket = browse("s3://alpha-bucket", s3_client=s3)
        assert bucket.location == "s3://alpha-bucket/" and bucket.parent == "s3://"
        assert [f.name for f in bucket.folders] == ["docs"] and [f.name for f in bucket.files] == ["top.txt"]

        docs = browse("s3://alpha-bucket/docs", s3_client=s3)  # trailing slash optional
        assert docs.location == "s3://alpha-bucket/docs/" and docs.parent == "s3://alpha-bucket/"
        assert [f.name for f in docs.folders] == ["sub"] and [(f.name, f.size) for f in docs.files] == [("a.md", 3)]
        assert docs.crumbs == [("s3://", "s3://"), ("alpha-bucket", "s3://alpha-bucket/"), ("docs", "s3://alpha-bucket/docs/")]
        assert [f.name for f in browse("s3://alpha-bucket/docs/", show_hidden=True, s3_client=s3).folders] == [".hidden", "sub"]

        sub = browse(docs.folders[0].location, s3_client=s3)
        assert [f.name for f in sub.files] == ["b.txt"]  # the "docs/sub/" folder marker is not a file


# ------------------------------------------------------------------ index body / actions / queries
def test_index_body():
    body = build_index_body(IndexConfig(name="t", analyzer="english"))
    props = body["mappings"]["properties"]
    assert props["content"]["analyzer"] == "english" and "embedding" not in props
    sem = build_index_body(IndexConfig(name="t", semantic=True), dimension=384)
    assert sem["mappings"]["properties"]["embedding"]["dimension"] == 384
    assert sem["settings"]["index"]["knn"] is True
    assert sem["mappings"]["_meta"]["osss"]["config"]["semantic"] is True
    with pytest.raises(ValueError):
        build_index_body(IndexConfig(name="t", semantic=True))


def test_actions_are_stable():
    f = sf("a.md", b"x")
    [d] = load(sf("a.md", b"# T\n" + b"word " * 500), CFG)
    a1 = _make_actions("t", f, [d], IndexConfig(name="t", chunk_size=300, chunk_overlap=50))
    a2 = _make_actions("t", f, [d], IndexConfig(name="t", chunk_size=300, chunk_overlap=50))
    assert len(a1) > 3 and [a["_id"] for a in a1] == [a["_id"] for a in a2]
    assert a1[0]["_source"]["title"] == "T" and a1[0]["_source"]["file_type"] == "md"


def test_build_filters():
    f = build_filters({"file_type": ["pdf", "md"], "fields.category": "camping", "fields.year": {"gte": 2020}, "x": None})
    assert {"terms": {"file_type": ["pdf", "md"]}} in f
    assert {"terms": {"fields.category.keyword": ["camping"]}} in f
    assert {"range": {"fields.year": {"gte": 2020}}} in f
    assert len(f) == 3


class FakeClient:
    def __init__(self, hits):
        self.hits = hits
        self.bodies = []

    def search(self, index, body):
        self.bodies.append(body)
        return {"took": 3, "hits": {"total": {"value": len(self.hits)}, "hits": self.hits}}


def _hit(i, content="text <b>", hl=None):
    h = {"_id": str(i), "_score": 1.0 / (i + 1), "_source": {"content": content, "title": f"T{i}", "path": "p", "file_type": "md"}}
    if hl:
        h["highlight"] = {"content": hl}
    return h


def test_keyword_search_escapes_unhighlighted_content():
    c = FakeClient([_hit(0, "<script>x</script>")])
    r = run_search(c, "i", "hello", mode="keyword")
    assert "<script>" not in r[0].snippet and "&lt;script&gt;" in r[0].snippet
    assert c.bodies[0]["highlight"]["encoder"] == "html"
    assert "<script>" not in r._repr_html_().split("<style>")[-1].split("</style>", 1)[1]


def test_hybrid_rrf_merges():
    class E:
        name, dimension = "e", 2

        def embed_query(self, t):
            return [1.0, 0.0]

    c = FakeClient([_hit(0), _hit(1), _hit(2)])
    r = run_search(c, "i", "q", mode="hybrid", k=2, embedder=E())
    assert len(r) == 2 and r.total == 3 and r[0].id == "0"
    with pytest.raises(ValueError):
        run_search(c, "i", "q", mode="semantic")


# ------------------------------------------------------------------ custom metadata
from osss.metadata import MetadataError, normalize, parse_sidecar  # noqa: E402
from osss.metadata import resolve as resolve_metadata  # noqa: E402


def test_parse_bedrock_sidecar_plain_and_typed():
    plain = {"metadataAttributes": {"team": "finance", "year": 2024, "tags": ["q3", "audit"], "public": False}}
    assert parse_sidecar(json.dumps(plain).encode()) == plain["metadataAttributes"]
    typed = {"metadataAttributes": {
        "team": {"value": {"type": "STRING", "stringValue": "hr"}, "includeForEmbedding": True},
        "year": {"value": {"type": "NUMBER", "numberValue": 2023}},
        "ok": {"value": {"type": "BOOLEAN", "booleanValue": True}},
        "tags": {"value": {"type": "STRING_LIST", "stringListValue": ["a", "b"]}},
    }}
    assert parse_sidecar(json.dumps(typed)) == {"team": "hr", "year": 2023, "ok": True, "tags": ["a", "b"]}
    assert parse_sidecar(b'\xef\xbb\xbf{"team": "ops"}') == {"team": "ops"}  # flat object, BOM
    for bad in (b"not json", b"[1, 2]", b'{"metadataAttributes": 3}',
                b'{"x": {"value": {"type": "BLOB", "blobValue": 1}}}', b'{"x": [[1]]}'):
        with pytest.raises(MetadataError):
            parse_sidecar(bad)


def test_normalize_metadata():
    d = datetime(2024, 5, 1, tzinfo=timezone.utc)
    assert normalize({"when": d, "skip": None, "n": 1.5}) == {"when": d.isoformat(), "n": 1.5}
    with pytest.raises(MetadataError):
        normalize({"obj": object()})
    with pytest.raises(MetadataError):
        normalize({"": 1})


def test_local_sidecars_are_attached_not_indexed(tmp_path):
    (tmp_path / "a.md").write_text("# A")
    (tmp_path / "a.md.metadata.json").write_text(json.dumps({"metadataAttributes": {"team": "hr", "year": 2024}}))
    (tmp_path / "b.md").write_text("# B")
    files = {f.rel_path: f for f in LocalSource(tmp_path).iter_files()}
    assert sorted(files) == ["a.md", "b.md"]  # the sidecar is not a document of its own
    assert files["b.md"].read_sidecar() is None
    # sidecar wins over metadata=, which can be a dict or a function of the file
    assert resolve_metadata(files["a.md"], {"team": "x", "src": "wiki"}) == {"team": "hr", "year": 2024, "src": "wiki"}
    assert resolve_metadata(files["b.md"], lambda f: {"name": f.name}) == {"name": "b.md"}
    assert resolve_metadata(files["a.md"], sidecars=False) == {}
    # pointing at a single file still finds its sidecar
    [single] = LocalSource(tmp_path / "a.md").iter_files()
    assert resolve_metadata(single) == {"team": "hr", "year": 2024}


def test_s3_sidecars_with_moto():
    moto = pytest.importorskip("moto")
    import boto3

    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="kb-bucket")
        s3.put_object(Bucket="kb-bucket", Key="kb/a.pdf", Body=b"x")
        s3.put_object(Bucket="kb-bucket", Key="kb/a.pdf.metadata.json", Body=b'{"metadataAttributes": {"team": "legal"}}')
        s3.put_object(Bucket="kb-bucket", Key="kb/b.pdf", Body=b"y")
        files = {f.rel_path: f for f in S3Source("s3://kb-bucket/kb/", client=s3).iter_files(include=["*.pdf"])}
        assert sorted(files) == ["a.pdf", "b.pdf"]
        assert resolve_metadata(files["a.pdf"]) == {"team": "legal"}
        assert files["b.pdf"].read_sidecar() is None
        [single] = S3Source("s3://kb-bucket/kb/a.pdf", client=s3).iter_files()
        assert resolve_metadata(single) == {"team": "legal"}
        [lone] = S3Source("s3://kb-bucket/kb/b.pdf", client=s3).iter_files()
        assert lone.read_sidecar() is None


def test_metadata_on_every_chunk_and_filters():
    [d] = load(sf("a.md", b"# T\n" + b"word " * 500), CFG)
    acts = _make_actions("t", sf("a.md", b""), [d], IndexConfig(name="t", chunk_size=300, chunk_overlap=50), {"team": "hr"})
    assert len(acts) > 3 and all(a["_source"]["metadata"] == {"team": "hr"} for a in acts)
    assert "metadata" not in _make_actions("t", sf("a.md", b""), [d], CFG)[0]["_source"]
    assert build_index_body(CFG)["mappings"]["properties"]["metadata"]["type"] == "object"
    f = build_filters({"metadata.team": "hr", "metadata.year": {"gte": 2024}, "metadata.public": True})
    assert {"terms": {"metadata.team.keyword": ["hr"]}} in f
    assert {"range": {"metadata.year": {"gte": 2024}}} in f
    assert {"terms": {"metadata.public": [True]}} in f


def test_ingest_attaches_metadata(tmp_path, monkeypatch):
    from opensearchpy import helpers

    from osss.indexer import ingest

    (tmp_path / "a.md").write_text("# A\nalpha")
    (tmp_path / "a.md.metadata.json").write_text('{"metadataAttributes": {"team": "hr"}}')
    (tmp_path / "b.md").write_text("# B\nbeta")
    (tmp_path / "bad.md").write_text("# Bad")
    (tmp_path / "bad.md.metadata.json").write_text("{oops")
    written = []
    monkeypatch.setattr(helpers, "bulk", lambda client, actions, **kw: (written.extend(actions) or (len(actions), [])))

    class C:
        class indices:
            put_settings = refresh = staticmethod(lambda **kw: None)

    report = ingest(C(), IndexConfig(name="t"), LocalSource(tmp_path), metadata={"src": "wiki"}, progress=False)
    by_path = {a["_source"]["path"]: a["_source"].get("metadata") for a in written}
    assert by_path == {"a.md": {"src": "wiki", "team": "hr"}, "b.md": {"src": "wiki"}}
    assert report.files_indexed == 2 and len(report.failed) == 1 and "bad.md.metadata.json" in report.failed[0][1]


def test_hit_exposes_metadata():
    h = _hit(0)
    h["_source"]["metadata"] = {"team": "hr"}
    r = run_search(FakeClient([h]), "i", "q", mode="keyword", filters={"metadata.team": "hr"})
    assert r[0].metadata == {"team": "hr"} and r.to_list()[0]["metadata.team"] == "hr"
    assert "team" in r._repr_html_()


def test_cli_meta_parsing():
    from osss.cli import _parse_meta

    assert _parse_meta(["team=hr", "year=2024", "tags=a, b", "ok=true", 'name="x=y"']) == {
        "team": "hr", "year": 2024, "tags": ["a", "b"], "ok": True, "name": "x=y"}
    with pytest.raises(SystemExit):
        _parse_meta(["nokey"])
