"""The osss notebook app: ``osss.ui()``.

Tabs:
  🔍 Search      – query any index (keyword / semantic / hybrid), filter, page.
  ＋ New index   – pick a local folder or S3 prefix, preview, configure, build.
  🗂 Indexes     – inspect, add files to, or delete indexes.
  ⚙ Server      – start/stop the local OpenSearch or connect to a remote one.
"""

from __future__ import annotations

import html
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from .._progress import Progress
from .._utils import human_count, human_duration, module_available, pip_install, sanitize_index_name
from ..config import ANALYZERS, DEFAULT_EXCLUDE, EMBEDDING_MODELS, IndexConfig
from ..loaders import is_supported
from . import render as R
from .styles import CSS

e = html.escape


# ------------------------------------------------------------------ helpers
def _btn(label: str, *classes: str, icon: str = "", tooltip: str = "", width: Optional[str] = None) -> W.Button:
    b = W.Button(description=label, icon=icon, tooltip=tooltip or label,
                 layout=W.Layout(width=width or "auto"))
    for c in classes:
        b.add_class(c)
    return b


def _panel(*children: W.Widget, gap: str = "8px") -> W.VBox:
    box = W.VBox(list(children), layout=W.Layout(gap=gap) if _supports_gap() else W.Layout())
    box.add_class("o-panel")
    return box


def _row(*children: W.Widget, align: str = "center", wrap: bool = True, gap: str = "8px") -> W.HBox:
    lay = dict(align_items=align, flex_flow="row wrap" if wrap else "row nowrap")
    if _supports_gap():
        lay["gap"] = gap
    return W.HBox(list(children), layout=W.Layout(**lay))


def _supports_gap() -> bool:
    return "gap" in W.Layout.class_trait_names()


def _label(text: str, width: str = "120px") -> W.HTML:
    return W.HTML(f"<span class='o-muted' style='font-size:12.5px'>{e(text)}</span>",
                  layout=W.Layout(width=width))


def _field(label: str, widget: W.Widget, width: str = "120px", hint: str = "") -> W.HBox:
    items: List[W.Widget] = [_label(label, width), widget]
    if hint:
        items.append(W.HTML(f"<span class='o-muted' style='font-size:11.5px'>{hint}</span>"))
    return _row(*items, wrap=False)


def _set_titles(container: Any, titles: List[str]) -> None:
    try:
        container.titles = tuple(titles)
    except Exception:
        for i, t in enumerate(titles):
            container.set_title(i, t)


def _csv(text: str) -> List[str]:
    return [t.strip() for t in (text or "").replace("\n", ",").split(",") if t.strip()]


