"""`cockpit serve` — live dashboard: file changes → re-scan → browser updates.

Stdlib only. Background thread runs the watch loop (reused from watch.py),
HTTP server exposes:
  GET /            → shell HTML with polling client
  GET /state.json  → current envelope + monotonic version counter

The client polls /state.json?since=<v> and long-waits until a newer version
is ready (up to WAIT_TIMEOUT), then re-renders findings. Poll, not SSE:
http.server has no chunked streaming primitive and long-poll works fine
for a single-user dev-loop dashboard.
"""
from __future__ import annotations
import collections
import datetime
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import baseline as bl
from .watch import _run_once, _snapshot, POLL_INTERVAL, DEBOUNCE


WAIT_TIMEOUT = 25.0     # long-poll ceiling before returning current state
ACTIVITY_LEN = 12       # rolling scan-event log for the NOW panel


# Per-analyzer rationale shown in the evidence pane. Kept next to the
# analyzer roster so a new analyzer added to __init__.py without a
# rationale here still renders (falls back to the analyzer id).
_RATIONALES = {
    "dup.block":
        "5+ line duplicate windows inside function bodies. "
        "String-dominant blocks filtered; tests/examples/docs downgraded; "
        "clusters of >5 copies collapse to one info.",
    "risk.error-masking":
        "except body is only pass/…, split by broadness: "
        "bare `except:` or `except Exception:` → warn; "
        "`except SpecificError:` → info.",
    "except.reraise-vs-raise":
        "`raise <alias>` in `except X as <alias>:` truncates traceback. "
        "Bare `raise` preserves it.",
    "arg.mutable-default":
        "Default is evaluated once at def-time. `def f(x=[]):` shares "
        "one list across every call — classic hidden state.",
    "test.assertion-free":
        "test_* function with no assert*, pytest.raises, or unittest self.assert*. "
        "Runs, passes, checks nothing.",
    "test.always-true-assertion":
        "assert on a truthy literal (True, non-empty container, non-zero number). "
        "Always passes regardless of code.",
    "test.no-test-for-public-symbol":
        "Public top-level symbol has no test_<name> anywhere in the parallel "
        "tests/ tree.",
}


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.version = 0
        self.envelope: dict | None = None
        self.scanning = False
        self.activity: collections.deque = collections.deque(maxlen=ACTIVITY_LEN)
        self.prev_ids: set[str] = set()

    def set(self, envelope: dict) -> None:
        with self.cond:
            self.version += 1
            cur_ids = {f["id"] for f in envelope["findings"]}
            delta_new = len(cur_ids - self.prev_ids)
            delta_gone = len(self.prev_ids - cur_ids)
            self.prev_ids = cur_ids
            self.activity.appendleft({
                "at": datetime.datetime.now().strftime("%H:%M:%S"),
                "files": envelope["summary"]["files_scanned"],
                "total": len(cur_ids),
                "new": delta_new,
                "gone": delta_gone,
            })
            envelope["activity"] = list(self.activity)
            envelope["analyzer_counts"] = _counts_by_analyzer(envelope["findings"])
            self.envelope = envelope
            self.cond.notify_all()

    def wait_after(self, since: int, timeout: float) -> tuple[int, dict | None, bool]:
        with self.cond:
            if self.version > since:
                return self.version, self.envelope, self.scanning
            self.cond.wait(timeout=timeout)
            return self.version, self.envelope, self.scanning

    def set_scanning(self, on: bool) -> None:
        with self.cond:
            self.scanning = on
            self.cond.notify_all()


_state = _State()


def _counts_by_analyzer(findings: list[dict]) -> list[dict]:
    """Sorted analyzer counts split by severity, for the bar chart."""
    by = {}
    for f in findings:
        by.setdefault(f["analyzer_id"], {"block": 0, "warn": 0, "info": 0})
        by[f["analyzer_id"]][f["severity"]] += 1
    out = [{"id": k, **v, "total": v["block"] + v["warn"] + v["info"]}
           for k, v in by.items()]
    out.sort(key=lambda x: (-x["total"], x["id"]))
    return out


