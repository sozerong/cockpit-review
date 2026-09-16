"""`cockpit report [--out FILE]` — self-contained HTML report.

PLAN §7 killer panel is RISK. This is the minimum viable web view: a
single-file HTML with findings embedded as JSON, severity-colored rows,
filters, and click-to-expand evidence. No build tools, no CDN except
the CSS/JS below inlined.

Later expansions (NOW / DELTA / EVIDENCE panels, live push via watch)
go in a separate module when the RISK view has real users."""
from __future__ import annotations
import html
import json
from pathlib import Path
from typing import Any

_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cockpit — findings</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #fdfdfd; --fg: #1a1a1a; --muted: #666;
  --border: #ddd; --stripe: #f6f6f6; --code-bg: #f0f0f0;
  --block: #c62828; --warn: #d97706; --info: #0369a1;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a1a; --fg: #eee; --muted: #999;
    --border: #333; --stripe: #222; --code-bg: #2a2a2a;
    --block: #ef5350; --warn: #fbbf24; --info: #38bdf8;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 1rem 1.25rem;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--fg);
}
header {
  display: flex; gap: 1.25rem; align-items: baseline; flex-wrap: wrap;
  padding-bottom: 0.5rem; border-bottom: 1px solid var(--border); margin-bottom: 0.75rem;
}
h1 { font-size: 1.1rem; margin: 0; font-weight: 600; }
.repo { color: var(--muted); font-family: ui-monospace, monospace; font-size: 0.85rem; }
.summary { display: flex; gap: 0.75rem; }
.summary span { padding: 0.15rem 0.5rem; border-radius: 3px; font-weight: 600; font-size: 0.85rem; }
.summary .n-block { background: var(--block); color: #fff; }
.summary .n-warn { background: var(--warn); color: #fff; }
.summary .n-info { background: var(--info); color: #fff; }
.summary .n-zero { background: transparent; color: var(--muted); font-weight: 400; }
.filters { display: flex; gap: 0.75rem; margin: 0.75rem 0; align-items: center; flex-wrap: wrap; }
.filters label { display: flex; gap: 0.25rem; align-items: center; user-select: none; cursor: pointer; }
.filters input[type=text] { padding: 0.25rem 0.5rem; border: 1px solid var(--border); background: var(--bg); color: var(--fg); border-radius: 3px; min-width: 20ch; }
.count { color: var(--muted); font-size: 0.85rem; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
tr:nth-child(even) { background: var(--stripe); }
.sev { display: inline-block; width: 3.3em; padding: 0.05rem 0.35rem; border-radius: 3px; font-size: 0.75rem; font-weight: 700; color: #fff; text-align: center; text-transform: uppercase; }
.sev.block { background: var(--block); }
.sev.warn { background: var(--warn); }
.sev.info { background: var(--info); }
.loc { font-family: ui-monospace, monospace; font-size: 0.85rem; color: var(--muted); white-space: nowrap; }
.ana { font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--muted); }
tr.hidden { display: none; }
tr.finding.expanded + tr.evidence { display: table-row; }
tr.evidence { display: none; }
tr.evidence td { background: var(--code-bg); padding: 0.5rem 0.75rem; border-top: none; }
tr.evidence pre { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: ui-monospace, monospace; font-size: 0.8rem; color: var(--fg); }
tr.finding { cursor: pointer; }
tr.finding:hover { background: var(--stripe); }
.chev::before { content: "▸"; display: inline-block; width: 1em; color: var(--muted); font-size: 0.7rem; transition: transform 0.1s; }
tr.finding.expanded .chev::before { transform: rotate(90deg); }
.empty { padding: 2rem; text-align: center; color: var(--muted); }
</style>

<header>
  <h1>cockpit</h1>
  <span class="repo" id="repo"></span>
  <span class="repo" id="generated"></span>
  <div class="summary" id="summary"></div>
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
const ENVELOPE = __ENVELOPE_JSON__;
const SEV_ORDER = { block: 0, warn: 1, info: 2 };

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

document.getElementById("repo").textContent = ENVELOPE.repo;
document.getElementById("generated").textContent = ENVELOPE.generated_at;

const s = ENVELOPE.summary;
const summaryEl = document.getElementById("summary");
for (const sev of ["block", "warn", "info"]) {
  const n = s[sev] || 0;
  const span = document.createElement("span");
  span.className = "n-" + (n === 0 ? "zero" : sev);
  span.textContent = `${sev} ${n}`;
  summaryEl.appendChild(span);
}
const filesSpan = document.createElement("span");
filesSpan.className = "n-zero";
filesSpan.textContent = `· ${s.files_scanned} files scanned`;
summaryEl.appendChild(filesSpan);

const findings = [...ENVELOPE.findings].sort((a, b) =>
  (SEV_ORDER[a.severity] - SEV_ORDER[b.severity]) ||
  a.file.localeCompare(b.file) ||
  a.span[0] - b.span[0]);

const rowsEl = document.getElementById("rows");
findings.forEach((f, i) => {
  const tr = document.createElement("tr");
  tr.className = "finding sev-" + f.severity;
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
applyFilter();
</script>
"""


def render(envelope: dict[str, Any]) -> str:
    payload = json.dumps(envelope, ensure_ascii=False)
    # No user-controlled HTML injected into the template; the payload is
    # JSON so </script> would need to appear escaped from the JSON encoder.
    # Belt-and-suspenders: also escape closing script tags in the payload.
    payload = payload.replace("</", "<\\/")
    return _TEMPLATE.replace("__ENVELOPE_JSON__", payload)


def cmd_report(repo: Path, out: Path | None) -> int:
    from .analyzers import run_all
    from .changeset import full_scan
    from .finding import to_json
    from .indexer import index_file

    cs = full_scan(repo)
    indices = {}
    for fc in cs.files:
        try:
            indices[fc.path] = index_file(fc.path, fc.absolute)
        except Exception:
            pass
    findings = run_all(cs, indices)
    envelope = to_json(
        repo=str(repo.resolve()),
        scope={"kind": "full", "base": None, "head": "working"},
        findings=findings,
        files_scanned=len(indices),
    )
    text = render(envelope)
    dest = out or (repo / "cockpit-report.html")
    dest.write_text(text, encoding="utf-8")
    print(f"=> {dest}  ({len(findings)} findings, {len(indices)} files)")
    return 0


def demo() -> None:
    """Self-check: render on a tiny envelope, verify script escape and DOM sanity."""
    env = {
        "schema": 1, "repo": "/tmp/x", "generated_at": "2026-09-14T00:00:00+00:00",
        "scope": {"kind": "full", "base": None, "head": "working"},
        "summary": {"block": 0, "warn": 2, "info": 1, "files_scanned": 5},
        "findings": [
            {"id": "a", "analyzer_id": "dup.block", "analyzer_version": "5",
             "severity": "warn", "file": "src/a.py", "span": [10, 15],
             "symbol": None, "message": "5+ line block duplicated in 2 places",
             "evidence": {"matches": [{"file": "src/b.py", "span": [20, 25]}]}},
            {"id": "b", "analyzer_id": "risk.error-masking", "analyzer_version": "2",
             "severity": "warn", "file": "src/c.py", "span": [42, 44],
             "symbol": None, "message": "except clause swallows errors (broad-except)",
             "evidence": {"kind": "broad-except", "snippet": "except Exception:\n    pass"}},
            {"id": "c", "analyzer_id": "test.assertion-free", "analyzer_version": "2",
             "severity": "info", "file": "tests/test_d.py", "span": [3, 5],
             "symbol": "test_smoke", "message": "test `test_smoke` has no assertion",
             "evidence": {"function": "test_smoke"}},
        ],
    }
    html_out = render(env)
    assert "__ENVELOPE_JSON__" not in html_out
    assert "dup.block" in html_out
    assert "except</" not in html_out  # closing-script escape check
    # Injection defense: a </script> in user content must not create a second
    # closing tag; the template has exactly one legitimate closing tag.
    baseline = html_out.count("</script>")
    env2 = dict(env)
    env2["findings"] = [dict(env["findings"][0], message="foo </script><x>y")]
    html2 = render(env2)
    assert html2.count("</script>") == baseline, "user content leaked past escape"
    print("ui.demo ok")


if __name__ == "__main__":
    demo()