class PanelProgress(Progress):
    """Renders progress into an HTML widget (thread-safe, throttled)."""

    def __init__(self, target: W.HTML) -> None:
        self.target = target
        self.total: Optional[float] = None
        self.desc = ""
        self.unit = ""
        self.t0 = time.time()
        self._last = 0.0
        self._done = 0.0
        self._msg = ""

    def _render(self, state: str = "", force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last < 0.15:
            return
        self._last = now
        frac = (self._done / self.total) if self.total else None
        if self.total:
            if self.unit == "B":
                from .._utils import human_bytes

                amount = f"{human_bytes(self._done)} / {human_bytes(self.total)}"
            else:
                amount = f"{int(self._done):,} / {int(self.total):,} {self.unit}"
            right = f"{100 * frac:.0f}% · {amount}"
        else:
            right = human_duration(now - self.t0)
        icon = {"done": "<span class='o-ok'>✓</span> ", "fail": "<span class='o-err'>✕</span> "}.get(state, "")
        self.target.value = R.wrap(
            f"<div class='o-progress-label'><span style='color:var(--o-fg)'>{icon}{e(self.desc)}</span><span class='o-muted'>{e(right)}</span></div>"
            f"{R.meter(frac if state == '' else 1.0, state)}"
            f"<div class='o-muted' style='font-size:12px;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis'>{e(self._msg)}</div>",
            standalone=False,
        )

    def start(self, total, description="", unit=""):
        self.total, self.desc, self.unit = total, description, unit
        self.t0, self._done, self._msg = time.time(), 0.0, ""
        self._render(force=True)

    def update(self, completed, message=""):
        self._done = float(completed)
        if message:
            self._msg = message
        self._render()

    def note(self, message):
        self._msg = message
        self._render()

    def close(self, message="", ok=True):
        if self.total:
            self._done = self.total
        self._msg = message
        self._render("done" if ok else "fail", force=True)


# ------------------------------------------------------------------ the app
class App(W.VBox):
    """Interactive osss app. Display it in a notebook cell: ``osss.ui()``."""

    def __init__(self, cluster=None) -> None:
        super().__init__()
        self.add_class("osss")
        self.add_class("osss-app")
        self.cluster = cluster
        self._busy = False
        self._search_offset = 0

        self.header = W.HTML()
        self.toast = W.HTML()
        self.search_tab = self._build_search_tab()
        self.create_tab = self._build_create_tab()
        self.indexes_tab = self._build_indexes_tab()
        self.server_tab = self._build_server_tab()
        self.tabs = W.Tab(children=[self.search_tab, self.create_tab, self.indexes_tab, self.server_tab])
        _set_titles(self.tabs, ["🔍  Search", "＋  New index", "🗂  Indexes", "⚙  Server"])
        self.tabs.observe(self._on_tab, names="selected_index")

        spacer = W.HTML("<div style='height:10px'></div>")
        self.children = [W.HTML(CSS), self.header, spacer, self.toast, self.tabs]
        self._refresh_all(initial=True)

    # ---------------------------------------------------------------- shared
    def _notify(self, text: str, kind: str = "info", sticky: bool = False) -> None:
        self.toast.value = R.wrap(R.callout(text, kind), standalone=False) if text else ""
        if text and not sticky:
            def clear(v=self.toast.value):
                time.sleep(6)
                if self.toast.value == v:
                    self.toast.value = ""

            threading.Thread(target=clear, daemon=True).start()

    def _error(self, err: BaseException, context: str = "") -> None:
        msg = str(err) or type(err).__name__
        details = e("".join(traceback.format_exception(type(err), err, err.__traceback__))[-3000:])
        self._notify(
            f"<b>{e(context or 'Something went wrong')}</b><br>{e(msg).replace(chr(10), '<br>')}"
            f"<details class='o-more'><summary>Traceback</summary><pre>{details}</pre></details>",
            "err", sticky=True,
        )

    def _run_bg(self, fn: Callable[[], None], context: str, on_done: Optional[Callable[[], None]] = None) -> None:
        def runner():
            try:
                fn()
            except BaseException as ex:  # noqa: BLE001 - surface everything in the UI
                self._error(ex, context)
            finally:
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

        threading.Thread(target=runner, daemon=True, name="osss-ui").start()

    def _connected(self) -> bool:
        if self.cluster is None:
            return False
        try:
            self.cluster.client.ping()
            return True
        except Exception:
            return False

    def _refresh_header(self) -> None:
        status: Dict[str, Any] = {"running": False}
        if self.cluster is not None:
            try:
                info = self.cluster.info()
                status = {"running": True, "url": info["url"], "opensearch_version": info["version"],
                          "health": info["health"], "semantic": info["semantic"]}
            except Exception as ex:
                status = {"error": str(ex)}
        self.header.value = R.wrap(R.header(R.status_pill(status)), standalone=False)

    def _refresh_all(self, initial: bool = False) -> None:
        self._refresh_header()
        self._refresh_server_panel()
        connected = self._connected()
        names = self.cluster.index_names() if connected else []
        self._set_index_options(names)
        self._refresh_indexes_table()
        self.search_gate.layout.display = "none" if connected else ""
        self.search_body.layout.display = "" if connected else "none"
        self.create_gate.layout.display = "none" if connected else ""
        if initial:
            if not connected:
                self.tabs.selected_index = 3
            elif not names:
                self.tabs.selected_index = 1

    def _on_tab(self, change) -> None:
        if change["new"] == 2:
            self._refresh_indexes_table()
        elif change["new"] == 3:
            self._refresh_server_panel()

    def _set_index_options(self, names: List[str], select: Optional[str] = None) -> None:
        for dd in (self.s_index, self.ix_select):
            current = select or dd.value
            dd.options = names
            if current in names:
                dd.value = current
            elif names:
                dd.value = names[0]

    # ================================================================ SEARCH
    def _build_search_tab(self) -> W.VBox:
        self.search_gate = W.HTML(R.wrap(R.empty("🔌", "Not connected", "Start the local OpenSearch (or connect to a cluster) in the <b>⚙ Server</b> tab."), standalone=False))
        self.s_index = W.Dropdown(options=[], layout=W.Layout(width="260px"))
        self.s_index_info = W.HTML()
        self.s_query = W.Text(placeholder="Search…   try  \"exact phrase\"   -exclude   prefix*   a | b",
                              continuous_update=False, layout=W.Layout(flex="1 1 auto", width="auto"))
        self.s_query.add_class("o-search")
        self.s_go = _btn("Search", "o-primary", "o-big")
        self.s_mode = W.ToggleButtons(options=[("Keyword", "keyword")], value="keyword",
                                      tooltips=["BM25 full-text"], style={"button_width": "auto"})
        self.s_type = W.Dropdown(options=[("All file types", "")], value="", layout=W.Layout(width="190px"))
        self.s_k = W.Dropdown(options=[("10 / page", 10), ("20 / page", 20), ("50 / page", 50)], value=10, layout=W.Layout(width="120px"))
        self.s_fuzzy = W.Checkbox(value=False, description="Typo tolerance", indent=False, layout=W.Layout(width="auto"))
        self.s_all = W.Checkbox(value=False, description="Match all words", indent=False, layout=W.Layout(width="auto"))
        self.s_results = W.HTML()
        self.s_prev = _btn("Previous", "o-quiet")
        self.s_next = _btn("Next", "o-quiet")
        self.s_page = W.HTML()
        self.s_pager = _row(self.s_prev, self.s_page, self.s_next)
        self.s_pager.layout.justify_content = "center"
        self.s_pager.layout.display = "none"

        self.s_index.observe(lambda c: self._on_index_change(), names="value")
        self.s_query.observe(lambda c: self._do_search(reset=True), names="value")
        self.s_go.on_click(lambda b: self._do_search(reset=True))
        for wdg in (self.s_mode, self.s_type, self.s_k, self.s_fuzzy, self.s_all):
            wdg.observe(lambda c: self._do_search(reset=True), names="value")
        self.s_prev.on_click(lambda b: self._page(-1))
        self.s_next.on_click(lambda b: self._page(1))

        top = _row(_label("Index", "48px"), self.s_index, self.s_index_info)
        bar = _row(self.s_query, self.s_go, wrap=False)
        opts = _row(self.s_mode, self.s_type, self.s_k, self.s_fuzzy, self.s_all)
        controls = W.VBox([top, bar, opts], layout=W.Layout(gap="10px", margin="0 0 18px 0") if _supports_gap() else W.Layout(margin="0 0 18px 0"))
        self.search_body = W.VBox([controls, self.s_results, self.s_pager])
        return W.VBox([self.search_gate, self.search_body])

    def _current_index(self):
        name = self.s_index.value
        return self.cluster.index(name) if (self.cluster is not None and name) else None

    def _on_index_change(self) -> None:
        idx = None
        try:
            idx = self._current_index()
        except Exception:
            pass
        if idx is None:
            self.s_index_info.value = ""
            self.s_results.value = R.wrap(R.empty("🗂️", "No indexes yet", "Create one in the <b>＋ New index</b> tab."), standalone=False)
            return
        try:
            st = idx.stats()
        except Exception as ex:
            self._error(ex, "Could not read index")
            return
        sem = st["semantic"]
        modes = [("Keyword", "keyword")] + ([("Semantic", "semantic"), ("Hybrid", "hybrid")] if sem else [])
        self._quiet = True
        self.s_mode.options = modes
        self.s_mode.tooltips = ["BM25 full-text", "Meaning-based (vectors)", "Best of both (RRF fusion)"][: len(modes)]
        self.s_mode.value = "hybrid" if sem else "keyword"
        types = [("All file types", "")] + [(f"{t or 'other'}  ({c:,})", t) for t, c in st["file_types"].items()]
        self.s_type.options = types
        self.s_type.value = ""
        self._quiet = False
        badge = "<span class='o-tag'>semantic</span>" if sem else "<span class='o-tag'>keyword</span>"
        self.s_index_info.value = R.wrap(
            f"<span class='o-muted'>{human_count(st['files'])} files · {human_count(st['chunks'])} chunks</span> {badge}",
            standalone=False,
        )
        self._do_search(reset=True)

    def _page(self, delta: int) -> None:
        self._search_offset = max(0, self._search_offset + delta * int(self.s_k.value))
        self._do_search(reset=False)

    def _do_search(self, reset: bool = True) -> None:
        if getattr(self, "_quiet", False):
            return
        idx = None
        try:
            idx = self._current_index()
        except Exception:
            pass
        if idx is None:
            return
        if reset:
            self._search_offset = 0
        q = self.s_query.value
        mode = self.s_mode.value if q.strip() else "keyword"
        if mode != "keyword":
            self.s_results.value = R.wrap(R.empty("⏳", "Searching…", "The embedding model loads on the first semantic query."), standalone=False)
        try:
            res = idx.search(
                q, mode=mode, k=int(self.s_k.value), offset=self._search_offset,
                file_type=self.s_type.value or None, fuzzy=self.s_fuzzy.value,
                operator="and" if self.s_all.value else "or",
            )
        except Exception as ex:
            self.s_results.value = ""
            self._error(ex, "Search failed")
            return
        if not q.strip() and res.hits:
            overview = R.index_card(idx.stats(), standalone=False) if self._search_offset == 0 else ""
            note = R.callout("Browsing the first chunk of every file. Type a query above to search.", "info")
            self.s_results.value = overview + R.wrap(note, standalone=False) + R.results_html(res, standalone=False)
        else:
            self.s_results.value = R.results_html(res, standalone=False)
        pages = max(1, -(-res.total // int(self.s_k.value)))
        page = self._search_offset // int(self.s_k.value) + 1
        self.s_pager.layout.display = "" if res.total > int(self.s_k.value) else "none"
        self.s_prev.disabled = page <= 1
        self.s_next.disabled = page >= pages
        self.s_page.value = R.wrap(f"<span class='o-muted'>Page <b>{page}</b> of {pages:,}</span>", standalone=False)

    # ================================================================ CREATE
    def _build_create_tab(self) -> W.VBox:
        self.create_gate = W.HTML(R.wrap(R.callout("Not connected yet — you can configure everything now; the <b>⚙ Server</b> tab starts OpenSearch.", "warn"), standalone=False))
        # --- step 1: source
        self.c_kind = W.ToggleButtons(options=[("📁  Local folder", "local"), ("☁️  Amazon S3", "s3")], value="local", style={"button_width": "auto"})
        self.c_path = W.Text(placeholder="/home/sagemaker-user/my-docs", layout=W.Layout(flex="1 1 auto", width="auto"))
        self.c_scan = _btn("Scan", "o-primary")
        self.c_scan_out = W.HTML()
        self.c_kind.observe(self._on_kind, names="value")
        self.c_scan.on_click(lambda b: self._do_scan())
        self.c_path.observe(lambda c: self._suggest_name(), names="value")
        step1 = _panel(
            W.HTML(R.wrap(R.step("01", "Choose your data", "A folder on this machine or an S3 prefix — subfolders are included."), standalone=False)),
            self.c_kind, _row(self.c_path, self.c_scan, wrap=False), self.c_scan_out,
        )

        # --- step 2: configure
        self.c_name = W.Text(placeholder="my-index", layout=W.Layout(width="280px"))
        self._name_touched = False
        self.c_name.observe(self._on_name_typed, names="value")
        self.c_types_box = W.HBox([], layout=W.Layout(flex_flow="row wrap"))
        self._type_checks: Dict[str, W.Checkbox] = {}
        self.c_search = W.ToggleButtons(
            options=[("Keyword (BM25)", "keyword"), ("Keyword + Semantic", "semantic")], value="keyword",
            tooltips=["Fast exact-term search", "Adds vector embeddings for meaning-based & hybrid search"],
            style={"button_width": "auto"},
        )
        self.c_model = W.Dropdown(options=[(label, mid) for mid, (_, label) in EMBEDDING_MODELS.items()],
                                  value="sentence-transformers/all-MiniLM-L6-v2", layout=W.Layout(width="420px"))
        self.c_model_note = W.HTML()
        self.c_install = _btn("Install sentence-transformers", "o-quiet")
        self.c_install.on_click(lambda b: self._install_st())
        self.c_model_row = W.VBox([_field("Embedding model", self.c_model), _row(self.c_model_note, self.c_install)])
        self.c_search.observe(lambda c: self._on_semantic(), names="value")
        self.c_model.observe(lambda c: self._on_semantic(), names="value")
        self.c_chunk = W.IntSlider(value=1000, min=0, max=4000, step=100, continuous_update=False, readout=True, layout=W.Layout(width="360px"))
        self.c_overlap = W.IntSlider(value=150, min=0, max=1000, step=25, continuous_update=False, layout=W.Layout(width="360px"))
        self.c_chunk_hint = W.HTML()
        self.c_chunk.observe(lambda c: self._on_chunk(), names="value")
        self.c_analyzer = W.Dropdown(options=[(v, k) for k, v in ANALYZERS.items()], value="standard", layout=W.Layout(width="320px"))

        # advanced
        self.c_include = W.Text(placeholder="e.g. *.pdf, reports/**", layout=W.Layout(width="420px"))
        self.c_exclude = W.Text(value=", ".join(DEFAULT_EXCLUDE), layout=W.Layout(width="420px"))
        self.c_text_fields = W.Text(placeholder="all text columns", layout=W.Layout(width="420px"))
        self.c_title_field = W.Text(placeholder="auto (title, name, subject…)", layout=W.Layout(width="260px"))
        self.c_id_field = W.Text(placeholder="none", layout=W.Layout(width="260px"))
        self.c_max_mb = W.BoundedFloatText(value=100, min=1, max=10000, layout=W.Layout(width="120px"))
        self.c_shards = W.BoundedIntText(value=1, min=1, max=64, layout=W.Layout(width="120px"))
        self.c_replicas = W.BoundedIntText(value=0, min=0, max=5, layout=W.Layout(width="120px"))
        self.c_workers = W.IntSlider(value=8, min=1, max=32, layout=W.Layout(width="300px"))
        self.c_recreate = W.Checkbox(value=False, description="Replace the index if it already exists", indent=False, layout=W.Layout(width="auto"))
        adv = W.VBox([
            _field("Include", self.c_include, hint="comma-separated globs; empty = everything"),
            _field("Exclude", self.c_exclude),
            W.HTML(R.wrap("<div class='o-label' style='margin:14px 0 4px'>CSV / JSON / Parquet records</div>", standalone=False)),
            _field("Text columns", self.c_text_fields, hint="columns to search"),
            _field("Title column", self.c_title_field),
            _field("ID column", self.c_id_field, hint="stable ids make re-indexing idempotent"),
            W.HTML(R.wrap("<div class='o-label' style='margin:14px 0 4px'>Performance</div>", standalone=False)),
            _field("Max file size", self.c_max_mb, hint="MB"),
            _field("Parallel reads", self.c_workers),
            _field("Shards", self.c_shards),
            _field("Replicas", self.c_replicas, hint="keep 0 on a single node"),
        ])
        self.c_adv = W.Accordion(children=[adv], selected_index=None)
        _set_titles(self.c_adv, ["Advanced options"])

        step2 = _panel(
            W.HTML(R.wrap(R.step("02", "Configure", "Sensible defaults — tweak only what you need."), standalone=False)),
            _field("Index name", self.c_name),
            _field("File types", self.c_types_box),
            _field("Search type", self.c_search),
            self.c_model_row,
            _field("Chunk size", self.c_chunk, hint=""),
            _row(_label(""), self.c_chunk_hint),
            _field("Overlap", self.c_overlap, hint="characters shared by neighbouring chunks"),
            _field("Analyzer", self.c_analyzer),
            self.c_recreate,
            self.c_adv,
        )

        # --- step 3: build
        self.c_build = _btn("Build index", "o-primary", "o-big")
        self.c_cancel = _btn("Cancel", "o-danger")
        self.c_cancel.layout.display = "none"
        self.c_progress = W.HTML()
        self.c_stats = W.HTML()
        self.c_log = W.HTML()
        self.c_result = W.HTML()
        self.c_open = _btn("Search this index", "o-primary")
        self.c_open.layout.display = "none"
        self.c_open.layout.margin = "14px 0 0 0"
        self._cancel_event: Optional[threading.Event] = None
        self.c_build.on_click(lambda b: self._do_build())
        self.c_cancel.on_click(lambda b: self._cancel_event and self._cancel_event.set())
        self.c_open.on_click(lambda b: self._open_in_search(self._last_built))
        self._last_built = ""
        step3 = _panel(
            W.HTML(R.wrap(R.step("03", "Build", "Files are read in parallel, chunked and bulk-indexed."), standalone=False)),
            _row(self.c_build, self.c_cancel), self.c_progress, self.c_stats, self.c_log, self.c_result, _row(self.c_open),
        )
        self._on_kind({"new": "local"})
        self._on_semantic()
        self._on_chunk()
        return W.VBox([self.create_gate, step1, step2, step3])

    def _on_kind(self, change) -> None:
        if change["new"] == "s3":
            self.c_path.placeholder = "s3://my-bucket/path/to/docs/"
            if not self.c_path.value.startswith("s3://"):
                self.c_path.value = "s3://"
        else:
            self.c_path.placeholder = "/home/sagemaker-user/my-docs   or   ./data"
            if self.c_path.value.startswith("s3://"):
                self.c_path.value = ""

    def _on_name_typed(self, change) -> None:
        if not getattr(self, "_setting_name", False):
            self._name_touched = bool(change["new"])

    def _suggest_name(self) -> None:
        if self._name_touched:
            return
        from ..api import default_index_name

        path = self.c_path.value.strip()
        if not path or path == "s3://":
            return
        self._setting_name = True
        try:
            self.c_name.value = default_index_name(path)
        finally:
            self._setting_name = False

    def _on_chunk(self) -> None:
        v = self.c_chunk.value
        self.c_overlap.disabled = v == 0
        if v == 0:
            hint = "Each file / page / record is indexed whole."
        else:
            hint = f"≈ {max(1, v // 5):,} words per chunk — smaller chunks give more precise hits, larger ones more context."
        self.c_chunk_hint.value = R.wrap(f"<span class='o-muted' style='font-size:11.5px'>{hint}</span>", standalone=False)

    def _on_semantic(self) -> None:
        sem = self.c_search.value == "semantic"
        self.c_model_row.layout.display = "" if sem else "none"
        provider = EMBEDDING_MODELS.get(self.c_model.value, ("sentence-transformers",))[0]
        need_install = sem and provider == "sentence-transformers" and not module_available("sentence_transformers")
        self.c_install.layout.display = "" if need_install else "none"
        notes = []
        if need_install:
            notes.append("<b>sentence-transformers</b> is not installed in this kernel.")
        if provider == "bedrock":
            notes.append("Uses Amazon Bedrock with your AWS credentials (model access must be enabled in the Bedrock console).")
        else:
            notes.append("Runs locally; the model downloads once (~90–420 MB). A GPU is used automatically if present.")
        server = getattr(self.cluster, "server", None)
        if sem and server is not None and server.flavor != "full":
            notes.append("The local server will be upgraded to the distribution with the k-NN plugin (one-time ~1 GB download).")
        self.c_model_note.value = R.wrap(f"<span class='o-muted' style='font-size:11.5px'>{' '.join(notes)}</span>", standalone=False)

    def _install_st(self) -> None:
        self.c_install.disabled = True
        self.c_install.description = "Installing… (a few minutes)"

        def work():
            r = pip_install(["sentence-transformers"])
            if r.returncode != 0:
                raise RuntimeError(r.stderr[-2000:])
            import importlib

            importlib.invalidate_caches()
            self._notify("✓ sentence-transformers installed. You're ready to build a semantic index.", "ok")

        def done():
            self.c_install.disabled = False
            self.c_install.description = "Install sentence-transformers"
            self._on_semantic()

        self._run_bg(work, "Installing sentence-transformers failed", done)

    def _source_value(self) -> str:
        path = self.c_path.value.strip()
        if not path or path == "s3://":
            raise ValueError("Enter a folder path or an s3:// URI first.")
        return path

    def _do_scan(self) -> None:
        try:
            path = self._source_value()
        except ValueError as ex:
            self._notify(str(ex), "warn")
            return
        self.c_scan.disabled = True
        self.c_scan_out.value = R.wrap(R.empty("⏳", "Scanning…", e(path)), standalone=False)

        def work():
            from ..sources import resolve_source

            src = resolve_source(path)
            summary = src.scan(_csv(self.c_include.value), _csv(self.c_exclude.value), limit=200_000)
            self.c_scan_out.value = R.scan_card(summary, standalone=False)
            self._set_type_checks(summary.by_type)
            self._suggest_name()

        def done():
            self.c_scan.disabled = False

        def wrapped():
            try:
                work()
            except Exception:
                self.c_scan_out.value = ""
                raise

        self._run_bg(wrapped, f"Could not scan {path}", done)

    def _set_type_checks(self, by_type: Dict[str, int]) -> None:
        checks = []
        self._type_checks = {}
        for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
            supported = is_supported(t) or not t
            cb = W.Checkbox(value=supported, description=f"{t or 'no ext'} ({c:,})", indent=False,
                            disabled=not supported, layout=W.Layout(width="auto", margin="0 14px 0 0"))
            if not supported:
                cb.description += " – unsupported"
            self._type_checks[t] = cb
            checks.append(cb)
        self.c_types_box.children = checks

    def _build_config(self) -> IndexConfig:
        name = sanitize_index_name(self.c_name.value or "my-index")
        if name != self.c_name.value:
            self._setting_name = True
            self.c_name.value = name
            self._setting_name = False
        file_types = None
        if self._type_checks:
            chosen = [t for t, cb in self._type_checks.items() if cb.value and not cb.disabled]
            all_supported = all(cb.value for cb in self._type_checks.values() if not cb.disabled)
            if not chosen:
                raise ValueError("Select at least one file type.")
            file_types = None if all_supported else chosen
        overlap = min(self.c_overlap.value, max(0, self.c_chunk.value // 2)) if self.c_chunk.value else 0
        return IndexConfig(
            name=name,
            include=_csv(self.c_include.value),
            exclude=_csv(self.c_exclude.value),
            file_types=file_types,
            chunk_size=self.c_chunk.value,
            chunk_overlap=overlap,
            analyzer=self.c_analyzer.value,
            semantic=self.c_search.value == "semantic",
            embedding_model=self.c_model.value,
            text_fields=_csv(self.c_text_fields.value) or None,
            title_field=self.c_title_field.value.strip() or None,
            id_field=self.c_id_field.value.strip() or None,
            max_file_mb=float(self.c_max_mb.value),
            shards=int(self.c_shards.value),
            replicas=int(self.c_replicas.value),
            workers=int(self.c_workers.value),
        )

    def _do_build(self) -> None:
        if not self._connected():
            self._notify("Start or connect to OpenSearch in the <b>⚙ Server</b> tab first.", "warn")
            self.tabs.selected_index = 3
            return
        try:
            path = self._source_value()
            cfg = self._build_config()
        except Exception as ex:
            self._notify(e(str(ex)), "warn")
            return
        if self.cluster.exists(cfg.name) and not self.c_recreate.value:
            self._notify(f"Index <b>{e(cfg.name)}</b> already exists. Tick <i>Replace the index</i>, pick another name, or use <b>🗂 Indexes → Add files</b>.", "warn")
            return
        self._cancel_event = threading.Event()
        self.c_build.disabled = True
        self.c_cancel.layout.display = ""
        self.c_open.layout.display = "none"
        self.c_result.value = ""
        log_lines: List[str] = []
        progress = PanelProgress(self.c_progress)

        def on_event(ev: Dict[str, Any]) -> None:
            self.c_stats.value = R.wrap(R.stats([
                (f"{human_count(ev['files_done'])} / {human_count(ev['files_total'])}", "Files"),
                (human_count(ev["chunks"]), "Chunks"),
                (human_count(ev["errors"]), "Errors"),
                (human_duration(ev["elapsed"]), "Elapsed"),
            ]), standalone=False)
            msg = ev.get("message")
            if msg and (not log_lines or log_lines[-1] != msg):
                log_lines.append(msg)
                del log_lines[:-5]
                self.c_log.value = R.wrap(f"<div class='o-log'>{e(chr(10).join(log_lines))}</div>", standalone=False)

        def work():
            if cfg.semantic:
                progress.start(None, "Preparing semantic search")
                progress.note(f"Loading embedding model {cfg.embedding_model}…")
            idx = self.cluster.create_index(
                cfg.name, path, config=cfg, recreate=self.c_recreate.value,
                progress=lambda: progress, on_event=on_event, cancel=self._cancel_event,
            )
            report = idx.last_report
            self._last_built = cfg.name
            self.c_result.value = R.report_card(report, standalone=False)
            self.c_open.layout.display = ""
            self._set_index_options(self.cluster.index_names(), select=None)
            self._refresh_header()

        def done():
            self.c_build.disabled = False
            self.c_cancel.layout.display = "none"

        self._run_bg(work, f"Building index '{cfg.name}' failed", done)

    def _open_in_search(self, name: str) -> None:
        if not name:
            return
        self._set_index_options(self.cluster.index_names())
        self.s_index.value = name
        self._on_index_change()
        self.tabs.selected_index = 0

    # ================================================================ INDEXES
    def _build_indexes_tab(self) -> W.VBox:
        self.ix_table = W.HTML()
        self.ix_select = W.Dropdown(options=[], layout=W.Layout(width="260px"))
        self.ix_refresh = _btn("Refresh", "o-quiet")
        self.ix_open = _btn("Open in Search", "o-primary")
        self.ix_details = _btn("Details")
        self.ix_delete = _btn("Delete", "o-danger")
        self.ix_detail_out = W.HTML()
        self.ix_add_path = W.Text(placeholder="folder or s3://bucket/prefix to add / re-index", layout=W.Layout(flex="1 1 auto", width="auto"))
        self.ix_add = _btn("Add files")
        self.ix_add_progress = W.HTML()
        self._delete_armed = ""

        self.ix_refresh.on_click(lambda b: self._refresh_all())
        self.ix_open.on_click(lambda b: self._open_in_search(self.ix_select.value))
        self.ix_details.on_click(lambda b: self._show_details())
        self.ix_delete.on_click(lambda b: self._delete_index())
        self.ix_add.on_click(lambda b: self._add_files())
        self.ix_select.observe(lambda c: self._disarm_delete(), names="value")

        return W.VBox([
            _panel(W.HTML(R.wrap("<h3>Indexes on this cluster</h3>", standalone=False)), self.ix_table),
            _panel(
                _row(_label("Index", "48px"), self.ix_select, self.ix_open, self.ix_details, self.ix_refresh, self.ix_delete),
                _row(self.ix_add_path, self.ix_add, wrap=False),
                W.HTML(R.wrap("<span class='o-muted' style='font-size:11.5px'>Adding uses the index's original settings. Files already indexed are replaced, so re-running on an updated folder is safe.</span>", standalone=False)),
                self.ix_add_progress,
                self.ix_detail_out,
            ),
        ])

    def _refresh_indexes_table(self) -> None:
        if not self._connected():
            self.ix_table.value = R.wrap(R.empty("🔌", "Not connected", "Start OpenSearch in the ⚙ Server tab."), standalone=False)
            return
        try:
            self.ix_table.value = R.wrap(R.index_table(self.cluster.indexes()), standalone=False)
        except Exception as ex:
            self._error(ex, "Could not list indexes")

    def _show_details(self) -> None:
        name = self.ix_select.value
        if not name:
            return
        try:
            idx = self.cluster.index(name)
            self.ix_detail_out.value = R.index_card(idx.stats(), standalone=False) + R.results_html(idx.sample(3), standalone=False)
        except Exception as ex:
            self._error(ex, f"Could not load '{name}'")

    def _disarm_delete(self) -> None:
        self._delete_armed = ""
        self.ix_delete.description = "Delete"

    def _delete_index(self) -> None:
        name = self.ix_select.value
        if not name:
            return
        if self._delete_armed != name:
            self._delete_armed = name
            self.ix_delete.description = f"Click again to delete '{name}'"
            return
        try:
            self.cluster.delete_index(name)
            self._notify(f"Deleted index <b>{e(name)}</b>.", "ok")
            self.ix_detail_out.value = ""
        except Exception as ex:
            self._error(ex, f"Could not delete '{name}'")
        self._disarm_delete()
        self._refresh_all()

    def _add_files(self) -> None:
        name, path = self.ix_select.value, self.ix_add_path.value.strip()
        if not name or not path:
            self._notify("Pick an index and enter a folder or s3:// path to add.", "warn")
            return
        self.ix_add.disabled = True
        progress = PanelProgress(self.ix_add_progress)

        def work():
            report = self.cluster.index(name).add(path, progress=lambda: progress)
            self.ix_detail_out.value = R.report_card(report, standalone=False)
            self._refresh_indexes_table()

        def done():
            self.ix_add.disabled = False

        self._run_bg(work, f"Adding files to '{name}' failed", done)

    # ================================================================ SERVER
    def _build_server_tab(self) -> W.VBox:
        from ..server import LocalServer

        self.sv_card = W.HTML()
        self.sv_semantic = W.Checkbox(value=False, description="Include k-NN plugin (semantic & hybrid search, ~1 GB once)", indent=False, layout=W.Layout(width="auto"))
        self.sv_heap = W.Dropdown(options=["512m", "1g", "2g", "4g", "8g"], value="1g", layout=W.Layout(width="100px"))
        self.sv_port = W.BoundedIntText(value=9200, min=1024, max=65535, layout=W.Layout(width="110px"))
        self.sv_backend = W.Dropdown(options=[("Auto (Docker if available)", "auto"), ("Docker", "docker"), ("Tarball (no Docker)", "tarball")], value="auto", layout=W.Layout(width="230px"))
        self.sv_start = _btn("Start OpenSearch", "o-primary", "o-big")
        self.sv_stop = _btn("Stop", "o-danger")
        self.sv_logs_btn = _btn("Logs", "o-quiet")
        self.sv_progress = W.HTML()
        self.sv_logs = W.HTML()
        self.sv_start.on_click(lambda b: self._start_server())
        self.sv_stop.on_click(lambda b: self._stop_server())
        self.sv_logs_btn.on_click(lambda b: self._toggle_logs())

        local = _panel(
            W.HTML(R.wrap(R.step("⚡", "Local OpenSearch", "Runs on this machine. Data persists across kernel restarts."), standalone=False)),
            self.sv_card,
            _row(self.sv_semantic),
            _row(_label("Memory", "60px"), self.sv_heap, _label("Port", "36px"), self.sv_port, _label("Backend", "60px"), self.sv_backend),
            _row(self.sv_start, self.sv_stop, self.sv_logs_btn),
            self.sv_progress, self.sv_logs,
        )

        self.rc_url = W.Text(placeholder="https://search-my-domain.us-east-1.es.amazonaws.com", layout=W.Layout(flex="1 1 auto", width="auto"))
        self.rc_auth = W.Dropdown(options=[("Auto (AWS IAM for *.amazonaws.com)", "auto"), ("None", "none"), ("Username / password", "basic"), ("AWS IAM (SigV4)", "aws")], value="auto", layout=W.Layout(width="300px"))
        self.rc_user = W.Text(placeholder="username", layout=W.Layout(width="200px"))
        self.rc_pass = W.Password(placeholder="password", layout=W.Layout(width="200px"))
        self.rc_region = W.Text(placeholder="region (auto)", layout=W.Layout(width="160px"))
        self.rc_basic = _row(self.rc_user, self.rc_pass)
        self.rc_basic.layout.display = "none"
        self.rc_auth.observe(lambda c: setattr(self.rc_basic.layout, "display", "" if c["new"] == "basic" else "none"), names="value")
        self.rc_connect = _btn("Connect", "o-primary")
        self.rc_connect.on_click(lambda b: self._connect_remote())
        remote = _panel(
            W.HTML(R.wrap(R.step("☁️", "Existing cluster", "Amazon OpenSearch Service, Serverless, or any self-managed OpenSearch."), standalone=False)),
            _row(self.rc_url, self.rc_connect, wrap=False),
            _row(_label("Auth", "36px"), self.rc_auth, self.rc_region),
            self.rc_basic,
        )
        self._LocalServer = LocalServer
        return W.VBox([local, remote])

    def _local_server(self):
        if self.cluster is not None and self.cluster.server is not None:
            return self.cluster.server
        return self._LocalServer(port=int(self.sv_port.value))

    def _refresh_server_panel(self) -> None:
        try:
            server = self._local_server()
            st = server.status()
        except Exception as ex:
            self.sv_card.value = R.wrap(R.callout(e(str(ex)), "err"), standalone=False)
            return
        self.sv_card.value = R.server_card(st, standalone=False)
        running = st["running"]
        self.sv_start.description = "Running" if running else "Start OpenSearch"
        self.sv_start.disabled = running and (st["semantic"] or not self.sv_semantic.value)
        self.sv_stop.disabled = not running
        if st.get("semantic"):
            self.sv_semantic.value = True

    def _start_server(self) -> None:
        from ..api import Cluster

        self.sv_start.disabled = True
        progress = PanelProgress(self.sv_progress)

        def work():
            server = self._LocalServer(
                flavor="full" if self.sv_semantic.value else "min", heap=self.sv_heap.value,
                port=int(self.sv_port.value), backend=self.sv_backend.value,
            )
            server.start(progress=lambda: progress)
            self.cluster = Cluster(server.client(), server=server)
            import osss

            osss._current = self.cluster
            self._notify(f"✓ OpenSearch is running at <code>{e(server.url)}</code>.", "ok")
            self._refresh_all()
            if not self.cluster.index_names():
                self.tabs.selected_index = 1

        self._run_bg(work, "Could not start OpenSearch", self._refresh_server_panel)

    def _stop_server(self) -> None:
        try:
            self._local_server().stop()
            self._notify("OpenSearch stopped. Your indexes are kept on disk.", "info")
        except Exception as ex:
            self._error(ex, "Could not stop OpenSearch")
        self._refresh_all()

    def _toggle_logs(self) -> None:
        if self.sv_logs.value:
            self.sv_logs.value = ""
            return
        text = self._local_server().logs(60) or "(no logs yet)"
        self.sv_logs.value = R.wrap(f"<div class='o-log' style='max-height:300px'>{e(text)}</div>", standalone=False)

    def _connect_remote(self) -> None:
        from ..api import Cluster
        from ..client import connect

        url = self.rc_url.value.strip()
        if not url:
            self._notify("Enter the cluster URL.", "warn")
            return
        kw: Dict[str, Any] = {}
        auth = self.rc_auth.value
        if auth == "basic":
            kw.update(username=self.rc_user.value, password=self.rc_pass.value)
        elif auth == "aws":
            kw.update(aws_auth=True)
        elif auth == "none":
            kw.update(aws_auth=False)
        if self.rc_region.value.strip():
            kw["aws_region"] = self.rc_region.value.strip()
        self.rc_connect.disabled = True

        def work():
            client = connect(url, **kw)
            client.info()
            self.cluster = Cluster(client, url=url)
            import osss

            osss._current = self.cluster
            self._notify(f"✓ Connected to <code>{e(url)}</code>.", "ok")
            self._refresh_all()
            self.tabs.selected_index = 0 if self.cluster.index_names() else 1

        def done():
            self.rc_connect.disabled = False

        self._run_bg(work, f"Could not connect to {url}", done)
