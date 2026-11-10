"""Where documents come from: local folders/files and Amazon S3 prefixes."""

from __future__ import annotations

import fnmatch
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from ._utils import human_bytes

#: Suffix of a sidecar metadata file (Amazon Bedrock Knowledge Base convention):
#: ``report.pdf`` is described by ``report.pdf.metadata.json``.
SIDECAR_SUFFIX = ".metadata.json"


def is_sidecar(name: str) -> bool:
    """True for ``*.metadata.json`` files: they describe another file and are not indexed themselves."""
    return name.lower().endswith(SIDECAR_SUFFIX)


@dataclass
class SourceFile:
    """A file discovered in a source. Content is fetched lazily by :meth:`read`."""

    uri: str
    rel_path: str
    size: int
    modified: Optional[datetime]
    _reader: Callable[[], bytes] = field(repr=False)
    _sidecar_reader: Optional[Callable[[], Optional[bytes]]] = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.rel_path.rsplit("/", 1)[-1]

    @property
    def ext(self) -> str:
        name = self.name.lower()
        for double in (".jsonl.gz", ".csv.gz"):
            if name.endswith(double):
                return double[1:]
        return name.rsplit(".", 1)[-1] if "." in name else ""

    @property
    def folder(self) -> str:
        return self.rel_path.rsplit("/", 1)[0] if "/" in self.rel_path else ""

    def read(self) -> bytes:
        return self._reader()

    def read_sidecar(self) -> Optional[bytes]:
        """Contents of this file's ``.metadata.json`` sidecar, or ``None`` if it has none."""
        return self._sidecar_reader() if self._sidecar_reader is not None else None


def _matches(rel: str, patterns: Sequence[str]) -> bool:
    base = rel.rsplit("/", 1)[-1]
    for p in patterns:
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(base, p):
            return True
        # "docs/**" should match "docs/a.md" and "docs/x/y.md"
        if p.endswith("/**") and (rel == p[:-3] or rel.startswith(p[:-2])):
            return True
    return False


def keep(rel: str, include: Sequence[str] = (), exclude: Sequence[str] = ()) -> bool:
    if exclude and _matches(rel, exclude):
        return False
    if include and not _matches(rel, include):
        return False
    return True


@dataclass
class ScanSummary:
    """What a source contains, shown before indexing."""

    uri: str
    files: List[SourceFile]
    by_type: Dict[str, int]
    total_bytes: int

    def __len__(self) -> int:
        return len(self.files)

    def __repr__(self) -> str:
        types = ", ".join(f"{k or '?'}:{v}" for k, v in sorted(self.by_type.items(), key=lambda x: -x[1]))
        return f"<ScanSummary {self.uri} · {len(self.files)} files · {human_bytes(self.total_bytes)} · {types}>"

    def _repr_html_(self) -> str:
        from .ui.render import scan_card

        return scan_card(self)


