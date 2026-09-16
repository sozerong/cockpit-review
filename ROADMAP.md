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
- [ ] **Incremental scan** — only rescan changed files. Target: fastapi 5.8s → <200ms
      after first scan (fastapi live save-to-update currently 7.4s; incremental is the
      biggest UX blocker measured)
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

## Goals stated as constraints

- **No LLM in the analysis path** — every finding derives from AST + graph +
  hash, always reproducible. Determinism is the product's moat.
- **Zero-config first run** — clone → `pip install cockpit-review` → run
- **Ships on Windows, macOS, Linux** — every release verified on all three
- **Sub-second checks on repos ≤ 500 files** — the loop of a live tool must
  feel free
- **First-party observability** — a real product knows when it fails; every
  crash or bad exit is logged and surfaces to us