def _scan(repo: Path) -> dict:
    """Run analyzers + annotate each finding with `baselined` bool and
    a `rationale` string. Baseline is re-read on every scan."""
    env = _run_once(repo)
    baselined = bl.load(repo) or set()
    for f in env["findings"]:
        f["baselined"] = f["id"] in baselined
        f["rationale"] = _RATIONALES.get(f["analyzer_id"], "")
    env["summary"]["baselined"] = sum(1 for f in env["findings"] if f["baselined"])
    env["summary"]["new"] = len(env["findings"]) - env["summary"]["baselined"]
    return env


def _watch_loop(repo: Path) -> None:
    _state.set_scanning(True)
    _state.set(_scan(repo))
    _state.set_scanning(False)

    prev = _snapshot(repo)
    last_change_at: float | None = None
    while True:
        time.sleep(POLL_INTERVAL)
        cur = _snapshot(repo)
        if cur != prev:
            last_change_at = time.monotonic()
            prev = cur
        elif last_change_at is not None and \
                time.monotonic() - last_change_at >= DEBOUNCE:
            _state.set_scanning(True)
            _state.set(_scan(repo))
            _state.set_scanning(False)
            last_change_at = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass  # ponytail: silence per-request access log

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
        elif url.path == "/state.json":
            since = int((parse_qs(url.query).get("since") or ["-1"])[0])
            version, envelope, scanning = _state.wait_after(since, WAIT_TIMEOUT)
            body = json.dumps({
                "version": version,
                "envelope": envelope,
                "scanning": scanning,
            }, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json", body)
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, status: int, ctype: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def cmd_serve(repo: Path, port: int = 8765) -> int:
    t = threading.Thread(target=_watch_loop, args=(repo,), daemon=True)
    t.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"cockpit serve · {url}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
        return 0


_PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cockpit — live</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #fdfdfd; --panel: #ffffff; --fg: #1a1a1a; --muted: #666;
  --border: #ddd; --stripe: #f6f6f6; --code-bg: #f0f0f0;
  --block: #c62828; --warn: #d97706; --info: #0369a1;
  --live: #16a34a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141414; --panel: #1c1c1c; --fg: #eee; --muted: #999;
    --border: #333; --stripe: #242424; --code-bg: #262626;
    --block: #ef5350; --warn: #fbbf24; --info: #38bdf8;
    --live: #4ade80;
  }
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; padding: 0.75rem 1rem;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--fg);
  display: grid; grid-template-rows: auto auto 1fr; gap: 0.5rem; }
