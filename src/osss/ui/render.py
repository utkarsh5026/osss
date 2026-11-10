"""HTML renderers for notebook display (``_repr_html_``) and the app."""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

from .._utils import human_bytes, human_count, human_duration
from .styles import CSS

if TYPE_CHECKING:  # pragma: no cover
    from ..indexer import IngestReport
    from ..search import SearchResults
    from ..sources import ScanSummary

e = html.escape
SEP = "<span class='sep'>·</span>"


def wrap(body: str, standalone: bool = True) -> str:
    return (CSS if standalone else "") + f"<div class='osss'>{body}</div>"


def tag(text: str, count: Optional[int] = None) -> str:
    tail = f"<b>{human_count(count)}</b>" if count is not None else ""
    return f"<span class='o-tag'>{e(text)}{tail}</span>"


def tags(by_type: Dict[str, int], limit: int = 16) -> str:
    items = sorted(by_type.items(), key=lambda x: -x[1])
    out = "".join(tag(k or "other", v) for k, v in items[:limit])
    if len(items) > limit:
        out += tag(f"+{len(items) - limit}")
    return f"<div class='o-tags'>{out}</div>"


def stats(items: Iterable[tuple]) -> str:
    cells = "".join(f"<div class='o-stat'><div class='v'>{e(str(v))}</div><div class='l'>{e(l)}</div></div>" for v, l in items)
    return f"<div class='o-stats'>{cells}</div>"


# Small stroke icons (Lucide-style, 24px grid). Coloured with ``currentColor``.
ICONS = {
    "search": "<circle cx='11' cy='11' r='7'/><path d='M20 20l-3.5-3.5'/>",
    "plug": "<path d='M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5'/>",
    "folder": "<path d='M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/>",
    "info": "<circle cx='12' cy='12' r='9'/><path d='M12 11v5M12 8h.01'/>",
    "warn": "<path d='M10.3 3.9L2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01'/>",
    "err": "<circle cx='12' cy='12' r='9'/><path d='M15 9l-6 6M9 9l6 6'/>",
    "ok": "<circle cx='12' cy='12' r='9'/><path d='M8 12.5l2.5 2.5L16 9.5'/>",
    "check": "<path d='M5 12.5l4.5 4.5L19 7.5'/>",
    "x": "<path d='M6 6l12 12M18 6L6 18'/>",
}

LOGO = (
    "<svg class='o-logo' viewBox='0 0 32 32' aria-hidden='true'><rect width='32' height='32' rx='7'/>"
    "<circle cx='14' cy='14' r='6.5'/><path d='M19 19l6 6'/></svg>"
)


def icon(name: str) -> str:
    return f"<svg class='o-icon' viewBox='0 0 24 24' aria-hidden='true'>{ICONS.get(name, '')}</svg>" if name in ICONS else ""


def callout(text_html: str, kind: str = "info") -> str:
    return f"<div class='o-note {kind}'>{icon(kind)}<div>{text_html}</div></div>"


def empty(icon_name: str, title: str, text: str = "") -> str:
    """An empty / loading state. ``icon_name`` is a key of ``ICONS`` or ``"spin"``."""
    mark = "<div class='o-spin'></div>" if icon_name == "spin" else icon(icon_name)
    sub = f"<div class='s'>{text}</div>" if text else ""
    return f"<div class='o-empty'>{mark}<div class='t'>{e(title)}</div>{sub}</div>"


def step(n: Any, title: str, subtitle: str = "") -> str:
    num = f"<span class='n'>{e(str(n))}</span>" if n not in (None, "") else ""
    sub = f"<div class='s'>{subtitle}</div>" if subtitle else ""
    return f"<div class='o-step'>{num}<div><div class='t'>{e(title)}</div>{sub}</div></div>"


def meter(fraction: Optional[float], state: str = "") -> str:
    if fraction is None and state == "":
        return "<div class='o-meter indeterminate'><i></i></div>"
    width = 100 if fraction is None else max(0.0, min(100.0, fraction * 100))
    return f"<div class='o-meter {state}'><i style='width:{width:.1f}%'></i></div>"


