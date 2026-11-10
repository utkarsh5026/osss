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


def callout(text_html: str, kind: str = "info") -> str:
    return f"<div class='o-note {kind}'>{text_html}</div>"


def empty(icon: str, title: str, text: str = "") -> str:
    icon_html = f"<div style='font-size:22px;margin-bottom:8px'>{icon}</div>" if icon else ""
    sub = f"<div class='s'>{text}</div>" if text else ""
    return f"<div class='o-empty'>{icon_html}<div class='t'>{e(title)}</div>{sub}</div>"


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
def status_pill(status: Dict[str, Any]) -> str:
    if status.get("error"):
        return "<span class='o-status'><span class='o-dot err'></span>Disconnected</span>"
    if not status.get("running", True):
        return "<span class='o-status'><span class='o-dot'></span>Not connected</span>"
    health = status.get("health") or "green"
    dot = "err" if health == "red" else "ok"
    ver = status.get("opensearch_version") or status.get("version") or ""
    url = (status.get("url") or "").replace("http://", "").replace("https://", "")
    mode = " · semantic" if status.get("semantic") else ""
    return f"<span class='o-status'><span class='o-dot {dot}'></span>OpenSearch {e(str(ver))} · {e(url)}{mode}</span>"


def header(status_html: str, subtitle: str = "Index folders and S3, search them from your notebook.") -> str:
    return (
        "<div class='o-header'><div class='o-brand'><span class='o-wordmark'>osss</span>"
        f"<span class='o-tagline'>{e(subtitle)}</span></div>{status_html}</div>"
    )


def server_card(status: Dict[str, Any], standalone: bool = True) -> str:
    running = status.get("running")
    state = "<span class='o-ok'>Running</span>" if running else "<span class='o-muted'>Stopped</span>"
    if running and status.get("uptime_s") is not None:
        state += f" <span class='o-faint'>· up {e(human_duration(status['uptime_s']))}</span>"
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
        return empty("🗂️", "No indexes yet", "Create one from a local folder or an S3 prefix.")
    trs = "".join(
        f"<tr><td class='name'>{e(r['name'])}</td><td class='num'>{human_count(r['docs'])}</td>"
        f"<td class='num'>{human_bytes(r['size_bytes'])}</td>"
        f"<td><span class='o-dot {'ok' if r.get('health') in ('green', 'yellow') else 'err'}'></span>&nbsp; {e(str(r.get('health')))}</td></tr>"
        for r in rows
    )
    return (
        "<table class='o-table'><thead><tr><th>Index</th><th class='num'>Chunks</th>"
        f"<th class='num'>Size</th><th>Health</th></tr></thead><tbody>{trs}</tbody></table>"
    )


def cluster_card(info: Dict[str, Any], rows: List[Dict[str, Any]], standalone: bool = True) -> str:
    if info.get("error"):
        return wrap(callout(f"Cannot reach <code>{e(info.get('url', ''))}</code><br>{e(info['error'])}", "err"), standalone)
    status = {**info, "running": True, "opensearch_version": info.get("version")}
    body = header(status_pill(status)) + spacer(16) + index_table(rows)
    return wrap(body, standalone)


