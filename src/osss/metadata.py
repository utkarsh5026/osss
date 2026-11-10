"""Custom metadata attached to every chunk of a file.

Two ways to provide it, and they combine:

* **Sidecar files**, the same convention as Amazon Bedrock Knowledge Bases:
  next to ``report.pdf`` put ``report.pdf.metadata.json``::

      {"metadataAttributes": {"department": "finance", "year": 2024, "tags": ["q3", "audit"]}}

  Bedrock's typed form is accepted too, so existing knowledge-base sidecars
  work unchanged::

      {"metadataAttributes": {"year": {"value": {"type": "NUMBER", "numberValue": 2024},
                                       "includeForEmbedding": true}}}

* **In Python**, ``metadata=`` on ``create_index`` / ``add``: a dict applied to
  every file, or a function ``(SourceFile) -> dict`` computed per file.

The values end up under ``metadata.<key>`` on each chunk, where they can be
filtered (``idx.search(q, metadata={"department": "finance"})``) and are shown
with every result.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable, Dict, Mapping, Optional, Union

from .sources import SIDECAR_SUFFIX, SourceFile

MetadataLike = Union[Mapping[str, Any], Callable[[SourceFile], Optional[Mapping[str, Any]]], None]

_TYPED_KEYS = {
    "STRING": "stringValue",
    "NUMBER": "numberValue",
    "BOOLEAN": "booleanValue",
    "STRING_LIST": "stringListValue",
}


class MetadataError(ValueError):
    pass


def _typed_value(v: Dict[str, Any]) -> Any:
    """``{"type": "NUMBER", "numberValue": 3}`` → ``3`` (Bedrock's typed attribute value)."""
    t = str(v.get("type", "")).upper()
    key = _TYPED_KEYS.get(t)
    if key is None:
        raise MetadataError(f"unknown attribute type {v.get('type')!r}; expected one of {sorted(_TYPED_KEYS)}")
    return v.get(key)


def _clean_value(key: str, v: Any) -> Any:
    # Bedrock typed form: {"value": {"type": ..., "...Value": ...}, "includeForEmbedding": ...}
    if isinstance(v, dict) and isinstance(v.get("value"), dict) and "type" in v["value"]:
        v = _typed_value(v["value"])
    elif isinstance(v, dict) and "type" in v and any(k in v for k in _TYPED_KEYS.values()):
        v = _typed_value(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, (list, tuple, set)):
        out = []
        for item in v:
            item = _clean_value(key, item)
            if isinstance(item, (list, dict)):
                raise MetadataError(f"metadata {key!r}: lists may only contain plain values")
            out.append(item)
        return out
    raise MetadataError(
        f"metadata {key!r}: unsupported value of type {type(v).__name__} "
        "(use strings, numbers, booleans, dates or lists of those)"
    )


def normalize(attrs: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate metadata and turn it into plain JSON values (``None`` values are dropped)."""
    if not attrs:
        return {}
    if not isinstance(attrs, Mapping):
        raise MetadataError(f"metadata must be a dict, got {type(attrs).__name__}")
    out: Dict[str, Any] = {}
    for k, v in attrs.items():
        key = str(k).strip()
        if not key:
            raise MetadataError("metadata keys must be non-empty")
        v = _clean_value(key, v)
        if v is not None:
            out[key] = v
    return out


def parse_sidecar(data: Union[bytes, str]) -> Dict[str, Any]:
    """Parse a Bedrock-style ``*.metadata.json`` file.

    The attributes are read from ``metadataAttributes``. A file without that
    key is treated as a flat ``{"key": value}`` object.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig")
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        raise MetadataError(f"metadata file is not valid JSON: {e}") from None
    if not isinstance(obj, dict):
        raise MetadataError("metadata file must contain a JSON object")
    attrs = obj.get("metadataAttributes", obj)
    if not isinstance(attrs, dict):
        raise MetadataError("'metadataAttributes' must be a JSON object")
    return normalize(attrs)


def resolve(f: SourceFile, metadata: MetadataLike = None, *, sidecars: bool = True) -> Dict[str, Any]:
    """Metadata for one file: the ``metadata=`` argument, then its sidecar file (which wins on conflicts)."""
    out: Dict[str, Any] = {}
    if metadata is not None:
        out.update(normalize(metadata(f) if callable(metadata) else metadata))
    if sidecars:
        raw = f.read_sidecar()
        if raw is not None:
            try:
                out.update(parse_sidecar(raw))
            except MetadataError as e:
                raise MetadataError(f"{f.name}{SIDECAR_SUFFIX}: {e}") from None
    return out
