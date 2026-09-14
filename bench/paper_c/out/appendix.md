# Paper C — Appendices

## Appendix A. Repository sample summary

Each repository was cloned to `bench/clones/<name>` and sampled at
100 uniformly-random reachable-from-HEAD commits with `seed = 42`,
subject to `commit_date + 14d < now`.

| Repo | Rows (all, pre-filter) | Earliest sampled | Latest sampled |
|---|---:|---|---|
| aiohttp | 4214 | 2014-03-31 | 2026-08-13 |
| black | 1965 | 2018-03-16 | 2026-08-03 |
| click | 1723 | 2014-04-25 | 2026-08-15 |
| fastapi | 9536 | 2018-12-10 | 2026-07-27 |
| flask | 1149 | 2010-04-16 | 2026-07-30 |
| httpx | 2684 | 2019-04-06 | 2025-10-04 |
| poetry | 7367 | 2018-02-28 | 2026-05-03 |
| pytest | 5290 | 2007-02-04 | 2026-08-19 |
| records | 336 | 2016-02-06 | 2026-02-08 |
| requests | 2288 | 2011-02-14 | 2025-02-13 |

## Appendix B. Test-file subgroup

Restricted to `tests/`, `testing/`, `test_*.py`, `*_test.py`. N = 10997.

H1 restricted to tests:

| Variable | ρ | 95% CI |
|---|---:|---|
| log(warns_dup + 1) → log(churn₁₄ + 1) | +0.000 | [+0.000, +0.000] |
| log(warns_em + 1) → log(churn₁₄ + 1)  | +0.000 | [+0.000, +0.000] |

## Appendix C. Robustness checks

### C1. Raw-count (no-log) alternative

Spearman is rank-invariant, so log transformation should not change
the coefficient. Included as a sanity check.

| Variable | ρ | Note |
|---|---:|---|
| warns_dup vs churn_14d (raw) | -0.429 | ranks unchanged, identical to H1 |

### C2. Fisher-z weighted per-repository mean

Each per-repo Spearman ρ (warns_dup, churn_14d) is Fisher-z
transformed, weighted by (n − 3), aggregated, and back-transformed.
This aggregation gives every repo comparable weight regardless of the
aggregate correlation being potentially driven by one large repo.

| Aggregate ρ̄ (Fisher-z weighted) | 95% CI (Fisher-z + normal) |
|---:|---|
| -0.413 | [-0.424, -0.401] |

Per-repo Fisher-z values:

| Repo | ρ_dup | Fisher z | weight (n-3) |
|---|---:|---:|---:|
| poetry | -0.411 | -0.437 | 5277 |
| fastapi | -0.623 | -0.730 | 3646 |
| pytest | -0.260 | -0.266 | 2907 |
| aiohttp | -0.320 | -0.332 | 2602 |
| requests | -0.345 | -0.360 | 1728 |
| click | -0.373 | -0.392 | 1242 |
| httpx | -0.288 | -0.296 | 1235 |
| black | -0.261 | -0.268 | 1107 |
| flask | -0.649 | -0.774 | 923 |
| records | -0.279 | -0.287 | 162 |

### C3. Restricted to rows with any 14-day churn

N = 13620 (of 20859 src-file rows).

| Variable | ρ | 95% CI |
|---|---:|---|
| log(warns_dup + 1) → log(churn₁₄ + 1), churn > 0 | +0.163 | [+0.147, +0.180] |

### C4. Alternative churn windows (not run)

Computing correlations at 7-day and 30-day windows requires
re-running the harness with additional `git log` invocations per
commit. The pipeline is designed to support it (one column addition
in `harness.py`) but the full 10-repo × 100-commit run takes ~4 h.
This is scheduled as a follow-up and its expected direction is the
same as H1 based on the correlation structure observed here.
