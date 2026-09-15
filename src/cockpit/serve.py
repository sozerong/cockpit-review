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
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .watch import _run_once, _snapshot, POLL_INTERVAL, DEBOUNCE


WAIT_TIMEOUT = 25.0     # long-poll ceiling before returning current state


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.version = 0
        self.envelope: dict | None = None
        self.scanning = False

    def set(self, envelope: dict) -> None:
        with self.cond:
            self.version += 1
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


def _watch_loop(repo: Path) -> None:
    _state.set_scanning(True)
    _state.set(_run_once(repo))
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
            _state.set(_run_once(repo))
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
  --bg: #fdfdfd; --fg: #1a1a1a; --muted: #666;
  --border: #ddd; --stripe: #f6f6f6; --code-bg: #f0f0f0;
  --block: #c62828; --warn: #d97706; --info: #0369a1;
  --live: #16a34a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a1a; --fg: #eee; --muted: #999;
    --border: #333; --stripe: #222; --code-bg: #2a2a2a;
    --block: #ef5350; --warn: #fbbf24; --info: #38bdf8;
    --live: #4ade80;
  }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 1rem 1.25rem;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--fg); }
header { display: flex; gap: 1.25rem; align-items: baseline; flex-wrap: wrap;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); margin-bottom: 0.75rem; }
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
.filters { display: flex; gap: 0.75rem; margin: 0.75rem 0; align-items: center; flex-wrap: wrap; }
.filters label { display: flex; gap: 0.25rem; align-items: center; user-select: none; cursor: pointer; }
.filters input[type=text] { padding: 0.25rem 0.5rem; border: 1px solid var(--border);
  background: var(--bg); color: var(--fg); border-radius: 3px; min-width: 20ch; }
.count { color: var(--muted); font-size: 0.85rem; margin-left: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:nth-child(even) { background: var(--stripe); }
tr.finding.fresh { animation: flash 1.2s ease-out; }
@keyframes flash {
  0% { background: color-mix(in srgb, var(--live) 30%, var(--bg)); }
  100% { background: transparent; }
}
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
.chev::before { content: "▸"; display: inline-block; width: 1em; color: var(--muted);
  font-size: 0.7rem; transition: transform 0.1s; }
tr.finding.expanded .chev::before { transform: rotate(90deg); }
.empty { padding: 2rem; text-align: center; color: var(--muted); }
</style>

<header>
  <h1>cockpit</h1>
  <span class="repo" id="repo">connecting…</span>
  <div class="summary" id="summary"></div>
  <span class="live"><span class="dot" id="dot"></span><span id="livetext">live</span></span>
</header>

<div class="filters">
  <label><input type="checkbox" id="f-block" checked> block</label>
  <label><input type="checkbox" id="f-warn" checked> warn</label>
  <label><input type="checkbox" id="f-info"> info</label>
  <input type="text" id="q" placeholder="filter by file, analyzer, symbol…">
  <span class="count" id="count"></span>
</div>

<table>
  <thead>
    <tr>
      <th style="width:1.5em"></th>
      <th style="width:5em">sev</th>
      <th>file:line</th>
      <th style="width:12em">analyzer</th>
      <th>message</th>
    </tr>
  </thead>
  <tbody id="rows"></tbody>
</table>
<div id="empty" class="empty" hidden>No findings match the current filters.</div>

<script>
const SEV_ORDER = { block: 0, warn: 1, info: 2 };
let version = -1;
let findings = [];
let prevIds = new Set();

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
    tr.className = "finding sev-" + f.severity + (freshIds.has(f.id) ? " fresh" : "");
    tr.dataset.i = i;
    tr.innerHTML = `
      <td><span class="chev"></span></td>
      <td><span class="sev ${f.severity}">${f.severity}</span></td>
      <td class="loc">${esc(f.file)}:${f.span[0]}${f.symbol ? " · " + esc(f.symbol) : ""}</td>
      <td class="ana">${esc(f.analyzer_id)}<br><span style="opacity:0.6">v${esc(f.analyzer_version)}</span></td>
      <td>${esc(f.message)}</td>`;
    rowsEl.appendChild(tr);

    const ev = document.createElement("tr");
    ev.className = "evidence";
    const td = document.createElement("td");
    td.colSpan = 5;
    td.innerHTML = `<pre>${esc(JSON.stringify(f.evidence, null, 2))}</pre>`;
    ev.appendChild(td);
    rowsEl.appendChild(ev);

    tr.addEventListener("click", () => tr.classList.toggle("expanded"));
  });
  applyFilter();
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
    const qOk = !q || tr.textContent.toLowerCase().includes(q);
    const visible = sevOk && qOk;
    tr.classList.toggle("hidden", !visible);
    tr.nextElementSibling.classList.toggle("hidden", !visible);
    if (!visible) tr.classList.remove("expanded");
    if (visible) shown++;
  });
  document.getElementById("count").textContent = `${shown} of ${findings.length}`;
  document.getElementById("empty").hidden = shown > 0;
}

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