def kv(rows: Iterable[tuple]) -> str:
    return "<dl class='o-kv'>" + "".join(f"<dt>{e(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def spacer(px: int = 14) -> str:
    return f"<div style='height:{px}px'></div>"


# --------------------------------------------------------------- status
HEALTH_DOT = {"green": "ok", "yellow": "warn", "red": "err"}


def status_pill(status: Dict[str, Any]) -> str:
    if status.get("error"):
        return "<span class='o-status' title='The cluster stopped responding'><span class='o-dot err'></span>Disconnected</span>"
    if not status.get("running", True):
        return "<span class='o-status'><span class='o-dot'></span>Not connected</span>"
    health = status.get("health") or "green"
    dot = HEALTH_DOT.get(health, "ok")
    ver = status.get("opensearch_version") or status.get("version") or ""
    url = (status.get("url") or "").replace("http://", "").replace("https://", "")
    sep = "<span class='sep'>·</span>"
    mode = f"{sep}k-NN" if status.get("semantic") else ""
    return (
        f"<span class='o-status' title='Cluster health: {e(str(health))}'><span class='o-dot {dot}'></span>"
        f"<b>OpenSearch {e(str(ver))}</b>{sep}{e(url)}{mode}</span>"
    )


def header(status_html: str, subtitle: str = "Index folders and S3, search them from your notebook.") -> str:
    return (
        f"<div class='o-header'><div class='o-brand'>{LOGO}<span class='o-wordmark'>osss</span>"
        f"<span class='o-tagline'>{e(subtitle)}</span></div>{status_html}</div>"
    )


def server_card(status: Dict[str, Any], standalone: bool = True) -> str:
    running = status.get("running")
    if running:
        dot = HEALTH_DOT.get(status.get("health") or "green", "ok")
        state = f"<span class='o-health'><span class='o-dot {dot}'></span><span style='color:var(--o-fg)'>Running</span>"
        if status.get("uptime_s") is not None:
            state += f"<span class='o-faint'>up {e(human_duration(status['uptime_s']))}</span>"
        state += "</span>"
    else:
        state = "<span class='o-health'><span class='o-dot'></span>Stopped</span>"
    rows = [
        ("Status", state),
        ("Address", f"<code>{e(status.get('url', ''))}</code>"),
        ("Version", e(str(status.get("opensearch_version") or status.get("version")))),
        ("Runtime", e(f"{status.get('backend')} · {'keyword + semantic' if status.get('semantic') else 'keyword'}")),
        ("Data", f"<code>{e(status.get('home', ''))}</code>"),
    ]
    return wrap(kv(rows), standalone)


def index_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return empty("folder", "No indexes yet", "Create one from a local folder or an S3 prefix.")
    trs = "".join(
        f"<tr><td class='name'>{e(r['name'])}</td>"
        f"<td><span class='o-health'><span class='o-dot {HEALTH_DOT.get(r.get('health'), 'err')}'></span>{e(str(r.get('health') or 'unknown'))}</span></td>"
        f"<td class='num'>{human_count(r['docs'])}</td>"
        f"<td class='num'>{human_bytes(r['size_bytes'])}</td></tr>"
        for r in rows
    )
    return (
        "<table class='o-table'><thead><tr><th>Index</th><th style='width:140px'>Health</th>"
        f"<th class='num' style='width:120px'>Chunks</th><th class='num' style='width:120px'>Size</th></tr></thead><tbody>{trs}</tbody></table>"
    )


def cluster_card(info: Dict[str, Any], rows: List[Dict[str, Any]], standalone: bool = True) -> str:
    if info.get("error"):
        return wrap(callout(f"Cannot reach <code>{e(info.get('url', ''))}</code><br>{e(info['error'])}", "err"), standalone)
    status = {**info, "running": True, "opensearch_version": info.get("version")}
    body = header(status_pill(status)) + spacer(16) + index_table(rows)
    return wrap(body, standalone)


def index_card(s: Dict[str, Any], standalone: bool = True) -> str:
    mode = "keyword + semantic" if s.get("semantic") else "keyword"
    top = stats([
        (human_count(s.get("files", 0)), "Files"),
        (human_count(s.get("chunks", 0)), "Chunks"),
        (human_bytes(s.get("size_bytes", 0)), "On disk"),
    ])
    rows = []
    if s.get("embedding_model"):
        rows.append(("Embeddings", f"<code>{e(s['embedding_model'])}</code>"))
    if s.get("analyzer"):
        rows.append(("Analyzer", e(s["analyzer"])))
    if s.get("chunk_size") is not None:
        strategy = s.get("chunking") or "fixed"
        if strategy == "none" or not s["chunk_size"]:
            text = "whole documents"
        elif strategy == "hierarchical":
            text = f"hierarchical · {s['chunk_size']}-character chunks in {s.get('parent_chunk_size')}-character parents"
        elif strategy == "semantic":
            text = f"semantic · up to {s['chunk_size']} characters"
        else:
            text = f"{s['chunk_size']} characters"
        rows.append(("Chunking", e(text)))
    if s.get("created_at"):
        rows.append(("Created", e(str(s["created_at"])[:16].replace("T", " "))))
    if s.get("last_indexed"):
        rows.append(("Last indexed", e(str(s["last_indexed"])[:16].replace("T", " "))))
    body = (
        f"<div style='display:flex;align-items:center;gap:10px'><h3>{e(s['name'])}</h3>"
        f"<span class='o-tag solid'>{mode}</span></div>{spacer(14)}{top}{spacer(14)}{tags(s.get('file_types') or {})}"
        f"{spacer(14) + kv(rows) if rows else ''}"
    )
    return wrap(f"<div style='padding-bottom:18px;margin-bottom:6px;border-bottom:1px solid var(--o-line)'>{body}</div>", standalone)


def scan_card(summary: "ScanSummary", standalone: bool = True, sample: int = 8) -> str:
    from ..loaders import is_supported

    n = len(summary.files)
    if n == 0:
        return wrap(callout(f"No files found in <code>{e(summary.uri)}</code> with the current filters.", "warn"), standalone)
    unsupported = sum(c for t, c in summary.by_type.items() if t and not is_supported(t))
    ordered = sorted(summary.files, key=lambda f: (not is_supported(f.ext) and bool(f.ext), f.rel_path))
    def row(f) -> str:
        off = bool(f.ext) and not is_supported(f.ext)
        right = "skipped" if off else human_bytes(f.size)
        return f"<li class='{'off' if off else ''}'><span title='{e(f.rel_path)}'>{e(f.rel_path)}</span><span>{right}</span></li>"

    files = "".join(row(f) for f in ordered[:sample])
    more = f"<li class='more'><span>and {human_count(n - sample)} more</span><span></span></li>" if n > sample else ""
    note = (
        callout(f"{human_count(unsupported)} {'file has a type' if unsupported == 1 else 'files have types'} "
                "osss can't read. They will be skipped.", "warn")
        if unsupported else ""
    )
    body = (
        stats([(human_count(n), "Files"), (human_bytes(summary.total_bytes), "Total size"), (len(summary.by_type), "Types")])
        + spacer(12) + tags(summary.by_type) + note + f"<ul class='o-files'>{files}{more}</ul>"
    )
    return wrap(f"<div style='margin-top:10px'>{body}</div>", standalone)


def report_card(r: "IngestReport", standalone: bool = True) -> str:
    if r.cancelled:
        title, dot = "Indexing cancelled", "err"
    elif r.ok:
        title, dot = f"{r.index} is ready", "ok"
    else:
        title, dot = f"{r.index} was built with warnings", "warn"
    top = stats([
        (human_count(r.files_indexed), "Files"),
        (human_count(r.chunks), "Chunks"),
        (human_bytes(r.bytes_read), "Read"),
        (human_duration(r.elapsed), "Time"),
    ])
    issues = ""
    problem_rows = [("skipped", u, m) for u, m in r.skipped[:50]] + [("failed", u, m) for u, m in r.failed[:50]]
    if problem_rows:
        lis = "".join(
            f"<li><span>{e(u.rsplit('/', 1)[-1])}</span><span class='{'o-err' if k == 'failed' else ''}'>{e(m)}</span></li>"
            for k, u, m in problem_rows
        )
        issues = (
            f"<details class='o-more' style='margin-left:0;margin-top:14px'><summary>{len(r.skipped)} skipped · {len(r.failed)} failed</summary>"
            f"<ul class='o-files'>{lis}</ul></details>"
        )
    if r.bulk_errors:
        issues += callout(f"{r.write_error_count} chunk(s) could not be written. First error: <code>{e(r.bulk_errors[0][:300])}</code>", "err")
    body = (
        f"<div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline'>"
        f"<span class='o-health'><span class='o-dot {dot}'></span><h3>{e(title)}</h3></span>"
        f"<span class='o-mono o-faint'>{e(r.source)}</span></div>"
        f"{spacer(12)}{top}{spacer(12)}{tags(dict(r.by_type))}{issues}"
    )
    return wrap(f"<div style='padding-top:16px;border-top:1px solid var(--o-line);margin-top:14px'>{body}</div>", standalone)


# --------------------------------------------------------------- results
def _fields_html(fields: Dict[str, Any], limit: int = 6) -> str:
    if not fields:
        return ""
    items = []
    for k, v in list(fields.items())[:limit]:
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, default=str)
        sv = str(v)
        if len(sv) > 60:
            sv = sv[:57] + "…"
        items.append(f"<span><b>{e(str(k))}</b>{e(sv)}</span>")
    return f"<div class='o-fields'>{''.join(items)}</div>"


