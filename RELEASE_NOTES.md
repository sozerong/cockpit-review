## cockpit-review 0.2.0

A live dashboard, a machine-readable diff receipt, three new analyzers,
and a **27× speedup** on the developer save-to-update loop.

### Highlights

**Live dashboard — `cockpit serve`.** Watch a repo in a browser. The
findings list, evidence panel, analyzer chart, and pipeline state
machine update the moment you save a file. Interactive route tracing
across every panel — click an analyzer id or file path to highlight
everywhere it appears. i18n EN / KO. SYSTEM panel is a proper SVG
visualization designed by an independent design pass.

**Machine receipt — `cockpit diff <base> <head>`.** Two envelopes go
in, a typed receipt comes out: added / resolved / moved / stable, split
by severity, plus per-finding rows. `--format json` (machine contract)
or `--format markdown` (PR-comment shape). CI now uses it — PR comments
show "you added N warns, resolved M" instead of a raw dump.

**Incremental scan — fastapi 5.8s → 212ms.** Rescan only changed files.
Per-file caches on FS walk, tree-sitter indices, and per-analyzer
findings, all invalidated by `.git` sentinels + `id(FileIndex)`
identity. Measured: **27× warm-scan speedup vs full rescan** on the
1138-file fastapi tree.

### New analyzers

- `except.reraise-vs-raise` v1 — `raise <alias>` truncates traceback.
- `arg.mutable-default` v1 — `def f(x=[])`, `x={}`, `x=set()`, `x=list()`.
- `test.time.sleep` v1 — `time.sleep()` inside a test function.

### Install

```bash
pip install cockpit-review
```

### Quick start

```bash
cockpit check                        # one-shot scan (CI-friendly)
cockpit check --exit-at warn         # gate on any new warn
cockpit serve                        # live browser dashboard, port 8765
cockpit diff base.json head.json     # PR receipt
cockpit report --out review.html     # single-file HTML report
```

### Verify

```bash
cockpit --version    # 0.2.0
```

### Under the hood

- 69 pytest tests, cross-platform CI (Linux × macOS × Windows × Python
  3.11, 3.12).
- Windows-safe: `cockpit check --json` never crashes on non-ASCII
  content on legacy consoles; every CLI stdout is forced to UTF-8.
- All rationale strings translated for the KO dashboard, including the
  per-analyzer "How this was detected" text.

### Known limits

- Python only. TypeScript is queued for M0.5.
- `test.mocks-target` v1 remains shipped disabled (P0 stop criterion);
  v2 with SUT detection is queued for a future release.
- Live dashboard is single-user local for now; hosted mode + GitHub
  App is the M1.0 target.

### Full change list

See [CHANGELOG.md](CHANGELOG.md) for the per-commit detail under the
`## 0.2.0` heading.
