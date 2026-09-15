# Changelog

## Unreleased

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