def hit_html(h, rank: int) -> str:
    where = []
    if h.page is not None:
        where.append(f"page {h.page}")
    if h.record is not None:
        where.append(f"row {h.record + 1:,}")
    extra = "".join(f"<span class='sep'>·</span><span class='x'>{w}</span>" for w in where)
    meta = (
        f"<span class='o-tag'>{e(h.file_type or 'file')}</span>"
        f"<span class='p'>{e(h.path or h.source)}</span>{extra}"
    )
    return (
        "<div class='o-hit'>"
        f"<div class='o-hit-top'><span class='o-rank'>{rank:02d}</span>"
        f"<span class='o-title' title='{e(h.title)}'>{e(h.title)}</span>"
        f"<span class='o-score' title='relevance score'>{f'{h.score:.3g}' if h.score else ''}</span></div>"
        f"<div class='o-meta' title='{e(h.source)}'>{meta}</div>"
        f"<div class='o-snippet'>{h.snippet}</div>"
        f"{_fields_html(getattr(h, 'metadata', None) or {})}"
        f"{_fields_html(h.fields)}"
        f"<details class='o-more'><summary>Show full text</summary><pre>{e(h.content)}</pre></details>"
        "</div>"
    )


def results_html(r: "SearchResults", standalone: bool = True) -> str:
    if not r.hits:
        tip = "Try different words, enable typo tolerance, or use semantic search."
        return wrap(empty("search", f"No results for “{r.query}”" if r.query else "This index is empty", tip if r.query else ""), standalone)
    shown = f"{r.offset + 1}–{r.offset + len(r.hits)}"
    q = f" for <b>“{e(r.query)}”</b>" if r.query else ""
    unit = "" if r.query else " files"
    head = (
        f"<div class='o-results-head'><span>{shown} of <b>{human_count(r.total)}</b>{unit}{q}</span>"
        f"<span class='r'><span class='o-tag'>{e(r.mode)}</span>{r.took_ms:,} ms</span></div>"
    )
    body = head + "".join(hit_html(h, i) for i, h in enumerate(r.hits, start=r.offset + 1))
    return wrap(body, standalone)