class Source:
    uri: str

    def iter_files(self, include: Sequence[str] = (), exclude: Sequence[str] = ()) -> Iterator[SourceFile]:
        raise NotImplementedError

    def scan(
        self, include: Sequence[str] = (), exclude: Sequence[str] = (), limit: Optional[int] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> ScanSummary:
        """List matching files. ``on_progress(files_found, bytes_found)`` is called for every file."""
        files: List[SourceFile] = []
        total = 0
        for f in self.iter_files(include, exclude):
            files.append(f)
            total += f.size
            if on_progress is not None:
                on_progress(len(files), total)
            if limit and len(files) >= limit:
                break
        return ScanSummary(
            uri=self.uri,
            files=files,
            by_type=dict(Counter(f.ext for f in files)),
            total_bytes=sum(f.size for f in files),
        )


def _local_sidecar(path: Path) -> Callable[[], Optional[bytes]]:
    def read() -> Optional[bytes]:
        side = path.with_name(path.name + SIDECAR_SUFFIX)
        try:
            return side.read_bytes() if side.is_file() else None
        except OSError:
            return None

    return read


class LocalSource(Source):
    """A local file or directory (searched recursively)."""

    def __init__(self, path: Union[str, os.PathLike]) -> None:
        self.path = Path(path).expanduser()
        if not self.path.exists():
            raise FileNotFoundError(f"No such file or directory: {self.path}")
        self.uri = str(self.path.resolve())

    def iter_files(self, include=(), exclude=()):
        root = self.path.resolve()
        if root.is_file():
            st = root.stat()
            yield SourceFile(
                uri=str(root), rel_path=root.name, size=st.st_size,
                modified=datetime.fromtimestamp(st.st_mtime, timezone.utc),
                _reader=root.read_bytes, _sidecar_reader=_local_sidecar(root),
            )
            return
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
            # Prune excluded directories early (e.g. .git, node_modules).
            # A directory is skipped when a hypothetical file inside it is excluded.
            dirnames[:] = sorted(
                d for d in dirnames
                if not (exclude and _matches(f"{rel_dir}/{d}/\0".lstrip("/"), exclude))
            )
            for fn in sorted(filenames):
                rel = f"{rel_dir}/{fn}" if rel_dir else fn
                if is_sidecar(fn) or not keep(rel, include, exclude):
                    continue
                full = Path(dirpath) / fn
                try:
                    st = full.stat()
                except OSError:
                    continue
                if not full.is_file():
                    continue
                yield SourceFile(
                    uri=str(full), rel_path=rel, size=st.st_size,
                    modified=datetime.fromtimestamp(st.st_mtime, timezone.utc),
                    _reader=full.read_bytes, _sidecar_reader=_local_sidecar(full),
                )


def _s3_client(profile: Optional[str] = None, region: Optional[str] = None):
    import boto3
    from botocore.config import Config

    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("s3", config=Config(max_pool_connections=32, retries={"max_attempts": 5, "mode": "adaptive"}))


class S3Source(Source):
    """All objects under an ``s3://bucket/prefix``.

    Uses the default boto3 credential chain, so in SageMaker the notebook's
    execution role is picked up automatically.
    """

    def __init__(self, uri: str, *, profile: Optional[str] = None, region: Optional[str] = None, client=None) -> None:
        if not uri.startswith("s3://"):
            raise ValueError("S3 URIs must look like s3://bucket/prefix")
        rest = uri[5:]
        self.bucket, _, self.prefix = rest.partition("/")
        if not self.bucket:
            raise ValueError("S3 URI is missing a bucket name")
        self.uri = f"s3://{self.bucket}/{self.prefix}"
        self._client = client
        self._profile = profile
        self._region = region

    @property
    def client(self):
        if self._client is None:
            self._client = _s3_client(self._profile, self._region)
        return self._client

    def _reader(self, key: str) -> Callable[[], bytes]:
        def read() -> bytes:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

        return read

    def _try_get(self, key: str) -> Optional[bytes]:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            code = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
            if code in ("NoSuchKey", "404", "NotFound", "AccessDenied", "403"):
                return None
            raise

    def _sidecar(self, key: str, listing: Optional[Dict[str, Any]]) -> Callable[[], Optional[bytes]]:
        side = key + SIDECAR_SUFFIX

        def read() -> Optional[bytes]:
            # Sidecars seen while listing are fetched directly; once the listing is
            # complete, a file without one costs no extra request.
            if listing is not None and side in listing["keys"]:
                return self.client.get_object(Bucket=self.bucket, Key=side)["Body"].read()
            if listing is not None and listing["done"]:
                return None
            return self._try_get(side)

        return read

    def iter_files(self, include=(), exclude=()):
        paginator = self.client.get_paginator("list_objects_v2")
        prefix = self.prefix
        # A single object: s3://bucket/path/file.pdf
        single = None
        if prefix and not prefix.endswith("/"):
            try:
                head = self.client.head_object(Bucket=self.bucket, Key=prefix)
                single = head
            except Exception:
                single = None
        if single is not None:
            yield SourceFile(
                uri=f"s3://{self.bucket}/{prefix}", rel_path=prefix.rsplit("/", 1)[-1],
                size=int(single.get("ContentLength", 0)), modified=single.get("LastModified"),
                _reader=self._reader(prefix), _sidecar_reader=self._sidecar(prefix, None),
            )
            return
        base = prefix if (not prefix or prefix.endswith("/")) else prefix + "/"
        listing: Dict[str, Any] = {"keys": set(), "done": False}
        for page in paginator.paginate(Bucket=self.bucket, Prefix=base):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                if is_sidecar(key):
                    listing["keys"].add(key)
                    continue
                rel = key[len(base):]
                if not keep(rel, include, exclude):
                    continue
                yield SourceFile(
                    uri=f"s3://{self.bucket}/{key}", rel_path=rel, size=int(obj.get("Size", 0)),
                    modified=obj.get("LastModified"), _reader=self._reader(key),
                    _sidecar_reader=self._sidecar(key, listing),
                )
        listing["done"] = True


class MultiSource(Source):
    def __init__(self, sources: Iterable[Source]) -> None:
        self.sources = list(sources)
        self.uri = ", ".join(s.uri for s in self.sources)

    def iter_files(self, include=(), exclude=()):
        for s in self.sources:
            yield from s.iter_files(include, exclude)


SourceLike = Union[str, os.PathLike, Source, Sequence[Union[str, os.PathLike, Source]]]


def resolve_source(src: SourceLike) -> Source:
    """Turn ``"s3://..."``, a path, a :class:`Source`, or a list of them into a Source."""
    if isinstance(src, Source):
        return src
    if isinstance(src, (list, tuple)):
        return MultiSource(resolve_source(s) for s in src)
    s = os.fspath(src)
    if s.startswith("s3://"):
        return S3Source(s)
    if s.startswith(("http://", "https://")):
        raise ValueError("HTTP sources are not supported; download the files or use S3.")
    return LocalSource(s)


# ------------------------------------------------------------------ browsing
@dataclass
class BrowseEntry:
    """One folder or file inside a :class:`Listing`."""

    name: str
    location: str  #: full path or ``s3://`` URI; for folders, what to browse into next
    is_dir: bool
    size: Optional[int] = None


@dataclass
class Listing:
    """The direct children of one folder (local) or prefix (S3), for click-through browsing."""

    location: str
    parent: Optional[str]  #: where "Up" goes; ``None`` at the top
    crumbs: List[Tuple[str, str]]  #: ``(label, location)`` from the top down to ``location``
    folders: List[BrowseEntry]
    files: List[BrowseEntry]
    truncated: bool = False  #: stopped after ``limit`` entries

    @property
    def is_s3(self) -> bool:
        return self.location.startswith("s3://")


def browse(location: str = "", *, show_hidden: bool = False, limit: int = 5000, s3_client=None) -> Listing:
    """List the folders and files directly inside ``location``.

    ``location`` is a local path (``""`` means the current directory) or an S3 URI:
    ``"s3://"`` lists your buckets, ``"s3://bucket/a/b"`` the "folders" (common
    prefixes) and objects under ``a/b/``. Unlike :meth:`Source.scan` this does not
    recurse, so it is quick even on huge trees. Names starting with ``.`` are hidden
    unless ``show_hidden``. A local path that does not exist falls back to its nearest
    existing parent, so a half-typed path still opens somewhere sensible.
    """
    loc = os.fspath(location or "").strip()
    if loc.startswith("s3://"):
        return _browse_s3(loc, show_hidden, limit, s3_client)
    return _browse_local(loc or ".", show_hidden, limit)


def _sort_key(entry: BrowseEntry) -> Tuple[str, str]:
    return (entry.name.lower(), entry.name)


def _browse_local(loc: str, show_hidden: bool, limit: int) -> Listing:
    path = Path(loc).expanduser()
    try:
        path = path.resolve()
    except OSError:
        path = path.absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise FileNotFoundError(f"No such folder: {path}")
    folders: List[BrowseEntry] = []
    files: List[BrowseEntry] = []
    truncated = False
    with os.scandir(path) as it:
        for de in it:
            if not show_hidden and de.name.startswith("."):
                continue
            try:
                is_dir = de.is_dir()
                size = None if is_dir else de.stat().st_size
            except OSError:  # broken symlink, vanished file, no permission
                continue
            (folders if is_dir else files).append(BrowseEntry(de.name, str(path / de.name), is_dir, size))
            if len(folders) + len(files) >= limit:
                truncated = True
                break
    chain = [path, *path.parents]
    crumbs = [(p.name or p.anchor or str(p), str(p)) for p in reversed(chain)]
    parent = str(path.parent) if path.parent != path else None
    return Listing(str(path), parent, crumbs, sorted(folders, key=_sort_key), sorted(files, key=_sort_key), truncated)


def _browse_s3(loc: str, show_hidden: bool, limit: int, client) -> Listing:
    bucket, _, prefix = loc[5:].partition("/")
    client = client if client is not None else _s3_client()
    if not bucket:
        try:
            buckets = client.list_buckets().get("Buckets", []) or []
        except Exception as ex:
            code = str(getattr(ex, "response", {}).get("Error", {}).get("Code", ""))
            if code in ("AccessDenied", "403"):
                raise PermissionError(
                    "These credentials can't list S3 buckets. Type the bucket instead, e.g. "
                    "s3://my-bucket/, and browse from there."
                ) from ex
            raise
        folders = [BrowseEntry(b["Name"], f"s3://{b['Name']}/", True) for b in buckets]
        return Listing("s3://", None, [("s3://", "s3://")], sorted(folders, key=_sort_key), [])
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    folders: List[BrowseEntry] = []
    files: List[BrowseEntry] = []
    truncated = False
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for cp in page.get("CommonPrefixes", []) or []:
            name = cp["Prefix"][len(prefix):].rstrip("/")
            if name and (show_hidden or not name.startswith(".")):
                folders.append(BrowseEntry(name, f"s3://{bucket}/{cp['Prefix']}", True))
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            name = key[len(prefix):]
            if not name or key.endswith("/") or (not show_hidden and name.startswith(".")):
                continue  # the "folder marker" object the console creates, or a hidden file
            files.append(BrowseEntry(name, f"s3://{bucket}/{key}", False, int(obj.get("Size", 0))))
        if len(folders) + len(files) >= limit:
            truncated = True
            break
    crumbs = [("s3://", "s3://"), (bucket, f"s3://{bucket}/")]
    acc = ""
    for part in [p for p in prefix.split("/") if p]:
        acc += part + "/"
        crumbs.append((part, f"s3://{bucket}/{acc}"))
    parent = crumbs[-2][1]
    return Listing(f"s3://{bucket}/{prefix}", parent, crumbs, sorted(folders, key=_sort_key),
                   sorted(files, key=_sort_key), truncated)
