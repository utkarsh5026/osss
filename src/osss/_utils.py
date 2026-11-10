"""Small internal helpers shared across modules."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, TypeVar

T = TypeVar("T")


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def osss_home() -> Path:
    """Directory where osss keeps OpenSearch binaries, data and logs.

    Override with the ``OSSS_HOME`` environment variable. When running as root
    (the default in SageMaker Studio kernels) we default to ``/opt/osss`` because
    OpenSearch refuses to run as root and the unprivileged user it is started as
    cannot traverse ``/root``.
    """
    env = os.environ.get("OSSS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if is_root():
        return Path("/opt/osss")
    return Path.home() / ".osss"


def in_notebook() -> bool:
    try:
        from IPython import get_ipython  # type: ignore
    except Exception:
        return False
    ip = get_ipython()
    if ip is None:
        return False
    name = ip.__class__.__name__
    if name in ("ZMQInteractiveShell", "Shell"):  # Jupyter / Colab
        return True
    return "IPKernelApp" in getattr(ip, "config", {})


_INDEX_NAME_BAD = re.compile(r"[^a-z0-9_\-]+")


def sanitize_index_name(name: str) -> str:
    """Turn arbitrary text (a folder name, an S3 prefix...) into a valid index name."""
    name = name.strip().lower().replace(" ", "-").replace(".", "-")
    name = _INDEX_NAME_BAD.sub("-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-_+")
    return name[:200] or "my-index"


def stable_id(*parts: object) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "surrogatepass"))
        h.update(b"\x1f")
    return h.hexdigest()


def batched(items: Iterable[T], size: int) -> Iterator[List[T]]:
    batch: List[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def human_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def human_count(n: int) -> str:
    return f"{int(n):,}"


def pip_install(packages: Sequence[str]) -> subprocess.CompletedProcess:
    """Install packages into the *current* interpreter (works inside notebooks)."""
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", *packages],
        capture_output=True,
        text=True,
    )


def module_available(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None
