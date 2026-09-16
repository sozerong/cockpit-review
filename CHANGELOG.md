# Changelog

## Unreleased

- **tests: pytest suite scaffolded** — `tests/` with a shared `make_repo`
  fixture and 37 initial tests covering the three new analyzers
  (`except.reraise-vs-raise`, `arg.mutable-default`, `test.time.sleep`),
  baseline save/load + finding-id stability, and the serve `_State`
  machine + `_scan` telemetry keys. Runs in 1.7s. 44% line coverage.
- **CI: pytest matrix** — Linux + macOS + Windows × Python 3.11, 3.12.
  Runs before the cockpit self-scan gate; both must pass.
- **docs: ROADMAP.md** — M0.2 (local tool), M0.5 (team tool), M1.0 (SaaS)
  milestone plan with the constraints the product commits to.
- **UI: SYSTEM panel visualization (v2)** — text tables replaced with an
  SVG pipeline spine per designer spec. 5-node state machine
  (starting → idle → debouncing → scanning → emitting) as horizontal
  flow with pulse ring + progress ring on the current node, 8 analyzer
  pips lit sequentially beneath the `scanning` node, proportional
  timing strip on the right (last-scan analyzer wall times color-coded
  by threshold), and a compact stats header (version, uptime, waiters,
  thread health dot). Stuck-state (>30s in a phase), indexer/analyzer
  errors, and reduced-motion all honored.
- **UI: SYSTEM panel** — bottom strip in the live dashboard exposes the
  internals: current pipeline phase (idle / detecting / debouncing /
  scanning / emitting) with elapsed timer, per-scan per-analyzer wall
  timings (bar chart), a rolling log of the last 30 state transitions,
  and a thread list with uptime, state version, long-poll waiter count,
  and indexer/analyzer error counts.
- **serve: `/system.json`** — cheap poll (~500ms) for the SYSTEM panel;
  doesn't touch the envelope long-poll path.
- **UI: EN / KO i18n** — every dashboard label, filter chip, help
  overlay row, evidence panel heading, and per-analyzer rationale
  translated to Korean. Language toggle (EN / KO) in the header;
  choice persists in `localStorage`. Default picks Korean when the
  browser's `navigator.language` starts with `ko-`, else English.
- **`test.time.sleep` v1** — flags `time.sleep(...)` and `sleep(...)`
  (when `from time import sleep`) inside `test_*` functions in test files.
  Flaky-test signal, `warn`. Real-repo pilot on pytest surfaced 4 hits, all
  in atime-sensitive tests.
- **UI: auto-pick baseline mode** — first envelope with no baseline (fresh
  repo) starts in `all` view instead of empty `new only`. Once set, the
  user can switch as normal.
- **CLI: JSON output ASCII-safe** — `cockpit check --json` uses
  `ensure_ascii=True` so a stray non-ASCII byte in evidence can never
  crash stdout on legacy Windows consoles (cp949/cp1252).
- **`cockpit serve --host`** — bind address flag for Tailscale/LAN access.
  Default `127.0.0.1` unchanged.
- **`cockpit serve`** — live dashboard. Watch loop pushes to in-memory state
  with a monotonic version; browser long-polls, re-renders on change. Newly
  appeared findings flash. Stdlib only (http.server + threading + urllib).
- **UI: baseline-diff view** — three-way segment control (new only / all /
  baselined) on the live dashboard; each finding tagged `baselined: true|false`
  in the state payload. Default view hides baselined noise, matching the CI
  gate philosophy.
- **UI: keyboard shortcuts** — j/k navigate, Enter expand, 1/2/3 toggle
  severity, n cycle baseline mode, / focus search, Esc blur / close, ? help
  overlay.
- **`arg.mutable-default` v1** — flags `def f(x=[])`, `x={}`, `x=set()`,
  `x=list()`, `x=dict()`. Deterministic single AST shape, `warn`.
- **`except.reraise-vs-raise` v1** — flags `except X as e: ... raise e`
  where the identifier raised is the `as` alias. Bare `raise` re-raises
  with the original traceback intact; `raise e` truncates it. Deterministic
  single AST shape, `warn`.
- **`cockpit report [--out FILE]`** — single-file HTML report of the current
  findings envelope. Severity filter (block/warn/info), full-text search
  across file/analyzer/symbol, click-to-expand evidence. No CDN, no build
  tools, no runtime dependencies beyond a modern browser. PLAN §7 RISK
  panel MVP.

## 0.1.0 — 2026-09-11

First tagged release. Product state at end of Week 5 execution.

**CLI**
- `cockpit check [--json] [--exit-code] [--exit-at info|warn|block] [--baseline]`
- `cockpit watch [--once]` — mtime polling, NDJSON to stdout
- `cockpit baseline save` — snapshot findings to `.cockpit/baseline.json`

**Analyzers**
- `risk.error-masking` v2 — bare / broad exception + `pass`, non-source paths
  downgraded. Actionable rate 50% on 100-row label sample. Emits `warn`.
- `dup.block` v5 — 5+ line duplicates inside function bodies, string-dominant
  windows filtered, tests/examples/docs downgraded, widespread clusters (>5
  copies) collapsed to single `info`. Actionable rate 28%. Emits `warn`.
- `test.assertion-free` v2, `test.always-true-assertion` v1,
  `test.no-test-for-public-symbol` v1 — all emit `info` after P0 pilot below
  precision threshold; kept for surfacing signal without CI failure. See
  `bench/history/p0_authenticity_v2_result.md`.
- `test.mocks-target` v1 — disabled (P0 stop criterion tripped; needs SUT
  detection). Source kept for future work.

**CI integration**
- `.github/workflows/cockpit.yml` example with baseline + PR comment
- Deterministic finding id (blake2b digest, fixes v0 hash-seed bug)

**Data + research**
- 10-repo benchmark harness (`bench/run.py`)
- Labeling pipeline (`bench/label.py`) — 412 rows labeled across 5 analyzers
- Paper C empirical study — 22,758 (repo, commit, file) observations across
  1,000 commits show warns predict LESS churn (Spearman ρ = -0.44), age
  is not the confounder. See `bench/paper_c/DRAFT_OUTLINE.md`.

**Known limitations**
- Python only (TypeScript queued for post-v0.2)
- test-authenticity analyzers below actionable threshold; `warn` only from
  dup.block and error-masking
- `cockpit` name may conflict on PyPI (unverified); package may need rename
  before public publish
