"""Scoped CSS for osss notebook output.

A deliberately quiet design: one ink colour, hairline rules, typographic
hierarchy and generous whitespace. Everything is scoped under ``.osss`` and
built on JupyterLab theme variables, so light and dark themes (SageMaker
Studio, JupyterLab, VS Code) are followed automatically.
"""

CSS = """
<style>
.osss {
  --o-bg: var(--jp-layout-color0, #ffffff);
  --o-subtle: var(--jp-layout-color2, #f6f6f5);
  --o-line: var(--jp-border-color2, #e6e6e3);
  --o-line-strong: var(--jp-border-color1, #cfcfcb);
  --o-fg: var(--jp-ui-font-color0, #18181b);
  --o-fg2: var(--jp-ui-font-color1, #3f3f46);
  --o-muted: var(--jp-ui-font-color2, #71717a);
  --o-faint: var(--jp-ui-font-color3, #a1a1aa);
  --o-ok: #15803d;
  --o-warn: #b45309;
  --o-err: #b91c1c;
  --o-mark: rgba(250, 204, 21, .28);
  --o-sans: var(--jp-ui-font-family, -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif);
  --o-mono: var(--jp-code-font-family, ui-monospace, "SF Mono", Menlo, Consolas, monospace);
  font-family: var(--o-sans);
  color: var(--o-fg2);
  font-size: 13px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
@media (prefers-color-scheme: dark) {
  .osss {
    --o-bg: var(--jp-layout-color0, #111113);
    --o-subtle: var(--jp-layout-color2, #1b1b1e);
    --o-line: var(--jp-border-color2, #2a2a2e);
    --o-line-strong: var(--jp-border-color1, #3a3a3f);
    --o-fg: var(--jp-ui-font-color0, #f4f4f5);
    --o-fg2: var(--jp-ui-font-color1, #d4d4d8);
    --o-muted: var(--jp-ui-font-color2, #a1a1aa);
    --o-faint: var(--jp-ui-font-color3, #71717a);
  }
}
body[data-jp-theme-light="false"] .osss, .vscode-dark .osss {
  --o-ok: #4ade80; --o-warn: #fbbf24; --o-err: #f87171; --o-mark: rgba(250, 204, 21, .22);
}
.osss * { box-sizing: border-box; }
.osss .o-muted { color: var(--o-muted); }
.osss .o-faint { color: var(--o-faint); }
.osss .o-ok { color: var(--o-ok); }
.osss .o-err { color: var(--o-err); }
.osss .o-mono, .osss code { font-family: var(--o-mono); font-size: 12px; }
.osss code { color: var(--o-fg2); }
.osss .o-label {
  font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--o-faint);
}
.osss h3 { margin: 0; font-size: 14px; font-weight: 600; color: var(--o-fg); letter-spacing: -.005em; }

/* header */
.osss .o-header {
  display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 2px 2px 14px; border-bottom: 1px solid var(--o-line);
}
.osss .o-brand { display: flex; align-items: baseline; gap: 12px; }
.osss .o-wordmark { font-size: 17px; font-weight: 650; color: var(--o-fg); letter-spacing: -.02em; }
.osss .o-tagline { font-size: 12.5px; color: var(--o-muted); }
.osss .o-status { display: inline-flex; align-items: center; gap: 8px; font-size: 12px; color: var(--o-muted); }
.osss .o-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--o-faint); display: inline-block; flex: none; }
.osss .o-dot.ok { background: var(--o-ok); }
.osss .o-dot.err { background: var(--o-err); }

/* sections */
.osss .o-section + .o-section { margin-top: 22px; }
.osss .o-step { display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px; }
.osss .o-step .n { font-family: var(--o-mono); font-size: 11.5px; color: var(--o-faint); }
.osss .o-step .t { font-size: 14px; font-weight: 600; color: var(--o-fg); }
.osss .o-step .s { font-size: 12.5px; color: var(--o-muted); margin-top: 1px; }

/* tags */
.osss .o-tag {
  display: inline-block; font-family: var(--o-mono); font-size: 11px; color: var(--o-muted);
  padding: 0 6px; border: 1px solid var(--o-line); border-radius: 4px; line-height: 18px; white-space: nowrap;
}
.osss .o-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.osss .o-tag b { color: var(--o-fg2); font-weight: 500; margin-left: 4px; }

/* stats */
.osss .o-stats { display: flex; flex-wrap: wrap; gap: 8px 40px; margin: 4px 0 2px; }
.osss .o-stat .v { font-size: 22px; font-weight: 500; color: var(--o-fg); letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1.25; }
.osss .o-stat .l { font-size: 10.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--o-faint); }

/* key / value */
.osss .o-kv { display: grid; grid-template-columns: max-content 1fr; gap: 5px 24px; font-size: 12.5px; margin: 0; }
.osss .o-kv dt { color: var(--o-muted); white-space: nowrap; }
.osss .o-kv dd { margin: 0; color: var(--o-fg2); word-break: break-word; }

/* callouts */
.osss .o-note {
  padding: 6px 12px; border-left: 2px solid var(--o-line-strong); background: transparent;
  font-size: 12.5px; color: var(--o-fg2); border-radius: 0 4px 4px 0; margin: 8px 0;
}
.osss .o-note.warn { border-left-color: var(--o-warn); }
.osss .o-note.err { border-left-color: var(--o-err); }
.osss .o-note.ok { border-left-color: var(--o-ok); }
.osss .o-empty { padding: 36px 8px; text-align: center; }
.osss .o-empty .t { font-size: 14px; font-weight: 600; color: var(--o-fg); }
.osss .o-empty .s { font-size: 12.5px; color: var(--o-muted); margin-top: 4px; }

/* results */
.osss .o-results-head {
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap;
  font-size: 12px; color: var(--o-muted); padding: 2px 0 10px; border-bottom: 1px solid var(--o-line);
}
.osss .o-results-head b { color: var(--o-fg); font-weight: 600; }
.osss .o-hit { padding: 16px 0 15px; border-bottom: 1px solid var(--o-line); }
.osss .o-hit-top { display: flex; align-items: baseline; gap: 12px; }
.osss .o-rank { font-family: var(--o-mono); font-size: 11px; color: var(--o-faint); min-width: 18px; font-variant-numeric: tabular-nums; }
.osss .o-title { flex: 1; min-width: 0; font-size: 14.5px; font-weight: 600; color: var(--o-fg); letter-spacing: -.005em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.osss .o-score { font-family: var(--o-mono); font-size: 11px; color: var(--o-faint); font-variant-numeric: tabular-nums; flex: none; }
.osss .o-meta { margin: 2px 0 7px 30px; font-family: var(--o-mono); font-size: 11.5px; color: var(--o-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.osss .o-meta .sep { color: var(--o-faint); margin: 0 6px; }
.osss .o-snippet { margin-left: 30px; color: var(--o-fg2); font-size: 13px; line-height: 1.65; max-width: 860px; word-wrap: break-word; }
.osss mark { background: var(--o-mark); color: inherit; padding: 0 1px; border-radius: 2px; }
.osss .o-fields { margin: 8px 0 0 30px; font-size: 12px; color: var(--o-muted); display: flex; flex-wrap: wrap; gap: 2px 16px; }
.osss .o-fields span b { font-weight: 500; color: var(--o-faint); margin-right: 5px; }
.osss details.o-more { margin: 6px 0 0 30px; }
.osss details.o-more summary { cursor: pointer; color: var(--o-faint); font-size: 12px; list-style: none; user-select: none; width: max-content; }
.osss details.o-more summary:hover { color: var(--o-fg2); }
.osss details.o-more summary::-webkit-details-marker { display: none; }
.osss details.o-more pre {
  white-space: pre-wrap; max-height: 320px; overflow: auto; background: var(--o-subtle); font-family: var(--o-mono);
  padding: 10px 12px; border-radius: 6px; font-size: 12px; margin: 6px 0 0; color: var(--o-fg2); max-width: 860px;
}

/* tables & file lists */
.osss table.o-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.osss table.o-table th {
  text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--o-faint);
  font-weight: 600; padding: 0 12px 8px 0; border-bottom: 1px solid var(--o-line); background: none;
}
.osss table.o-table td { padding: 10px 12px 10px 0; border-bottom: 1px solid var(--o-line); color: var(--o-fg2); background: none; }
.osss table.o-table td.name { color: var(--o-fg); font-weight: 500; }
.osss table.o-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.osss table.o-table tr:last-child td { border-bottom: 0; }
.osss .o-files { margin: 10px 0 0; padding: 0; list-style: none; font-size: 12px; max-height: 260px; overflow: auto; }
.osss .o-files li { display: flex; justify-content: space-between; gap: 16px; padding: 4px 0; border-top: 1px solid var(--o-line); color: var(--o-fg2); font-family: var(--o-mono); }
.osss .o-files li span:last-child { color: var(--o-faint); flex: none; }

/* progress */
.osss .o-progress-label { display: flex; justify-content: space-between; gap: 12px; font-size: 12.5px; color: var(--o-fg); margin-bottom: 6px; }
.osss .o-progress-label span { color: var(--o-muted); font-variant-numeric: tabular-nums; }
.osss .o-meter { height: 2px; background: var(--o-line); overflow: hidden; border-radius: 2px; }
.osss .o-meter i { display: block; height: 100%; background: var(--o-fg); transition: width .25s ease; }
.osss .o-meter.indeterminate i { width: 30% !important; animation: o-slide 1.2s ease-in-out infinite; }
.osss .o-meter.fail i { background: var(--o-err); }
@keyframes o-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(340%); } }
.osss .o-log {
  font-family: var(--o-mono); font-size: 11.5px; color: var(--o-muted); overflow: hidden;
  margin-top: 10px; white-space: pre-wrap; line-height: 1.6;
}

/* ---------- widget polish (scoped to the app) ---------- */
.osss-app { max-width: 1080px; padding: 4px 2px; --jp-widgets-inline-height: 32px; }
.osss-app .widget-dropdown > select { height: 32px !important; }
.osss-app .widget-label, .osss-app .widget-label-basic { color: var(--o-muted) !important; font-size: 12px; }
.osss-app .widget-text input, .osss-app .widget-textarea textarea, .osss-app .widget-dropdown select,
.osss-app .widget-inline-hbox input[type="number"] {
  border-radius: 6px !important; border: 1px solid var(--o-line-strong) !important; background: var(--o-bg) !important;
  color: var(--o-fg) !important; padding: 0 10px !important; min-height: 32px; font-size: 13px; box-shadow: none !important;
  font-family: var(--o-sans);
}
.osss-app .widget-text input::placeholder { color: var(--o-faint); }
.osss-app .widget-text input:focus, .osss-app .widget-textarea textarea:focus, .osss-app .widget-dropdown select:focus,
.osss-app .widget-inline-hbox input[type="number"]:focus {
  border-color: var(--o-fg) !important; outline: none;
}
.osss-app .o-search input { min-height: 42px !important; font-size: 15px !important; padding: 0 14px !important; }
.osss-app .jupyter-button, .osss-app .widget-button {
  border-radius: 6px !important; height: 32px; padding: 0 14px; font-weight: 500; font-size: 12.5px;
  background: transparent; color: var(--o-fg); border: 1px solid var(--o-line-strong); box-shadow: none !important;
  font-family: var(--o-sans); transition: background .12s, border-color .12s;
}
.osss-app .jupyter-button:hover:enabled, .osss-app .widget-button:hover:enabled { background: var(--o-subtle); border-color: var(--o-faint); }
.osss-app .jupyter-button:focus, .osss-app .widget-button:focus { outline: none; }
.osss-app .o-primary.jupyter-button, .osss-app .o-primary.widget-button {
  background: var(--o-fg) !important; color: var(--o-bg) !important; border-color: var(--o-fg) !important;
}
.osss-app .o-primary.jupyter-button:hover:enabled { opacity: .88; }
.osss-app .o-big.jupyter-button { height: 42px; padding: 0 20px; font-size: 13px; }
.osss-app .o-quiet.jupyter-button { border-color: transparent; color: var(--o-muted); }
.osss-app .o-quiet.jupyter-button:hover:enabled { color: var(--o-fg); background: var(--o-subtle); }
.osss-app .o-danger.jupyter-button { color: var(--o-err); border-color: transparent; }
.osss-app .o-danger.jupyter-button:hover:enabled { background: var(--o-subtle); border-color: var(--o-line); }
.osss-app .jupyter-button:disabled { opacity: .4; }
.osss-app .widget-toggle-buttons { gap: 0; }
.osss-app .widget-toggle-buttons .widget-toggle-button {
  height: 32px; margin: 0 0 0 -1px; padding: 0 14px; width: auto !important; min-width: 0;
  border-radius: 0 !important; border: 1px solid var(--o-line-strong); background: var(--o-bg); color: var(--o-muted);
  font-weight: 500; font-size: 12.5px; box-shadow: none !important; font-family: var(--o-sans);
}
.osss-app .widget-toggle-buttons .widget-toggle-button:first-child { border-radius: 6px 0 0 6px !important; margin-left: 0; }
.osss-app .widget-toggle-buttons .widget-toggle-button:last-child { border-radius: 0 6px 6px 0 !important; }
.osss-app .widget-toggle-buttons .widget-toggle-button:only-child { border-radius: 6px !important; }
.osss-app .widget-toggle-buttons .widget-toggle-button.mod-active {
  background: var(--o-subtle); color: var(--o-fg); font-weight: 600; position: relative; z-index: 1;
}
.osss-app .widget-checkbox input, .osss-app input[type="checkbox"] { accent-color: var(--o-fg); }
.osss-app .widget-checkbox .widget-label-basic span, .osss-app .widget-checkbox label { color: var(--o-fg2) !important; font-size: 12.5px; }
.osss-app .widget-slider .noUi-connect, .osss-app .widget-slider .ui-slider-range { background: var(--o-fg) !important; }
.osss-app .widget-slider .noUi-target, .osss-app .widget-slider .ui-slider { background: var(--o-line) !important; border: 0 !important; box-shadow: none !important; height: 2px !important; }
.osss-app .widget-slider .noUi-handle, .osss-app .widget-slider .ui-slider-handle {
  border: 1.5px solid var(--o-fg) !important; background: var(--o-bg) !important; box-shadow: none !important;
  width: 12px !important; height: 12px !important; border-radius: 50% !important; top: -5px !important; right: -6px !important;
}
.osss-app .widget-slider .noUi-handle:before, .osss-app .widget-slider .noUi-handle:after { display: none; }
.osss-app .widget-readout { color: var(--o-fg2) !important; font-variant-numeric: tabular-nums; font-size: 12.5px; }
.osss-app .widget-tab > .lm-TabBar, .osss-app .jupyter-widget-tab > .lm-TabBar, .osss-app .widget-tab > .p-TabBar {
  border-bottom: 1px solid var(--o-line); min-height: 40px;
}
.osss-app .lm-TabBar-content, .osss-app .p-TabBar-content { border: 0 !important; }
.osss-app .widget-tab > .lm-TabBar .lm-TabBar-tab, .osss-app .jupyter-widget-tab > .lm-TabBar .lm-TabBar-tab,
.osss-app .widget-tab > .p-TabBar .p-TabBar-tab {
  background: transparent !important; border: 0 !important; border-bottom: 1.5px solid transparent !important;
  min-width: 0 !important; flex: 0 0 auto !important; padding: 0 2px !important; margin-right: 26px !important;
  font-size: 13px; font-weight: 500; color: var(--o-muted) !important; font-family: var(--o-sans);
  height: 38px !important; min-height: 38px !important; max-height: 38px !important; line-height: 36px !important;
  margin-top: 0 !important; top: 0 !important; transform: none !important;
}
.osss-app .lm-TabBar-content, .osss-app .p-TabBar-content { align-items: flex-end; }
.osss-app .widget-tab > .lm-TabBar .lm-TabBar-tab:hover { color: var(--o-fg) !important; }
.osss-app .widget-tab > .lm-TabBar .lm-TabBar-tab.lm-mod-current, .osss-app .jupyter-widget-tab > .lm-TabBar .lm-TabBar-tab.lm-mod-current,
.osss-app .widget-tab > .p-TabBar .p-TabBar-tab.p-mod-current {
  color: var(--o-fg) !important; border-bottom-color: var(--o-fg) !important; transform: none !important;
}
.osss-app .lm-TabBar-tab.lm-mod-current:before, .osss-app .p-TabBar-tab.p-mod-current:before { display: none !important; }
.osss-app .widget-tab-contents, .osss-app .jupyter-widget-tab > .widget-tab-contents {
  border: 0 !important; background: transparent !important; padding: 22px 0 0 !important; box-shadow: none !important; overflow: visible;
}
.osss-app .lm-Collapse-header, .osss-app .jupyter-widget-Collapse-header, .osss-app .p-Collapse-header {
  background: transparent !important; border: 0 !important; border-top: 1px solid var(--o-line) !important;
  color: var(--o-fg2) !important; font-weight: 500; font-size: 12.5px; padding: 10px 0 !important;
}
.osss-app .lm-Collapse-contents, .osss-app .jupyter-widget-Collapse-contents, .osss-app .p-Collapse-contents {
  border: 0 !important; background: transparent !important; padding: 6px 0 4px !important;
}
.osss-app .widget-html-content { font-size: 13px; line-height: 1.55; }
.osss-app .o-panel { padding: 20px 22px !important; border: 1px solid var(--o-line); border-radius: 8px; margin-bottom: 14px !important; background: var(--o-bg); }
.osss-app .o-flat { padding: 0 !important; }
</style>
"""
