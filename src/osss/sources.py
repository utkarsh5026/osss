"""Where documents come from: local folders/files and Amazon S3 prefixes."""

from __future__ import annotations

import fnmatch
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Union

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

    def scan(self, include: Sequence[str] = (), exclude: Sequence[str] = (), limit: Optional[int] = None) -> ScanSummary:
        files: List[SourceFile] = []
        for f in self.iter_files(include, exclude):
            files.append(f)
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
            import boto3
            from botocore.config import Config

            session = boto3.Session(profile_name=self._profile, region_name=self._region)
            self._client = session.client("s3", config=Config(max_pool_connections=32, retries={"max_attempts": 5, "mode": "adaptive"}))
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