header { display: flex; gap: 1.25rem; align-items: baseline; flex-wrap: wrap;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); }
h1 { font-size: 1.1rem; margin: 0; font-weight: 600; }
.repo { color: var(--muted); font-family: ui-monospace, monospace; font-size: 0.85rem; }
.summary { display: flex; gap: 0.5rem; }
.summary span { padding: 0.15rem 0.5rem; border-radius: 3px; font-weight: 600; font-size: 0.85rem; }
.summary .n-block { background: var(--block); color: #fff; }
.summary .n-warn { background: var(--warn); color: #fff; }
.summary .n-info { background: var(--info); color: #fff; }
.summary .n-zero { background: transparent; color: var(--muted); font-weight: 400; }
.live { display: inline-flex; align-items: center; gap: 0.35rem; color: var(--live); font-size: 0.85rem; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--live);
  box-shadow: 0 0 0 0 currentColor; animation: pulse 1.6s ease-out infinite; }
.dot.scanning { animation: pulse 0.6s ease-out infinite; }
.dot.stale { background: var(--muted); animation: none; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
  70% { box-shadow: 0 0 0 8px transparent; opacity: 0.9; }
  100% { box-shadow: 0 0 0 0 transparent; opacity: 1; }
}
.filters { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
.filters label { display: flex; gap: 0.25rem; align-items: center; user-select: none; cursor: pointer; }
.filters input[type=text] { padding: 0.25rem 0.5rem; border: 1px solid var(--border);
  background: var(--bg); color: var(--fg); border-radius: 3px; min-width: 20ch; }
.count { color: var(--muted); font-size: 0.85rem; margin-left: auto; }

main { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  grid-template-rows: minmax(0, 1fr) 180px; gap: 0.5rem; min-height: 0; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 4px;
  display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.panel > h2 { margin: 0; padding: 0.4rem 0.75rem;
  font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); border-bottom: 1px solid var(--border); display: flex; gap: 0.5rem; align-items: center; }
.panel > h2 .killer { color: var(--warn); }
.panel-body { flex: 1; overflow: auto; min-height: 0; }

.risk { grid-column: 1; grid-row: 1; }
.evidence { grid-column: 2; grid-row: 1 / span 2; }
.delta { grid-column: 1; grid-row: 2; }
.evidence-empty { padding: 1.5rem; color: var(--muted); font-size: 0.85rem; text-align: center; }

table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
thead th { position: sticky; top: 0; background: var(--panel); z-index: 1; font-size: 0.75rem; color: var(--muted); }
tr:nth-child(even) { background: var(--stripe); }
tr.finding.fresh { animation: flash 1.2s ease-out; }
tr.finding.selected { outline: 2px solid var(--live); outline-offset: -2px; background: color-mix(in srgb, var(--live) 8%, transparent); }
tr.finding.baselined { opacity: 0.55; }
tr.finding.baselined td.loc::after { content: " · baseline"; color: var(--muted); font-size: 0.75rem; }
@keyframes flash {
  0% { background: color-mix(in srgb, var(--live) 30%, var(--bg)); }
  100% { background: transparent; }
}
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
.seg button { border: 0; background: var(--bg); color: var(--fg); padding: 0.2rem 0.6rem;
  font: inherit; font-size: 0.85rem; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button.active { background: var(--live); color: #fff; }
kbd { font-family: ui-monospace, monospace; font-size: 0.75rem; padding: 0.05rem 0.35rem;
  border: 1px solid var(--border); border-bottom-width: 2px; border-radius: 3px;
  background: var(--stripe); color: var(--fg); }
.help-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex;
  align-items: center; justify-content: center; z-index: 10; }
.help-overlay[hidden] { display: none; }
.help-card { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
  padding: 1.25rem 1.5rem; min-width: 320px; max-width: 480px; }
.help-card h2 { margin: 0 0 0.75rem; font-size: 1rem; }
.help-card table { border: 0; }
.help-card td { border: 0; padding: 0.2rem 0.5rem 0.2rem 0; }
.help-card td:first-child { text-align: right; width: 8em; }
.sev { display: inline-block; width: 3.3em; padding: 0.05rem 0.35rem; border-radius: 3px;
  font-size: 0.75rem; font-weight: 700; color: #fff; text-align: center; text-transform: uppercase; }
.sev.block { background: var(--block); }
.sev.warn { background: var(--warn); }
.sev.info { background: var(--info); }
.loc { font-family: ui-monospace, monospace; font-size: 0.85rem; color: var(--muted); white-space: nowrap; }
.ana { font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--muted); }
tr.hidden { display: none; }
tr.finding.expanded + tr.evidence { display: table-row; }
tr.evidence { display: none; }
tr.evidence td { background: var(--code-bg); padding: 0.5rem 0.75rem; border-top: none; }
tr.evidence pre { margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--fg); }
tr.finding { cursor: pointer; }
tr.finding:hover { background: var(--stripe); }
.empty { padding: 2rem; text-align: center; color: var(--muted); }

/* EVIDENCE panel */
.ev { padding: 0.75rem 1rem; }
.ev .loc { font-family: ui-monospace, monospace; font-size: 0.9rem; margin-bottom: 0.5rem; color: var(--fg); }
.ev .rule { color: var(--muted); font-size: 0.8rem; margin-bottom: 0.5rem; }
.ev .msg { font-size: 0.95rem; margin-bottom: 0.75rem; }
.ev section { margin-top: 0.75rem; }
.ev section > h3 { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin: 0 0 0.35rem; }
.ev pre { background: var(--code-bg); padding: 0.6rem 0.75rem; border-radius: 3px;
  font-family: ui-monospace, monospace; font-size: 0.78rem; overflow: auto;
  white-space: pre-wrap; word-break: break-word; margin: 0; }
.ev .matches { display: flex; flex-direction: column; gap: 0.25rem; font-family: ui-monospace, monospace; font-size: 0.8rem; }
.ev .matches a { color: var(--fg); text-decoration: none; padding: 0.15rem 0.35rem; border-radius: 2px; }
.ev .matches a:hover { background: var(--stripe); }

/* DELTA (analyzer bar chart) */
.chart-row { display: grid; grid-template-columns: 12em 1fr 3em; gap: 0.5rem;
  align-items: center; padding: 0.15rem 0.75rem; font-size: 0.8rem; }
.chart-row .name { font-family: ui-monospace, monospace; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chart-row .bar { height: 0.55rem; background: var(--stripe); border-radius: 2px; overflow: hidden;
  display: flex; }
.chart-row .bar span { display: block; height: 100%; }
.chart-row .bar .block { background: var(--block); }
.chart-row .bar .warn { background: var(--warn); }
.chart-row .bar .info { background: var(--info); }
.chart-row .n { font-family: ui-monospace, monospace; text-align: right; color: var(--muted); }
.chart-empty { padding: 1rem; color: var(--muted); font-size: 0.85rem; text-align: center; }

/* NOW activity log (embedded in DELTA panel footer strip) */
.activity { display: flex; flex-direction: column; gap: 0.1rem; padding: 0.35rem 0.75rem; font-family: ui-monospace, monospace; font-size: 0.78rem; }
.activity .row { display: grid; grid-template-columns: 4.5em 1fr auto; gap: 0.5rem; color: var(--muted); }
.activity .row .delta.pos { color: var(--warn); }
.activity .row .delta.neg { color: var(--live); }
</style>

<header>
  <h1>cockpit</h1>
  <span class="repo" id="repo">connecting…</span>
  <div class="summary" id="summary"></div>
  <span class="live"><span class="dot" id="dot"></span><span id="livetext">live</span></span>
</header>

<div class="filters">
  <label><input type="checkbox" id="f-block" checked> block <kbd>1</kbd></label>
  <label><input type="checkbox" id="f-warn" checked> warn <kbd>2</kbd></label>
  <label><input type="checkbox" id="f-info"> info <kbd>3</kbd></label>
  <span class="seg" id="baseline-mode" role="group" aria-label="baseline filter">
    <button data-mode="new" class="active" title="hide baselined findings (press N)">new only</button>
    <button data-mode="all" title="show every finding">all</button>
    <button data-mode="baselined" title="show only baselined findings">baselined</button>
  </span>
  <input type="text" id="q" placeholder="filter by file, analyzer, symbol…  /">
  <span class="count" id="count"></span>
  <button id="help-btn" title="show keyboard shortcuts" style="border:1px solid var(--border);background:var(--bg);color:var(--muted);border-radius:3px;padding:0.15rem 0.5rem;cursor:pointer;font:inherit;font-size:0.85rem;">?</button>
</div>

<div class="help-overlay" id="help" hidden>
  <div class="help-card">
    <h2>keyboard</h2>
    <table>
      <tr><td><kbd>j</kbd> / <kbd>k</kbd></td><td>next / previous finding</td></tr>
      <tr><td><kbd>Enter</kbd></td><td>expand selected finding</td></tr>
      <tr><td><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></td><td>toggle block / warn / info</td></tr>
      <tr><td><kbd>n</kbd></td><td>cycle: new only → all → baselined</td></tr>
      <tr><td><kbd>/</kbd></td><td>focus search</td></tr>
      <tr><td><kbd>Esc</kbd></td><td>blur search / close this</td></tr>
      <tr><td><kbd>?</kbd></td><td>toggle this overlay</td></tr>
    </table>
  </div>
</div>

<main>
  <section class="panel risk">
    <h2>Risk <span class="killer">★</span> <span style="color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;">findings · j / k to navigate</span></h2>
    <div class="panel-body">
      <table>
        <thead>
          <tr>
            <th style="width:5em">sev</th>
            <th>file:line</th>
            <th style="width:11em">analyzer</th>
            <th>message</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
      <div id="empty" class="empty" hidden>No findings match the current filters.</div>
    </div>
  </section>

  <section class="panel evidence">
    <h2>Evidence</h2>
    <div class="panel-body" id="evidence-body">
      <div class="evidence-empty">Select a finding — press <kbd>j</kbd> or click a row.</div>
    </div>
  </section>

  <section class="panel delta">
    <h2>Delta · analyzer counts <span style="margin-left:auto;color:var(--muted);font-weight:400;text-transform:none;letter-spacing:0;">& recent scans</span></h2>
    <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr;gap:0;">
      <div id="chart" style="border-right:1px solid var(--border);overflow:auto;"></div>
      <div id="activity" class="activity"></div>
    </div>
  </section>
</main>

<script>
const SEV_ORDER = { block: 0, warn: 1, info: 2 };
const BASELINE_MODES = ["new", "all", "baselined"];
let version = -1;
let findings = [];
let prevIds = new Set();
let baselineMode = "new";
let selectedIdx = -1;

function esc(s) { return String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function render(envelope, freshIds) {
  document.getElementById("repo").textContent = envelope.repo;
  const s = envelope.summary;
  const sumEl = document.getElementById("summary");
  sumEl.innerHTML = "";
  for (const sev of ["block", "warn", "info"]) {
    const n = s[sev] || 0;
    const span = document.createElement("span");
    span.className = "n-" + (n === 0 ? "zero" : sev);
    span.textContent = `${sev} ${n}`;
    sumEl.appendChild(span);
  }
  const files = document.createElement("span");
  files.className = "n-zero";
  files.textContent = `· ${s.files_scanned} files`;
  sumEl.appendChild(files);

  findings = [...envelope.findings].sort((a, b) =>
    (SEV_ORDER[a.severity] - SEV_ORDER[b.severity]) ||
    a.file.localeCompare(b.file) ||
    a.span[0] - b.span[0]);

  const rowsEl = document.getElementById("rows");
  rowsEl.innerHTML = "";
  findings.forEach((f, i) => {
    const tr = document.createElement("tr");
    tr.className = "finding sev-" + f.severity
      + (freshIds.has(f.id) ? " fresh" : "")
      + (f.baselined ? " baselined" : "");
    tr.dataset.i = i;
    tr.innerHTML = `
      <td><span class="sev ${f.severity}">${f.severity}</span></td>
      <td class="loc">${esc(f.file)}:${f.span[0]}${f.symbol ? " · " + esc(f.symbol) : ""}</td>
      <td class="ana">${esc(f.analyzer_id)}<br><span style="opacity:0.6">v${esc(f.analyzer_version)}</span></td>
      <td>${esc(f.message)}</td>`;
    rowsEl.appendChild(tr);
    tr.addEventListener("click", () => select(i));
  });
  renderChart(envelope.analyzer_counts || []);
  renderActivity(envelope.activity || []);
  applyFilter();
  if (selectedIdx >= 0 && selectedIdx < findings.length) {
    renderEvidence(findings[selectedIdx]);
  } else {
    renderEvidence(null);
  }
}

function renderEvidence(f) {
  const body = document.getElementById("evidence-body");
  if (!f) {
    body.innerHTML = '<div class="evidence-empty">Select a finding — press <kbd>j</kbd> or click a row.</div>';
    return;
  }
  const evJson = JSON.stringify(f.evidence, null, 2);
  const snippet = (f.evidence && (f.evidence.snippet || f.evidence.text)) || evJson;
  const matches = (f.evidence && Array.isArray(f.evidence.matches)) ? f.evidence.matches : [];
  const matchesHtml = matches.length
    ? `<section><h3>Matches (${matches.length})</h3><div class="matches">`
        + matches.map(m => `<a>${esc(m.file || "")}:${m.span ? m.span[0] : ""}</a>`).join("")
        + `</div></section>`
    : "";
  body.innerHTML = `<div class="ev">
    <div class="loc"><span class="sev ${f.severity}">${f.severity}</span> ${esc(f.file)}:${f.span[0]}${f.symbol ? " · " + esc(f.symbol) : ""}${f.baselined ? ' <span style="color:var(--muted);font-size:0.75rem;">· baseline</span>' : ""}</div>
    <div class="rule">${esc(f.analyzer_id)} v${esc(f.analyzer_version)}</div>
    <div class="msg">${esc(f.message)}</div>
    ${f.rationale ? `<section><h3>How this was detected</h3><div style="color:var(--muted);font-size:0.83rem;">${esc(f.rationale)}</div></section>` : ""}
    <section><h3>Snippet</h3><pre>${esc(snippet)}</pre></section>
    ${matchesHtml}
    <section><h3>Raw evidence</h3><pre>${esc(evJson)}</pre></section>
  </div>`;
}

function renderChart(rows) {
  const el = document.getElementById("chart");
  if (!rows.length) { el.innerHTML = '<div class="chart-empty">no findings</div>'; return; }
  const max = Math.max(...rows.map(r => r.total));
  el.innerHTML = rows.map(r => {
    const pct = s => `${(r[s] / max * 100).toFixed(1)}%`;
    return `<div class="chart-row">
      <span class="name" title="${esc(r.id)}">${esc(r.id)}</span>
      <span class="bar">
        ${r.block ? `<span class="block" style="width:${pct('block')}"></span>` : ""}
        ${r.warn  ? `<span class="warn"  style="width:${pct('warn')}"></span>`  : ""}
        ${r.info  ? `<span class="info"  style="width:${pct('info')}"></span>`  : ""}
      </span>
      <span class="n">${r.total}</span>
    </div>`;
  }).join("");
}

function renderActivity(rows) {
  const el = document.getElementById("activity");
  if (!rows.length) { el.innerHTML = '<div class="chart-empty">waiting…</div>'; return; }
  el.innerHTML = rows.map(a => {
    const parts = [];
    if (a.new) parts.push(`<span class="delta pos">+${a.new}</span>`);
    if (a.gone) parts.push(`<span class="delta neg">−${a.gone}</span>`);
    const delta = parts.length ? parts.join(" ") : `<span style="opacity:0.5">·</span>`;
    return `<div class="row">
      <span>${esc(a.at)}</span>
      <span>${a.total} findings · ${a.files} files</span>
      <span>${delta}</span>
    </div>`;
  }).join("");
}

function applyFilter() {
  const showBlock = document.getElementById("f-block").checked;
  const showWarn = document.getElementById("f-warn").checked;
  const showInfo = document.getElementById("f-info").checked;
  const q = document.getElementById("q").value.toLowerCase().trim();
  let shown = 0;
  document.querySelectorAll("tr.finding").forEach((tr, i) => {
    const f = findings[i];
    const sevOk = (f.severity === "block" && showBlock) ||
                  (f.severity === "warn" && showWarn) ||
                  (f.severity === "info" && showInfo);
    const bOk = baselineMode === "all" ||
                (baselineMode === "new" && !f.baselined) ||
                (baselineMode === "baselined" && f.baselined);
    const qOk = !q || tr.textContent.toLowerCase().includes(q);
    const visible = sevOk && bOk && qOk;
    tr.classList.toggle("hidden", !visible);
    if (visible) shown++;
  });
  document.getElementById("count").textContent = `${shown} of ${findings.length}`;
  document.getElementById("empty").hidden = shown > 0;
  if (selectedIdx >= 0) {
    const cur = document.querySelector(`tr.finding[data-i="${selectedIdx}"]`);
    if (!cur || cur.classList.contains("hidden")) select(nextVisible(-1, +1));
  }
}

function nextVisible(from, dir) {
  const rows = [...document.querySelectorAll("tr.finding:not(.hidden)")];
  if (rows.length === 0) return -1;
  const idxs = rows.map(r => +r.dataset.i);
  if (from < 0) return dir > 0 ? idxs[0] : idxs[idxs.length - 1];
  const here = idxs.indexOf(from);
  if (here === -1) return dir > 0 ? idxs[0] : idxs[idxs.length - 1];
  const next = here + dir;
  return idxs[Math.max(0, Math.min(idxs.length - 1, next))];
}

function select(i) {
  document.querySelectorAll("tr.finding.selected").forEach(r => r.classList.remove("selected"));
  selectedIdx = i;
  if (i < 0 || i >= findings.length) { renderEvidence(null); return; }
  const tr = document.querySelector(`tr.finding[data-i="${i}"]`);
  if (tr) {
    tr.classList.add("selected");
    tr.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  renderEvidence(findings[i]);
}

function setBaselineMode(mode) {
  if (!BASELINE_MODES.includes(mode)) return;
  baselineMode = mode;
  document.querySelectorAll("#baseline-mode button").forEach(b =>
    b.classList.toggle("active", b.dataset.mode === mode));
  applyFilter();
}

document.querySelectorAll("#baseline-mode button").forEach(btn =>
  btn.addEventListener("click", () => setBaselineMode(btn.dataset.mode)));

const help = document.getElementById("help");
document.getElementById("help-btn").addEventListener("click", () => help.hidden = !help.hidden);
help.addEventListener("click", e => { if (e.target === help) help.hidden = true; });

document.addEventListener("keydown", e => {
  const q = document.getElementById("q");
  if (e.key === "Escape") {
    if (!help.hidden) { help.hidden = true; return; }
    if (document.activeElement === q) { q.blur(); return; }
  }
  if (document.activeElement === q) return;  // typing in search — let it be
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  switch (e.key) {
    case "j": select(nextVisible(selectedIdx, +1)); e.preventDefault(); break;
    case "k": select(nextVisible(selectedIdx, -1)); e.preventDefault(); break;
    case "Enter": case " ": {
      // Nav-to-first if nothing selected; otherwise re-focus the evidence pane's snippet.
      if (selectedIdx < 0) { select(nextVisible(-1, +1)); e.preventDefault(); }
      break;
    }
    case "1": document.getElementById("f-block").click(); break;
    case "2": document.getElementById("f-warn").click(); break;
    case "3": document.getElementById("f-info").click(); break;
    case "n": {
      const i = BASELINE_MODES.indexOf(baselineMode);
      setBaselineMode(BASELINE_MODES[(i + 1) % BASELINE_MODES.length]);
      break;
    }
    case "/": q.focus(); q.select(); e.preventDefault(); break;
    case "?": help.hidden = !help.hidden; break;
  }
});

for (const id of ["f-block", "f-warn", "f-info"]) {
  document.getElementById(id).addEventListener("change", applyFilter);
}
document.getElementById("q").addEventListener("input", applyFilter);

async function poll() {
  const dot = document.getElementById("dot");
  const label = document.getElementById("livetext");
  while (true) {
    try {
      const r = await fetch(`/state.json?since=${version}`);
      const { version: v, envelope, scanning } = await r.json();
      dot.classList.toggle("scanning", scanning);
      dot.classList.remove("stale");
      label.textContent = scanning ? "scanning…" : "live";
      if (envelope && v !== version) {
        version = v;
        const newIds = new Set(envelope.findings.map(f => f.id));
        const fresh = new Set([...newIds].filter(id => !prevIds.has(id)));
        prevIds = newIds;
        render(envelope, fresh);
      }
    } catch (e) {
      dot.classList.add("stale");
      label.textContent = "disconnected";
      await new Promise(r => setTimeout(r, 2000));
    }
  }
}
poll();
</script>
"""


def demo() -> None:
    """Self-check: start server on ephemeral port, hit /state.json, stop."""
    import socket
    import tempfile
    import urllib.request
    from contextlib import closing

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("def f():\n    try: x()\n    except: pass\n")
        with closing(socket.socket()) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        t = threading.Thread(target=_watch_loop, args=(root,), daemon=True)
        t.start()
        server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        st = threading.Thread(target=server.serve_forever, daemon=True)
        st.start()
        try:
            # Wait for first envelope.
            for _ in range(50):
                r = urllib.request.urlopen(f"http://127.0.0.1:{port}/state.json?since=-1", timeout=3)
                data = json.loads(r.read())
                if data["envelope"] is not None:
                    break
                time.sleep(0.1)
            assert data["envelope"] is not None, "no envelope after 5s"
            assert data["envelope"]["schema"] == 1
            # Page renders.
            page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
            assert "cockpit" in page and "state.json" in page
            print("serve ok")
        finally:
            server.shutdown()


if __name__ == "__main__":
    demo()
