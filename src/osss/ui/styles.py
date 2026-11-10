"""Scoped CSS for osss notebook output.

A deliberately quiet design: one ink colour, hairline rules, typographic
hierarchy and generous whitespace. Colour is reserved for state (healthy,
warning, error) and for search-term highlights. Everything is scoped under
``.osss`` and built on JupyterLab theme variables, so light and dark themes
(SageMaker Studio, JupyterLab, VS Code) are followed automatically.
"""

CSS = """
<style>
.osss {
  --o-bg: var(--jp-layout-color0, #ffffff);
  --o-raised: var(--jp-layout-color0, #ffffff);
  /* tints derived from the theme's own ink/background, so they sit right in any theme */
  --o-subtle: color-mix(in srgb, var(--o-fg) 5%, var(--o-bg));
  --o-hover: color-mix(in srgb, var(--o-fg) 7%, var(--o-bg));
  --o-line: var(--jp-border-color2, #e7e7e4);
  --o-line-strong: var(--jp-border-color1, #d2d2ce);
  --o-fg: var(--jp-ui-font-color0, #18181b);
  --o-fg2: var(--jp-ui-font-color1, #3f3f46);
  --o-muted: var(--jp-ui-font-color2, #71717a);
  --o-faint: var(--jp-ui-font-color3, #a1a1aa);
  --o-ok: #15803d;
  --o-warn: #b45309;
  --o-err: #b91c1c;
  --o-ok-soft: rgba(21, 128, 61, .10);
  --o-warn-soft: rgba(180, 83, 9, .08);
  --o-err-soft: rgba(185, 28, 28, .07);
  --o-mark: rgba(250, 204, 21, .30);
  --o-shadow: 0 1px 2px rgba(0, 0, 0, .06), 0 0 0 1px var(--o-line);
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
    --o-raised: var(--jp-layout-color1, #1a1a1d);
    --o-line: var(--jp-border-color2, #2a2a2e);
    --o-line-strong: var(--jp-border-color1, #3a3a3f);
    --o-fg: var(--jp-ui-font-color0, #f4f4f5);
    --o-fg2: var(--jp-ui-font-color1, #d4d4d8);
    --o-muted: var(--jp-ui-font-color2, #a1a1aa);
    --o-faint: var(--jp-ui-font-color3, #71717a);
    --o-ok: #4ade80; --o-warn: #fbbf24; --o-err: #f87171; --o-mark: rgba(250, 204, 21, .22);
    --o-ok-soft: rgba(74, 222, 128, .12); --o-warn-soft: rgba(251, 191, 36, .10); --o-err-soft: rgba(248, 113, 113, .10);
    --o-shadow: 0 0 0 1px var(--o-line-strong);
  }
}
body[data-jp-theme-light="false"] .osss, .vscode-dark .osss, .vscode-high-contrast .osss {
  --o-raised: var(--jp-layout-color1, #1a1a1d);
  --o-ok: #4ade80; --o-warn: #fbbf24; --o-err: #f87171; --o-mark: rgba(250, 204, 21, .22);
  --o-ok-soft: rgba(74, 222, 128, .12); --o-warn-soft: rgba(251, 191, 36, .10); --o-err-soft: rgba(248, 113, 113, .10);
  --o-shadow: 0 0 0 1px var(--o-line-strong);
}
.osss * { box-sizing: border-box; }
.osss .o-muted { color: var(--o-muted); }
.osss .o-faint { color: var(--o-faint); }
.osss .o-ok { color: var(--o-ok); }
.osss .o-err { color: var(--o-err); }
.osss .o-mono, .osss code { font-family: var(--o-mono); font-size: 12px; }
.osss code { color: var(--o-fg2); background: none; padding: 0; }
.osss .o-label {
  font-size: 10.5px; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: var(--o-faint);
}
.osss .o-hint { font-size: 12px; color: var(--o-muted); line-height: 1.5; }
.osss h3 { margin: 0; font-size: 14px; font-weight: 600; color: var(--o-fg); letter-spacing: -.005em; line-height: 1.4; }
.osss .o-icon { width: 16px; height: 16px; flex: none; display: inline-block; vertical-align: -3px; }
.osss .o-icon * { fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }

/* header */
.osss .o-header {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 2px 2px 14px; border-bottom: 1px solid var(--o-line);
}
.osss .o-brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.osss .o-logo { width: 22px; height: 22px; flex: none; }
.osss .o-logo rect { fill: var(--o-fg); }
.osss .o-logo circle, .osss .o-logo path { fill: none; stroke: var(--o-bg); stroke-width: 2.6; stroke-linecap: round; }
.osss .o-wordmark { font-size: 16px; font-weight: 650; color: var(--o-fg); letter-spacing: -.02em; }
.osss .o-tagline { font-size: 12.5px; color: var(--o-muted); padding-left: 10px; border-left: 1px solid var(--o-line); }
.osss .o-status {
  display: inline-flex; align-items: center; gap: 8px; font-size: 12px; color: var(--o-muted);
  padding: 3px 10px 3px 9px; border: 1px solid var(--o-line); border-radius: 999px; font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.osss .o-status b { color: var(--o-fg2); font-weight: 500; }
.osss .o-status .sep { color: var(--o-faint); }
.osss .o-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--o-faint); display: inline-block; flex: none; }
.osss .o-dot.ok { background: var(--o-ok); box-shadow: 0 0 0 3px var(--o-ok-soft); }
.osss .o-dot.warn { background: var(--o-warn); box-shadow: 0 0 0 3px var(--o-warn-soft); }
.osss .o-dot.err { background: var(--o-err); box-shadow: 0 0 0 3px var(--o-err-soft); }

/* sections */
.osss .o-section + .o-section { margin-top: 22px; }
.osss .o-step { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 8px; }
.osss .o-step .n {
  font-family: var(--o-mono); font-size: 11px; color: var(--o-muted); font-variant-numeric: tabular-nums;
  width: 22px; height: 22px; line-height: 20px; text-align: center; flex: none;
  border: 1px solid var(--o-line-strong); border-radius: 50%;
}
.osss .o-step .t { font-size: 14px; font-weight: 600; color: var(--o-fg); line-height: 22px; }
.osss .o-step .s { font-size: 12.5px; color: var(--o-muted); margin-top: 1px; }

/* tags */
.osss .o-tag {
  display: inline-flex; align-items: center; gap: 5px; font-family: var(--o-mono); font-size: 11px; color: var(--o-muted);
  padding: 0 7px; border: 1px solid var(--o-line); border-radius: 4px; line-height: 19px; white-space: nowrap;
  background: var(--o-bg); font-variant-numeric: tabular-nums;
}
.osss .o-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.osss .o-tag b { color: var(--o-fg2); font-weight: 500; }
.osss .o-tag.solid { background: var(--o-subtle); border-color: transparent; color: var(--o-fg2); }

/* stats */
.osss .o-stats { display: flex; flex-wrap: wrap; gap: 8px 44px; margin: 2px 0; }
.osss .o-stat .v { font-size: 22px; font-weight: 500; color: var(--o-fg); letter-spacing: -.02em; font-variant-numeric: tabular-nums; line-height: 1.25; }
.osss .o-stat .l { font-size: 10.5px; font-weight: 600; letter-spacing: .07em; text-transform: uppercase; color: var(--o-faint); margin-top: 2px; }

/* key / value */
.osss .o-kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px 28px; font-size: 12.5px; margin: 0; }
.osss .o-kv dt { color: var(--o-muted); white-space: nowrap; font-weight: 400; margin: 0; }
.osss .o-kv dd { margin: 0; color: var(--o-fg2); word-break: break-word; }

/* callouts */
.osss .o-note {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 9px 12px; border: 1px solid var(--o-line); background: transparent;
  font-size: 12.5px; color: var(--o-fg2); border-radius: 6px; margin: 10px 0; line-height: 1.5;
}
.osss .o-note > .o-icon { margin-top: 1px; color: var(--o-muted); }
.osss .o-note > div { min-width: 0; flex: 1; }
.osss .o-note.warn { background: var(--o-warn-soft); border-color: transparent; }
.osss .o-note.warn > .o-icon { color: var(--o-warn); }
.osss .o-note.err { background: var(--o-err-soft); border-color: transparent; }
.osss .o-note.err > .o-icon { color: var(--o-err); }
.osss .o-note.ok { background: var(--o-ok-soft); border-color: transparent; }
.osss .o-note.ok > .o-icon { color: var(--o-ok); }
.osss .o-note details.o-more { margin-left: 0; }

/* empty / loading states */
.osss .o-empty {
  padding: 40px 16px; text-align: center; border: 1px dashed var(--o-line-strong); border-radius: 10px;
  display: flex; flex-direction: column; align-items: center;
}
.osss .o-empty .o-icon { width: 20px; height: 20px; color: var(--o-faint); margin-bottom: 10px; }
.osss .o-empty .t { font-size: 13.5px; font-weight: 600; color: var(--o-fg); }
.osss .o-empty .s { font-size: 12.5px; color: var(--o-muted); margin-top: 4px; max-width: 460px; }
.osss .o-spin {
  width: 16px; height: 16px; border-radius: 50%; border: 1.5px solid var(--o-line-strong); border-top-color: var(--o-fg);
  animation: o-rot .7s linear infinite; margin-bottom: 12px;
}
@keyframes o-rot { to { transform: rotate(360deg); } }

/* results */
.osss .o-results-head {
  display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
  font-size: 12px; color: var(--o-muted); padding: 2px 0 10px; border-bottom: 1px solid var(--o-line);
  font-variant-numeric: tabular-nums;
}
.osss .o-results-head b { color: var(--o-fg); font-weight: 600; }
.osss .o-results-head .r { display: inline-flex; align-items: center; gap: 8px; }
.osss .o-hit { padding: 16px 0 15px; border-bottom: 1px solid var(--o-line); }
.osss .o-hit-top { display: flex; align-items: baseline; gap: 12px; }
.osss .o-rank { font-family: var(--o-mono); font-size: 11px; color: var(--o-faint); min-width: 18px; font-variant-numeric: tabular-nums; }
.osss .o-title { flex: 1; min-width: 0; font-size: 14.5px; font-weight: 600; color: var(--o-fg); letter-spacing: -.008em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.osss .o-score { font-family: var(--o-mono); font-size: 11px; color: var(--o-faint); font-variant-numeric: tabular-nums; flex: none; }
.osss .o-meta { display: flex; align-items: center; gap: 8px; margin: 4px 0 8px 30px; font-size: 12px; color: var(--o-muted); min-width: 0; }
.osss .o-meta .p { font-family: var(--o-mono); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.osss .o-meta .x { white-space: nowrap; color: var(--o-faint); }
.osss .o-meta .sep { color: var(--o-faint); }
.osss .o-snippet { margin-left: 30px; color: var(--o-fg2); font-size: 13px; line-height: 1.65; max-width: 860px; word-wrap: break-word; }
.osss mark { background: var(--o-mark); color: inherit; padding: 0 2px; margin: 0 -1px; border-radius: 3px; }
.osss .o-fields { margin: 10px 0 0 30px; font-size: 12px; color: var(--o-fg2); display: flex; flex-wrap: wrap; gap: 6px; }
.osss .o-fields span { display: inline-flex; gap: 6px; padding: 1px 8px; border-radius: 4px; background: var(--o-subtle); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.osss .o-fields span b { font-weight: 400; color: var(--o-muted); }
.osss details.o-more { margin: 8px 0 0 30px; }
.osss details.o-more summary {
  cursor: pointer; color: var(--o-muted); font-size: 12px; list-style: none; user-select: none; width: max-content;
  display: inline-flex; align-items: center; gap: 6px;
}
.osss details.o-more summary::before {
  content: ""; width: 5px; height: 5px; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg); transition: transform .15s ease; margin-right: 1px;
}
.osss details.o-more[open] summary::before { transform: rotate(45deg); }
.osss details.o-more summary:hover { color: var(--o-fg); }
.osss details.o-more summary::-webkit-details-marker { display: none; }
.osss details.o-more pre {
  white-space: pre-wrap; max-height: 320px; overflow: auto; background: var(--o-subtle); font-family: var(--o-mono);
  padding: 12px 14px; border-radius: 6px; font-size: 12px; margin: 8px 0 0; color: var(--o-fg2); max-width: 860px; line-height: 1.6;
}

/* tables & file lists */
.osss table.o-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.osss table.o-table th {
  text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em; color: var(--o-faint);
  font-weight: 600; padding: 0 16px 8px 0; border-bottom: 1px solid var(--o-line); background: none;
}
.osss table.o-table td { padding: 11px 16px 11px 0; border-bottom: 1px solid var(--o-line); color: var(--o-fg2); background: none; }
.osss table.o-table th:last-child, .osss table.o-table td:last-child { padding-right: 0; }
.osss table.o-table tbody tr:hover td { background: none; }
.osss table.o-table td.name { color: var(--o-fg); font-weight: 500; }
.osss table.o-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.osss table.o-table tr:last-child td { border-bottom: 0; }
.osss .o-health { display: inline-flex; align-items: center; gap: 8px; }
/* !important: JupyterLab's rendered-HTML rules (``.jp-RenderedHTMLCommon ul``) are more specific */
.osss ul.o-files { margin: 12px 0 0 !important; padding: 0 !important; list-style: none !important; font-size: 12px; max-height: 260px; overflow: auto; }
.osss ul.o-files li { margin: 0 !important; }
.osss .o-files li { display: flex; justify-content: space-between; gap: 16px; padding: 6px 0; border-top: 1px solid var(--o-line); color: var(--o-fg2); }
.osss .o-files li span:first-child { font-family: var(--o-mono); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.osss .o-files li span:last-child { color: var(--o-faint); flex: none; font-variant-numeric: tabular-nums; }
.osss .o-files li.off span:first-child { color: var(--o-faint); text-decoration: line-through; text-decoration-color: var(--o-line-strong); }
.osss .o-files li.more span:first-child { font-family: var(--o-sans); color: var(--o-faint); }

/* progress */
.osss .o-progress-label { display: flex; justify-content: space-between; align-items: center; gap: 12px; font-size: 12.5px; color: var(--o-fg); margin-bottom: 8px; }
.osss .o-progress-label > span:first-child { display: inline-flex; align-items: center; gap: 7px; font-weight: 500; }
.osss .o-progress-label > span:last-child { color: var(--o-muted); font-variant-numeric: tabular-nums; }
.osss .o-meter { height: 4px; background: var(--o-subtle); box-shadow: inset 0 0 0 1px var(--o-line); overflow: hidden; border-radius: 4px; }
.osss .o-meter i { display: block; height: 100%; background: var(--o-fg); border-radius: 4px; transition: width .25s ease; }
.osss .o-meter.indeterminate i { width: 30% !important; animation: o-slide 1.2s ease-in-out infinite; }
.osss .o-meter.done i { background: var(--o-ok); }
.osss .o-meter.fail i { background: var(--o-err); }
@keyframes o-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(340%); } }
.osss .o-progress-msg { font-size: 12px; color: var(--o-muted); margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.osss .o-log {
  font-family: var(--o-mono); font-size: 11.5px; color: var(--o-muted); overflow: auto;
  margin-top: 10px; white-space: pre-wrap; line-height: 1.6; background: var(--o-subtle); border-radius: 6px; padding: 10px 12px;
}

/* ---------- widget polish (scoped to the app) ---------- */
.osss-app { max-width: 1080px; padding: 4px 2px; --jp-widgets-inline-height: 32px; }
.osss-app .widget-label, .osss-app .widget-label-basic { color: var(--o-muted) !important; font-size: 12px; }
.osss-app .widget-text input, .osss-app .widget-textarea textarea, .osss-app .widget-dropdown select,
.osss-app .widget-inline-hbox input[type="number"], .osss-app .widget-password input {
  border-radius: 6px !important; border: 1px solid var(--o-line-strong) !important; background: var(--o-bg) !important;
  color: var(--o-fg) !important; padding: 0 10px !important; height: 32px !important; min-height: 32px; font-size: 13px;
  box-shadow: none !important; font-family: var(--o-sans); transition: border-color .12s, box-shadow .12s;
}
.osss-app .widget-dropdown select {
  -webkit-appearance: none; appearance: none; padding-right: 30px !important; cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%238a8a90' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") !important;
  background-repeat: no-repeat !important; background-position: right 11px center !important;
}
.osss-app .widget-dropdown select:disabled, .osss-app .widget-text input:disabled { opacity: .5; cursor: default; }
.osss-app .widget-text input::placeholder, .osss-app .widget-password input::placeholder { color: var(--o-faint); }
.osss-app .widget-text input:hover, .osss-app .widget-dropdown select:hover,
.osss-app .widget-inline-hbox input[type="number"]:hover { border-color: var(--o-faint) !important; }
.osss-app .widget-text input:focus, .osss-app .widget-textarea textarea:focus, .osss-app .widget-dropdown select:focus,
.osss-app .widget-inline-hbox input[type="number"]:focus, .osss-app .widget-password input:focus {
  border-color: var(--o-fg) !important; outline: none; box-shadow: 0 0 0 3px var(--o-subtle) !important;
}
.osss-app .o-search input { height: 42px !important; min-height: 42px !important; font-size: 14.5px !important; padding: 0 14px !important; }

/* buttons */
.osss-app .jupyter-button, .osss-app .widget-button {
  border-radius: 6px !important; height: 32px; padding: 0 14px; font-weight: 500; font-size: 12.5px; line-height: 30px;
  background: var(--o-bg); color: var(--o-fg); border: 1px solid var(--o-line-strong); box-shadow: none !important;
  font-family: var(--o-sans); transition: background .12s, border-color .12s, opacity .12s, color .12s; white-space: nowrap;
}
.osss-app .jupyter-button:hover:enabled, .osss-app .widget-button:hover:enabled { background: var(--o-hover); border-color: var(--o-faint); }
.osss-app .jupyter-button:focus, .osss-app .widget-button:focus { outline: none; }
.osss-app .jupyter-button:focus-visible, .osss-app .widget-button:focus-visible { outline: 2px solid var(--o-fg); outline-offset: 2px; }
.osss-app .o-primary.jupyter-button, .osss-app .o-primary.widget-button {
  background: var(--o-fg) !important; color: var(--o-bg) !important; border-color: var(--o-fg) !important;
}
.osss-app .o-primary.jupyter-button:hover:enabled { opacity: .86; }
.osss-app .o-big.jupyter-button { height: 42px; line-height: 40px; padding: 0 20px; font-size: 13px; }
.osss-app .o-quiet.jupyter-button { border-color: transparent; background: transparent; color: var(--o-muted); }
.osss-app .o-quiet.jupyter-button:hover:enabled { color: var(--o-fg); background: var(--o-hover); border-color: transparent; }
.osss-app .o-danger.jupyter-button { color: var(--o-err); border-color: transparent; background: transparent; }
.osss-app .o-danger.jupyter-button:hover:enabled { background: var(--o-err-soft); border-color: transparent; }
.osss-app .o-danger.o-armed.jupyter-button { background: var(--o-err) !important; color: #fff !important; border-color: var(--o-err) !important; }
.osss-app .jupyter-button:disabled { opacity: .4; cursor: default; }
.osss-app .jupyter-button i.fa { margin-right: 6px; }

/* segmented control (ToggleButtons) */
.osss-app .widget-toggle-buttons { gap: 0; }
.osss-app .widget-toggle-buttons > div {
  display: inline-flex; gap: 2px; padding: 2px; background: var(--o-subtle); border: 1px solid var(--o-line); border-radius: 7px;
}
.osss-app .widget-toggle-buttons .widget-toggle-button {
  height: 26px; line-height: 26px; margin: 0; padding: 0 12px; width: auto !important; min-width: 0;
  border-radius: 5px !important; border: 0; background: transparent; color: var(--o-muted);
  font-weight: 500; font-size: 12.5px; box-shadow: none !important; font-family: var(--o-sans);
}
.osss-app .widget-toggle-buttons .widget-toggle-button:hover:enabled { background: transparent; color: var(--o-fg); border: 0; }
.osss-app .widget-toggle-buttons .widget-toggle-button.mod-active,
.osss-app .widget-toggle-buttons .widget-toggle-button.mod-active:hover:enabled {
  background: var(--o-raised); color: var(--o-fg); box-shadow: var(--o-shadow) !important;
}

/* checkboxes */
.osss-app .widget-checkbox { height: 32px; align-items: center; }
.osss-app .widget-checkbox .widget-label-basic { display: inline-flex !important; align-items: center; gap: 8px; cursor: pointer; margin: 0; }
.osss-app .widget-checkbox input[type="checkbox"] { margin: 0; width: 14px; height: 14px; flex: none; accent-color: var(--o-fg); cursor: pointer; }
.osss-app .widget-checkbox .widget-label-basic span, .osss-app .widget-checkbox label { color: var(--o-fg2) !important; font-size: 12.5px; }
.osss-app .widget-checkbox input:disabled + span { color: var(--o-faint) !important; }
.osss-app .o-chips .widget-checkbox { height: 28px; padding: 0 10px; margin: 0 6px 6px 0 !important; border: 1px solid var(--o-line); border-radius: 6px; }
.osss-app .o-chips .widget-checkbox .widget-label-basic span { font-family: var(--o-mono); font-size: 11.5px; }

/* sliders */
.osss-app .widget-slider .noUi-connect, .osss-app .widget-slider .ui-slider-range { background: var(--o-fg) !important; }
.osss-app .widget-slider .noUi-target, .osss-app .widget-slider .ui-slider { background: var(--o-line-strong) !important; border: 0 !important; box-shadow: none !important; height: 2px !important; }
.osss-app .widget-slider .noUi-handle, .osss-app .widget-slider .ui-slider-handle {
  border: 1.5px solid var(--o-fg) !important; background: var(--o-bg) !important; box-shadow: none !important; cursor: grab;
  width: 14px !important; height: 14px !important; border-radius: 50% !important; top: -6px !important; right: -7px !important;
}
.osss-app .widget-slider .noUi-handle:before, .osss-app .widget-slider .noUi-handle:after { display: none; }
.osss-app .widget-slider.mod-disabled, .osss-app .widget-slider [disabled] { opacity: .45; }
.osss-app .widget-readout {
  color: var(--o-fg) !important; font-variant-numeric: tabular-nums; font-size: 12.5px; font-family: var(--o-mono);
  min-width: 52px; text-align: right; border: 0 !important; outline: none;
}

/* tabs */
.osss-app .widget-tab > .lm-TabBar, .osss-app .jupyter-widget-tab > .lm-TabBar, .osss-app .widget-tab > .p-TabBar {
  border-bottom: 1px solid var(--o-line); min-height: 42px;
}
.osss-app .lm-TabBar-content, .osss-app .p-TabBar-content { border: 0 !important; align-items: flex-end; }
.osss-app .widget-tab > .lm-TabBar .lm-TabBar-tab, .osss-app .jupyter-widget-tab > .lm-TabBar .lm-TabBar-tab,
.osss-app .widget-tab > .p-TabBar .p-TabBar-tab {
  background: transparent !important; border: 0 !important; border-bottom: 2px solid transparent !important;
  min-width: 0 !important; flex: 0 0 auto !important; padding: 0 2px !important; margin: 0 24px -1px 0 !important;
  font-size: 13px; font-weight: 500; color: var(--o-muted) !important; font-family: var(--o-sans);
  height: 40px !important; min-height: 40px !important; max-height: 40px !important; line-height: 38px !important;
  top: 0 !important; transform: none !important; cursor: pointer;
}
.osss-app .lm-TabBar-tabIcon, .osss-app .p-TabBar-tabIcon { display: none; }
.osss-app .widget-tab > .lm-TabBar .lm-TabBar-tab:hover { color: var(--o-fg) !important; }
.osss-app .widget-tab > .lm-TabBar .lm-TabBar-tab.lm-mod-current, .osss-app .jupyter-widget-tab > .lm-TabBar .lm-TabBar-tab.lm-mod-current,
.osss-app .widget-tab > .p-TabBar .p-TabBar-tab.p-mod-current {
  color: var(--o-fg) !important; border-bottom-color: var(--o-fg) !important; transform: none !important;
}
.osss-app .lm-TabBar-tab.lm-mod-current:before, .osss-app .p-TabBar-tab.p-mod-current:before { display: none !important; }
.osss-app .widget-tab-contents, .osss-app .jupyter-widget-tab > .widget-tab-contents {
  border: 0 !important; background: transparent !important; padding: 20px 0 0 !important; box-shadow: none !important; overflow: visible;
}

/* accordion */
.osss-app .lm-Collapse-header, .osss-app .jupyter-widget-Collapse-header, .osss-app .p-Collapse-header {
  background: transparent !important; border: 0 !important; border-top: 1px solid var(--o-line) !important;
  color: var(--o-fg2) !important; font-weight: 500; font-size: 12.5px; padding: 12px 0 !important; cursor: pointer;
}
.osss-app .lm-Collapse-header:hover, .osss-app .jupyter-widget-Collapse-header:hover { color: var(--o-fg) !important; }
.osss-app .lm-Collapse-contents, .osss-app .jupyter-widget-Collapse-contents, .osss-app .p-Collapse-contents {
  border: 0 !important; background: transparent !important; padding: 4px 0 4px !important;
}

/* layout */
.osss-app .widget-html-content { font-size: 13px; line-height: 1.55; }
.osss-app .o-panel { padding: 20px 22px !important; border: 1px solid var(--o-line); border-radius: 10px; margin-bottom: 14px !important; background: var(--o-bg); }
.osss-app .o-panel-head { margin-bottom: 4px; }
.osss-app .o-divider { border-top: 1px solid var(--o-line); margin: 10px 0 6px !important; }
.osss-app .o-flat { padding: 0 !important; }
.osss-app .o-g4 { gap: 4px; }
.osss-app .o-g6 { gap: 6px; }
.osss-app .o-g10 { gap: 10px; }
.osss-app .o-g14 { gap: 14px; }
.osss-app .o-stack { gap: 6px; }
.osss-app .o-stack > .widget-html:first-child .widget-html-content { line-height: 1.2; }
</style>
"""
