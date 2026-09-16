# cockpit-review roadmap

A living document. Goal-line: startup-grade deterministic code reviewer,
distributable as a local CLI and hostable as a PR-review SaaS.

## M0.2 · Local tool finished — target 2026-09-30

Deterministic Python analyzer with a real test suite, real distribution.

- [x] Live dashboard (`cockpit serve`) with SYSTEM panel visualization
- [x] i18n EN / KO
- [x] `except.reraise-vs-raise` v1, `arg.mutable-default` v1, `test.time.sleep` v1
- [x] pytest suite — 37 tests, 44% line coverage as of 2026-09-16
- [ ] pytest coverage → 70%+ (migrate remaining demo() self-checks: dup.block,
      error-masking, assertion-free, always-true-assertion, no-test-for-public)
- [ ] `test.mocks-target` v2 with SUT detection (re-enable after ≥0.75 precision pilot)
- [x] **Incremental scan** — target hit. fastapi 1138 files:
      cold 5.4s (from 12.5s), warm 1-file edit 212ms (from 2.9s), 27× vs cold.
      Three commits: IncrementalScanner + dup.block window cache +
      FS-walk cache + normalize_path fast path + no-test-for-public cache + O(1) test index.
- [ ] Cross-platform CI on Linux + macOS + Windows (added, needs green run)
- [ ] PyPI publish v0.2.0
- [ ] GitHub Release with wheel + sdist artifacts

## M0.5 · Team tool — target 2026-11-15

Small teams (10-100 engineers) use it as part of code review.

- [ ] **TypeScript / JavaScript support** — start with `dup.block` and
      `risk.error-masking` on tree-sitter-typescript
- [ ] **Error UX** — surface indexer failures with file paths and
      recovery hints in both CLI and dashboard
- [ ] **Team baseline sharing** — `.cockpit/baseline.json` committed to git,
      dashboard shows PR diff view (added findings only)
- [ ] **Docs site** — analyzer-per-page details at
      docs.cockpit-review.dev, hosted on GitHub Pages
- [ ] **brew / scoop** distribution
- [ ] Public benchmark leaderboard (already have data — publish `bench/history/` as
      a page)

## M1.0 · SaaS — target 2027-Q1

Hosted service. Real product.

- [ ] **GitHub App** — auto-review every PR, comment with findings
- [ ] **Web dashboard** — per-repo history, per-contributor breakdown, trends
- [ ] **Auth / billing / team management** — Clerk + Stripe
- [ ] **Observability** — Sentry, PostHog, opt-in usage telemetry
- [ ] **Persistence** — Postgres, finding history retained across scans
- [ ] **API** — CLI can talk to hosted server; local + cloud modes share findings
- [ ] **Reproducibility** — every finding on the web dashboard links to the exact
      commit + analyzer version that produced it

## Beyond 1.0 · defensible product

- Multi-language: Go, Rust, Java, Kotlin
- Enterprise: SAML, VPC deployment, SOC2
- LLM-assisted **outputs** (refactor prompts, PR summaries) — never in the
  detection path, always downstream of a deterministic finding
- Custom rule DSL — teams define their own patterns without writing Python

## Analyzer ideas — the wishlist

- **`ponytail.reinvented`** — detect code that a stdlib call or a
  common library would replace in 1-3 lines. E.g. hand-written
  `for x in lst: if x == target: return True` → `target in lst`;
  manual retry loop → `tenacity`; custom lru cache → `functools.lru_cache`;
  hand-written CSV split → `csv.reader`. The tool literally practising
  what its own philosophy preaches. Idea from a user in Sep 2026 —
  "you built it the hard way, turns out there's a library and 3 lines
  would've done it."

## Goals stated as constraints

- **No LLM in the analysis path** — every finding derives from AST + graph +
  hash, always reproducible. Determinism is the product's moat.
- **Zero-config first run** — clone → `pip install cockpit-review` → run
- **Ships on Windows, macOS, Linux** — every release verified on all three
- **Sub-second checks on repos ≤ 500 files** — the loop of a live tool must
  feel free
- **First-party observability** — a real product knows when it fails; every
  crash or bad exit is logged and surfaces to us
