## cockpit-review 0.1.0

First tagged release of **cockpit** — a local, deterministic code reviewer for Python. Every finding is computed from AST, graph, and hash primitives; there are no LLM calls in the analysis path. The reviewer stays the judge; the tool brings evidence.

### What's inside

Five analyzers, tuned against a 412-row labeled sample across 10 repositories:

- `risk.error-masking` v2 — bare / broad `except: pass`. Actionable 50% on labels. **warn**
- `dup.block` v5 — 5+ line intra-function duplicates, string-dominant windows filtered, widespread clusters collapsed. Actionable 28%. **warn**
- `test.assertion-free` v2 — **info**
- `test.always-true-assertion` v1 — **info**
- `test.no-test-for-public-symbol` v1 — **info**

CLI: `cockpit check` (table or `--json` schema-v1 envelope), `cockpit watch` (mtime polling, NDJSON), `cockpit baseline save`, and `cockpit report` — a single-file HTML view with severity filter, full-text search, and click-to-expand evidence (no CDN, no bundler).

### Install

```bash
pip install cockpit-review
```

### Quick start

```bash
cockpit check                     # analyze current directory
cockpit check --exit-at warn      # CI gate
cockpit report --out review.html  # shareable HTML findings view
```

### Verify

```bash
cockpit --version
cockpit check --json | head
```

### Research

Empirical study **Paper C** — 22,758 (repo, commit, file) observations across 1,000 commits show `warn` findings predict *less* subsequent churn (Spearman ρ = −0.44); age is not the confounder. See `bench/paper_c/DRAFT_OUTLINE.md`.

### Known limits

- Python only — TypeScript queued behind `dup.block` v6.
- `test.mocks-target` v1 is shipped disabled: the P0 authenticity pilot tripped the §13.5 stop criterion because the analyzer lacks system-under-test detection; source is retained for follow-up work.
- The three `test.*` analyzers emit `info` only (below the actionable-precision threshold); `warn` currently comes from `dup.block` and `risk.error-masking`.
- Self-scan baseline is ~26 findings — committed as `.cockpit/baseline.json` so CI only fails on *new* findings.

Full CI example: `.github/workflows/cockpit.yml`. Tuning history per analyzer: `bench/history/`.