def index_card(s: Dict[str, Any], standalone: bool = True) -> str:
    mode = "Keyword + semantic" if s.get("semantic") else "Keyword"
    top = stats([
        (human_count(s.get("files", 0)), "Files"),
        (human_count(s.get("chunks", 0)), "Chunks"),
        (human_bytes(s.get("size_bytes", 0)), "On disk"),
        (mode, "Search"),
    ])
    rows = []
    if s.get("embedding_model"):
        rows.append(("Embeddings", f"<code>{e(s['embedding_model'])}</code>"))
    if s.get("analyzer"):
        rows.append(("Analyzer", e(s["analyzer"])))
    if s.get("chunk_size") is not None:
        rows.append(("Chunking", e(f"{s['chunk_size']} characters" if s["chunk_size"] else "whole documents")))
    if s.get("created_at"):
        rows.append(("Created", e(str(s["created_at"])[:16].replace("T", " "))))
    if s.get("last_indexed"):
        rows.append(("Last indexed", e(str(s["last_indexed"])[:16].replace("T", " "))))
    body = (
        f"<h3>🗂️ {e(s['name'])}</h3>{spacer(12)}{top}{spacer(14)}{tags(s.get('file_types') or {})}"
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
    files = "".join(
        f"<li><span>{e(f.rel_path)}</span><span>{human_bytes(f.size)}</span></li>" for f in ordered[:sample]
    )
    more = f"<li><span class='o-faint'>and {human_count(n - sample)} more</span><span></span></li>" if n > sample else ""
    note = (
        callout(f"{human_count(unsupported)} file(s) have a type osss can't read and will be skipped.", "warn")
        if unsupported else ""
    )
    body = (
        stats([(human_count(n), "Files"), (human_bytes(summary.total_bytes), "Total size"), (len(summary.by_type), "Types")])
        + spacer(12) + tags(summary.by_type) + note + f"<ul class='o-files'>{files}{more}</ul>"
    )
    return wrap(f"<div style='margin-top:10px'>{body}</div>", standalone)


def report_card(r: "IngestReport", standalone: bool = True) -> str:
    if r.cancelled:
        title, cls = "Indexing cancelled", "o-err"
    elif r.ok:
        title, cls = f"✓ {r.index} is ready", "o-ok"
    else:
        title, cls = f"{r.index} was built with warnings", "o-err"
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
            f"<details class='o-more' style='margin-left:0'><summary>{len(r.skipped)} skipped · {len(r.failed)} failed</summary>"
            f"<ul class='o-files'>{lis}</ul></details>"
        )
    if r.bulk_errors:
        issues += callout(f"{r.write_error_count} chunk(s) could not be written. First error: <code>{e(r.bulk_errors[0][:300])}</code>", "err")
    body = (
        f"<div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline'>"
        f"<h3 class='{cls}'>{e(title)}</h3><span class='o-mono o-faint'>{e(r.source)}</span></div>"
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
    meta = [e(h.file_type or "file"), e(h.path or h.source)]
    if h.page is not None:
        meta.append(f"page {h.page}")
    if h.record is not None:
        meta.append(f"row {h.record + 1}")
    return (
        "<div class='o-hit'>"
        f"<div class='o-hit-top'><span class='o-rank'>{rank:02d}</span>"
        f"<span class='o-title' title='{e(h.title)}'>{e(h.title)}</span>"
        f"<span class='o-score' title='relevance score'>{f'{h.score:.3g}' if h.score else ''}</span></div>"
        f"<div class='o-meta' title='{e(h.source)}'>{SEP.join(meta)}</div>"
        f"<div class='o-snippet'>{h.snippet}</div>"
        f"{_fields_html(getattr(h, 'metadata', None) or {})}"
        f"{_fields_html(h.fields)}"
        f"<details class='o-more'><summary>Show full text</summary><pre>{e(h.content)}</pre></details>"
        "</div>"
    )


def results_html(r: "SearchResults", standalone: bool = True) -> str:
    if not r.hits:
        tip = "Try different words, enable typo tolerance, or use semantic search."
        return wrap(empty("🔍", f"No results for “{r.query}”" if r.query else "This index is empty", tip if r.query else ""), standalone)
    shown = f"{r.offset + 1}–{r.offset + len(r.hits)}"
    q = f" for <b>“{e(r.query)}”</b>" if r.query else ""
    unit = "" if r.query else " files"
    head = (
        f"<div class='o-results-head'><span>{shown} of <b>{human_count(r.total)}</b>{unit}{q}</span>"
        f"<span>{e(r.mode)} · {r.took_ms} ms</span></div>"
    )
    body = head + "".join(hit_html(h, i) for i, h in enumerate(r.hits, start=r.offset + 1))
    return wrap(body, standalone)
