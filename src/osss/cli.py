"""``osss`` command-line interface (rich-powered).

    osss start [--semantic]          start the local OpenSearch
    osss index ./docs --name docs    index a folder or s3:// prefix
    osss search docs "refund policy" search it
    osss list | status | logs | stop | delete NAME | scan PATH | doctor
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from typing import List, Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from . import __version__
from ._utils import human_bytes, human_count, human_duration, is_root, module_available, osss_home

console = Console(highlight=False)
err = Console(stderr=True, highlight=False)


def _cluster(args, autostart: bool = False):
    import osss

    if getattr(args, "url", None):
        return osss.connect(args.url)
    server = osss.LocalServer()
    if server.is_running():
        return osss.Cluster(server.client(), server=server)
    if autostart:
        console.print("[dim]Local OpenSearch is not running — starting it…[/]")
        return osss.start(semantic=getattr(args, "semantic", False))
    err.print("[red]✕[/] Local OpenSearch is not running. Run [bold]osss start[/] or pass [bold]--url[/].")
    sys.exit(1)


# ------------------------------------------------------------------ commands
def cmd_start(args) -> None:
    import osss

    c = osss.start(semantic=args.semantic, port=args.port, heap=args.heap, backend=args.backend, version=args.version)
    s = c.server.status()
    console.print(Panel.fit(
        f"[bold green]● running[/]  [bold]{s['url']}[/]\n"
        f"OpenSearch {s.get('opensearch_version')} · {s['backend']} · "
        f"{'keyword + semantic' if s['semantic'] else 'keyword'}\n[dim]data: {s['home']}[/]",
        title="osss", border_style="magenta",
    ))


def cmd_stop(args) -> None:
    import osss

    osss.stop()
    console.print("[green]✓[/] Stopped. Indexes are kept on disk.")


def cmd_status(args) -> None:
    import osss

    s = osss.status()
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold")
    t.add_column()
    t.add_row("Status", "[green]● running[/]" if s["running"] else "[dim]○ stopped[/]")
    for k in ("url", "backend", "flavor", "version", "home"):
        t.add_row(k.capitalize(), str(s.get(k)))
    if s["running"]:
        t.add_row("Health", str(s.get("health")))
        if s.get("uptime_s") is not None:
            t.add_row("Uptime", human_duration(s["uptime_s"]))
    console.print(Panel.fit(t, title="Local OpenSearch", border_style="magenta"))


def cmd_logs(args) -> None:
    import osss

    console.print(osss.LocalServer().logs(args.lines), markup=False)


def cmd_list(args) -> None:
    c = _cluster(args)
    rows = c.indexes(all=args.all)
    if not rows:
        console.print("[dim]No indexes yet. Try:[/] osss index ./my-docs")
        return
    t = Table(title=f"Indexes on {c.url}", title_style="bold", border_style="grey37")
    t.add_column("Index", style="bold cyan")
    t.add_column("Chunks", justify="right")
    t.add_column("Size", justify="right")
    t.add_column("Health")
    for r in rows:
        color = {"green": "green", "yellow": "yellow"}.get(r["health"], "red")
        t.add_row(r["name"], human_count(r["docs"]), human_bytes(r["size_bytes"]), f"[{color}]●[/] {r['health']}")
    console.print(t)


def cmd_scan(args) -> None:
    from .config import DEFAULT_EXCLUDE
    from .loaders import is_supported
    from .sources import resolve_source

    with console.status(f"Scanning {args.source}…"):
        s = resolve_source(args.source).scan(args.include or [], DEFAULT_EXCLUDE)
    t = Table(title=f"{args.source} · {human_count(len(s.files))} files · {human_bytes(s.total_bytes)}", border_style="grey37")
    t.add_column("Type", style="bold")
    t.add_column("Files", justify="right")
    t.add_column("Supported")
    for ext, n in sorted(s.by_type.items(), key=lambda x: -x[1]):
        t.add_row(ext or "(none)", human_count(n), "[green]yes[/]" if is_supported(ext) or not ext else "[yellow]skipped[/]")
    console.print(t)


def _parse_meta(pairs: Optional[List[str]]) -> dict:
    """``["team=hr", "year=2024", "tags=a,b"]`` → ``{"team": "hr", "year": 2024, "tags": ["a", "b"]}``."""
    out: dict = {}
    for pair in pairs or []:
        key, sep, raw = pair.partition("=")
        if not sep or not key.strip():
            raise SystemExit(f"--meta expects KEY=VALUE, got {pair!r}")
        try:
            value = json.loads(raw)
        except ValueError:
            value = [v.strip() for v in raw.split(",")] if "," in raw else raw
        out[key.strip()] = value
    return out


def cmd_index(args) -> None:
    from .api import default_index_name

    c = _cluster(args, autostart=True)
    name = args.name or default_index_name(args.source)
    opts = dict(
        chunk_size=args.chunk_size, chunk_overlap=args.overlap, analyzer=args.analyzer,
        semantic=args.semantic, embedding_model=args.model, chunking=args.chunking,
        parent_chunk_size=args.parent_chunk_size, breakpoint_percentile=args.breakpoint_percentile,
    )
    if args.include:
        opts["include"] = args.include
    if args.exclude:
        from .config import DEFAULT_EXCLUDE

        opts["exclude"] = DEFAULT_EXCLUDE + args.exclude
    if args.types:
        opts["file_types"] = [t.strip() for t in args.types.split(",") if t.strip()]
    if args.text_fields:
        opts["text_fields"] = [t.strip() for t in args.text_fields.split(",")]
    if args.title_field:
        opts["title_field"] = args.title_field
    if args.id_field:
        opts["id_field"] = args.id_field
    if args.no_metadata_files:
        opts["metadata_files"] = False
    meta = _parse_meta(args.meta) or None
    if args.add and c.exists(name):
        report = c.index(name).add(args.source, metadata=meta)
    else:
        idx = c.create_index(name, args.source, recreate=args.recreate, metadata=meta, **opts)
        report = idx.last_report
    console.print(report)
    console.print(f"\nSearch it:  [bold]osss search {name} \"your query\"[/]")


def cmd_search(args) -> None:
    c = _cluster(args)
    idx = c.index(args.index)
    res = idx.search(args.query, mode=args.mode, k=args.k, file_type=args.type, fuzzy=args.fuzzy,
                     metadata=_parse_meta(args.meta) or None)
    if args.json:
        print(json.dumps(res.to_list(), indent=2, default=str))
    else:
        console.print(res)


def cmd_delete(args) -> None:
    c = _cluster(args)
    if not args.yes:
        from rich.prompt import Confirm

        if not Confirm.ask(f"Delete index [bold]{args.index}[/]?", default=False):
            return
    c.delete_index(args.index)
    console.print(f"[green]✓[/] Deleted {args.index}")


def cmd_doctor(args) -> None:
    from .server import LocalServer, _arch, docker_available

    def row(ok: Optional[bool], label: str, detail: str) -> None:
        icon = {True: "[green]✓[/]", False: "[red]✕[/]", None: "[yellow]•[/]"}[ok]
        t.add_row(icon, label, detail)

    t = Table(show_header=False, box=None, padding=(0, 1))
    row(True, "osss", __version__)
    row(sys.version_info >= (3, 9), "Python", platform.python_version())
    row(True, "Platform", f"{platform.system()} {platform.machine()}")
    try:
        _arch()
        row(True, "CPU arch", "supported")
    except Exception as e:
        row(False, "CPU arch", str(e))
    home = osss_home()
    free = shutil.disk_usage(home if home.exists() else home.parent if home.parent.exists() else "/").free
    row(free > 3 * 1024**3, "Disk free", f"{human_bytes(free)} at {home}")
    try:
        mem = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        row(mem > 2 * 1024**3, "Memory", human_bytes(mem))
    except (ValueError, OSError, AttributeError):
        row(None, "Memory", "unknown")
    row(None, "Running as root", "yes → OpenSearch will run as 'nobody'" if is_root() else "no")
    d = docker_available()
    row(None, "Docker", "available (preferred backend)" if d else "not available → tarball backend")
    s = LocalServer().status()
    row(s["running"], "Local server", f"running at {s['url']}" if s["running"] else "stopped (osss start)")
    try:
        import boto3

        creds = boto3.Session().get_credentials()
        row(creds is not None, "AWS credentials", "found" if creds else "none (needed for S3 / Bedrock)")
    except Exception as e:
        row(False, "AWS credentials", str(e))
    for mod, label, extra in (("pypdf", "PDF support", "pdf"), ("pyarrow", "Parquet support", "parquet"), ("sentence_transformers", "Local embeddings", "semantic")):
        ok = module_available(mod)
        row(ok if ok else None, label, "installed" if ok else escape(f"pip install 'osss[{extra}]'"))
    console.print(Panel.fit(t, title="osss doctor", border_style="magenta"))


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="osss", description="Local OpenSearch for notebooks: index S3/local folders and search them.")
    p.add_argument("--version", action="version", version=f"osss {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    def add(name: str, fn, help: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        sp.set_defaults(func=fn)
        return sp

    from .chunking import STRATEGIES
    from .config import ANALYZERS
    from .server import DEFAULT_VERSION

    sp = add("start", cmd_start, "Start (or reconnect to) the local OpenSearch")
    sp.add_argument("--semantic", action="store_true", help="include the k-NN plugin for semantic search")
    sp.add_argument("--port", type=int, default=9200)
    sp.add_argument("--heap", default="1g", help="JVM heap, e.g. 512m, 2g")
    sp.add_argument("--backend", default="auto", choices=["auto", "docker", "tarball"])
    sp.add_argument("--version", default=DEFAULT_VERSION, help="OpenSearch version")
    add("stop", cmd_stop, "Stop the local OpenSearch (indexes are kept)")
    add("status", cmd_status, "Show local server status")
    sp = add("logs", cmd_logs, "Show local server logs")
    sp.add_argument("-n", "--lines", type=int, default=80)

    sp = add("list", cmd_list, "List indexes")
    sp.add_argument("--all", action="store_true", help="include system indexes")
    sp.add_argument("--url")

    sp = add("scan", cmd_scan, "Preview the files in a folder or s3:// prefix")
    sp.add_argument("source")
    sp.add_argument("--include", nargs="*")

    sp = add("index", cmd_index, "Index a folder or s3:// prefix")
    sp.add_argument("source", help="local path or s3://bucket/prefix")
    sp.add_argument("--name", help="index name (default: derived from the source)")
    sp.add_argument("--include", nargs="*", help="glob patterns to include, e.g. '*.pdf'")
    sp.add_argument("--exclude", nargs="*", help="extra glob patterns to exclude")
    sp.add_argument("--types", help="comma-separated extensions, e.g. pdf,md,csv")
    sp.add_argument("--chunk-size", type=int, default=1000, help="characters per chunk (0 = whole documents)")
    sp.add_argument("--overlap", type=int, default=150)
    sp.add_argument("--chunking", default="fixed", choices=list(STRATEGIES),
                    help="fixed (default) | hierarchical: search small chunks, return their parent | "
                         "semantic: split where the topic changes (uses --model) | none: whole documents")
    sp.add_argument("--parent-chunk-size", type=int, default=4000,
                    help="hierarchical: characters per parent chunk (--chunk-size is the child size)")
    sp.add_argument("--breakpoint-percentile", type=float, default=95.0,
                    help="semantic: split where sentence distance is above this percentile (lower = smaller chunks)")
    sp.add_argument("--analyzer", default="standard", choices=sorted(ANALYZERS))
    sp.add_argument("--semantic", action="store_true", help="also compute embeddings")
    sp.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2", help="embedding model id")
    sp.add_argument("--text-fields", help="CSV/JSON columns to search")
    sp.add_argument("--title-field")
    sp.add_argument("--id-field")
    sp.add_argument("--meta", action="append", metavar="KEY=VALUE",
                    help="metadata attached to every chunk (repeatable), e.g. --meta team=hr --meta year=2024")
    sp.add_argument("--no-metadata-files", action="store_true",
                    help="ignore <file>.metadata.json sidecar files")
    sp.add_argument("--recreate", action="store_true", help="replace the index if it exists")
    sp.add_argument("--add", action="store_true", help="add to an existing index instead of failing")
    sp.add_argument("--url")

    sp = add("search", cmd_search, "Search an index")
    sp.add_argument("index")
    sp.add_argument("query", nargs="?", default="")
    sp.add_argument("--mode", choices=["keyword", "semantic", "hybrid"])
    sp.add_argument("-k", type=int, default=10)
    sp.add_argument("--type", help="only this file type")
    sp.add_argument("--fuzzy", action="store_true")
    sp.add_argument("--meta", action="append", metavar="KEY=VALUE",
                    help="only chunks with this metadata (repeatable), e.g. --meta team=hr")
    sp.add_argument("--json", action="store_true", help="machine-readable output")
    sp.add_argument("--url")

    sp = add("delete", cmd_delete, "Delete an index")
    sp.add_argument("index")
    sp.add_argument("-y", "--yes", action="store_true")
    sp.add_argument("--url")

    add("doctor", cmd_doctor, "Check this environment")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return
    try:
        args.func(args)
    except KeyboardInterrupt:
        err.print("[yellow]Interrupted[/]")
        sys.exit(130)
    except Exception as e:  # pragma: no cover - top-level UX
        if os.environ.get("OSSS_DEBUG"):
            raise
        err.print(f"[red]✕ {type(e).__name__}:[/] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
