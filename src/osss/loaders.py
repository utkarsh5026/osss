"""Turn raw files into text documents.

Every loader yields :class:`Document` objects. Structured files (CSV, JSON,
JSONL, Parquet) yield one document per record and keep the original fields in
``fields`` so they can be filtered and displayed.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterator, List, Optional

from .config import IndexConfig
from .sources import SourceFile


@dataclass
class Document:
    text: str
    title: Optional[str] = None
    page: Optional[int] = None
    record: Optional[int] = None
    fields: Dict[str, Any] = field(default_factory=dict)
    doc_key: Optional[str] = None  # stable id for structured records


class UnsupportedFile(Exception):
    pass


class MissingDependency(Exception):
    def __init__(self, package: str, extra: str) -> None:
        super().__init__(f"needs `{package}` (pip install 'osss[{extra}]')")
        self.package = package


# --------------------------------------------------------------------- helpers
def decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\f\v]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class _HTMLText(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title: Optional[str] = None
        self._skip = 0
        self._in_title = False
        self._h1: Optional[str] = None
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip += 1
        if tag == "h1" and self._h1 is None:
            self._in_h1 = True
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag == "h1":
            self._in_h1 = False
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
            return
        if self._skip:
            return
        if self._in_h1:
            self._h1 = (self._h1 or "") + data
        self.parts.append(data)


def html_to_text(raw: str) -> tuple:
    p = _HTMLText()
    try:
        p.feed(raw)
        p.close()
    except Exception:
        pass
    text = re.sub(r"[ \t]+", " ", "".join(p.parts))
    title = (p.title or p._h1 or "").strip() or None
    return _clean(text), title


_MD_TITLE = re.compile(r"^\s{0,3}#\s+(.+?)\s*#*\s*$", re.M)
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _markdown_title(text: str) -> Optional[str]:
    fm = _FRONT_MATTER.match(text)
    if fm:
        m = re.search(r"^title:\s*['\"]?(.+?)['\"]?\s*$", fm.group(1), re.M)
        if m:
            return m.group(1)
    m = _MD_TITLE.search(text[:5000])
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------- records
def _record_text(rec: Dict[str, Any], cfg: IndexConfig) -> str:
    if cfg.text_fields:
        vals = []
        for k in cfg.text_fields:
            v = rec.get(k)
            if v not in (None, ""):
                vals.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str))
        return "\n".join(vals)
    lines = []
    for k, v in rec.items():
        if v in (None, "") or k == cfg.id_field:
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, default=str)
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _record_title(rec: Dict[str, Any], cfg: IndexConfig) -> Optional[str]:
    if cfg.title_field and rec.get(cfg.title_field) not in (None, ""):
        return str(rec[cfg.title_field])
    for k in ("title", "name", "subject", "headline", "question", "summary"):
        for key in (k, k.capitalize(), k.upper()):
            if isinstance(rec.get(key), str) and rec[key].strip():
                return rec[key].strip()[:300]
    return None


def _jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, bool, int, float)):
        if isinstance(v, float) and v != v:  # NaN
            return None
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalars
        try:
            return _jsonable(v.item())
        except Exception:
            pass
    return str(v)


def _records_to_docs(records, cfg: IndexConfig) -> Iterator[Document]:
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            rec = {"value": rec}
        rec = {str(k): _jsonable(v) for k, v in rec.items()}
        text = _record_text(rec, cfg)
        if not text.strip():
            continue
        key = str(rec[cfg.id_field]) if cfg.id_field and rec.get(cfg.id_field) is not None else None
        yield Document(text=text, title=_record_title(rec, cfg), record=i, fields=rec, doc_key=key)


# --------------------------------------------------------------------- loaders
def load_text(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    text = decode(data)
    title = _markdown_title(text) if f.ext in ("md", "markdown", "mdx", "rst", "txt") else None
    if f.ext in ("md", "markdown", "mdx"):
        text = _FRONT_MATTER.sub("", text, count=1)
    yield Document(text=_clean(text), title=title)


def load_html(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    text, title = html_to_text(decode(data))
    yield Document(text=text, title=title)


def load_xml(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    text = re.sub(r"<[^>]+>", " ", decode(data))
    import html as _h

    yield Document(text=_clean(re.sub(r"[ \t]+", " ", _h.unescape(text))))


def load_json(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    obj = json.loads(decode(data))
    if isinstance(obj, dict):
        lists = [v for v in obj.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
        if len(lists) == 1:
            obj = lists[0]
    if isinstance(obj, list):
        yield from _records_to_docs(obj, cfg)
    else:
        yield from _records_to_docs([obj], cfg)


def load_jsonl(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    if f.ext.endswith(".gz"):
        data = gzip.decompress(data)

    def records():
        for line in decode(data).splitlines():
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    yield from _records_to_docs(records(), cfg)


def load_csv(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    if f.ext.endswith(".gz"):
        data = gzip.decompress(data)
    text = decode(data)
    delimiter = "\t" if f.ext == "tsv" else ","
    if f.ext not in ("tsv",):
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            pass
    csv.field_size_limit(min(2**31 - 1, 50_000_000))
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    yield from _records_to_docs(({k: v for k, v in row.items() if k is not None} for row in reader), cfg)


def load_parquet(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    try:
        import pyarrow.parquet as pq
    except ImportError as e:
        raise MissingDependency("pyarrow", "parquet") from e
    table = pq.read_table(io.BytesIO(data))
    yield from _records_to_docs(table.to_pylist(), cfg)


def load_pdf(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise MissingDependency("pypdf", "pdf") from e
    import logging

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise UnsupportedFile("encrypted PDF") from e
    title = None
    try:
        meta = reader.metadata
        if meta and meta.title and str(meta.title).strip() and "untitled" not in str(meta.title).lower():
            title = str(meta.title).strip()
    except Exception:
        pass
    produced = False
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = _clean(text)
        if text:
            produced = True
            yield Document(text=text, title=title, page=i)
    if not produced:
        raise UnsupportedFile("no extractable text (scanned PDF? run OCR first)")


def load_docx(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise MissingDependency("python-docx", "docx") from e
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    title = (d.core_properties.title or "").strip() or None
    if not title:
        for p in d.paragraphs:
            if p.style is not None and p.style.name.lower().startswith(("title", "heading 1")) and p.text.strip():
                title = p.text.strip()
                break
    yield Document(text=_clean("\n".join(parts)), title=title)


def load_ipynb(data: bytes, f: SourceFile, cfg: IndexConfig) -> Iterator[Document]:
    nb = json.loads(decode(data))
    parts, title = [], None
    for cell in nb.get("cells", []):
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        if not src.strip():
            continue
        if cell.get("cell_type") == "markdown" and title is None:
            title = _markdown_title(src)
        parts.append(src)
    yield Document(text=_clean("\n\n".join(parts)), title=title)


TEXT_EXTS = {
    "txt", "text", "md", "markdown", "mdx", "rst", "adoc", "org", "tex", "log",
    "py", "pyi", "js", "jsx", "ts", "tsx", "java", "kt", "scala", "go", "rs", "c", "h",
    "cc", "cpp", "hpp", "cs", "rb", "php", "swift", "m", "r", "jl", "lua", "pl", "sh",
    "bash", "zsh", "ps1", "sql", "graphql", "proto", "yaml", "yml", "toml", "ini", "cfg",
    "conf", "env", "properties", "gradle", "tf", "hcl", "dockerfile", "makefile", "vue",
    "svelte", "css", "scss", "less", "srt", "vtt",
}

LOADERS: Dict[str, Callable[[bytes, SourceFile, IndexConfig], Iterator[Document]]] = {
    **{e: load_text for e in TEXT_EXTS},
    "html": load_html, "htm": load_html, "xhtml": load_html,
    "xml": load_xml, "svg": load_xml,
    "json": load_json,
    "jsonl": load_jsonl, "ndjson": load_jsonl, "jsonl.gz": load_jsonl,
    "csv": load_csv, "tsv": load_csv, "csv.gz": load_csv,
    "parquet": load_parquet,
    "pdf": load_pdf,
    "docx": load_docx,
    "ipynb": load_ipynb,
}

#: Friendly groups for the UI.
FILE_GROUPS = {
    "Documents": ["pdf", "docx", "md", "txt", "rst", "html", "htm"],
    "Data": ["csv", "tsv", "json", "jsonl", "ndjson", "parquet"],
    "Notebooks & code": ["ipynb", "py", "js", "ts", "java", "go", "sql", "yaml", "yml"],
}


def is_supported(ext: str) -> bool:
    return ext in LOADERS


def load(f: SourceFile, cfg: IndexConfig, data: Optional[bytes] = None) -> List[Document]:
    """Parse a file into documents. Raises :class:`UnsupportedFile` to skip it."""
    loader = LOADERS.get(f.ext)
    if data is None:
        data = f.read()
    if loader is None:
        # Unknown extension: index it if it looks like text (README, LICENSE...).
        if looks_binary(data):
            raise UnsupportedFile(f"unsupported file type '.{f.ext}'" if f.ext else "binary file")
        loader = load_text
    elif loader is load_text and looks_binary(data):
        raise UnsupportedFile("binary content")
    docs = [d for d in loader(data, f, cfg) if d.text]
    if not docs:
        raise UnsupportedFile("no text content")
    return docs
