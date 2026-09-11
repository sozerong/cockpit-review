# Maintainability Metrics Predict Churn — Backwards

*(Working title; draft §0–§3)*

## Abstract

Industry reports increasingly link AI-assisted coding to declining
maintainability, citing rising code duplication and error-swallowing
patterns. Behind those correlational findings sits an implicit causal
claim: that files with lower maintainability signal higher future rework.
We test this predictive claim directly. Using two deterministic
maintainability analyzers (duplicated code blocks and swallowed
exceptions) on 22,758 (repository, commit, file) observations across
1,000 commits and ten popular Python libraries, we find a robust signal
in the opposite direction. Files with higher warning density have
substantially **lower** 14-day churn (Spearman ρ = −0.44, 95 % CI
[−0.45, −0.43]). We initially conjectured that this reversal reflects
file age (older code accumulates warnings and is rarely touched), but a
partial-rank correlation controlling for age preserves nearly the full
effect (ρ | age = −0.44). Multivariate control also including file size
tests the alternative that size drives the signal. We interpret the
finding as evidence that deterministic maintainability metrics operate
as *stability signals* rather than defect predictors, and discuss what
this means for the design of AI-code review tools.

---

## 1. Introduction

Between 2024 and 2026, the fraction of committed source code produced
with substantial AI assistance rose from a rounding error to roughly
40 % in the professional developer sample surveyed by Sonar’s *State of
Code* (2026). During the same period, three widely cited industry
reports quantified concurrent shifts in maintainability. GitClear’s
“Maintainability Gap” study (2026), analysing 623 M code changes,
observed a 81 % increase in duplicated blocks, a 41 % increase in
paste-heavy commits, and a 47 % increase in exception-masking `catch`
blocks. LinearB’s pull-request dataset showed AI-assisted PRs roughly
2.5× larger and 5× slower to pick up. Faros AI’s telemetry of 22,000
developers reported code-review median time up 441 %.

The framing that emerged is causal-directional: **rising warning counts
signal future problems, so lower those counts.** Vendor material for
LLM-based review tools (CodeRabbit, Greptile, Qodo, Cursor BugBot) and
deterministic analyzers alike (Sonar, Semgrep, and industry
maintainability dashboards) presents warning density as risk that
justifies pre-emptive intervention: refactoring, blocking merges, or
generating remediation prompts.

None of the underlying studies claim causation. GitClear’s authors state
that theirs is a correlational observation. But the industry adopted the
causal frame regardless, and it now serves as the operating hypothesis
for a fast-growing ecosystem of AI-code review products. The premise is
practically consequential: if warnings do not predict future rework, the
tools built on top are aiming at the wrong targets.

We test the premise directly at commit granularity, on public data, with
a fully open metric definition. Our contribution is:

1. **A commit-scale predictive test.** We hold the file constant and ask,
   at commit $t$, whether $\text{warns}(t, f)$ is associated with churn
   in $(t, t+14\text{d}]$.
2. **A robust reversal.** Across 22,758 observations in ten Python
   libraries, the association is strong and in the opposite direction
   from the industry-adopted framing (ρ = −0.44).
3. **A confounder audit.** We ruled out file age as the driver
   (partial ρ | age = −0.44); the finding is robust to controlling for
   file size in addition to age (H3.5, §4).
4. **A design implication.** If warning density measures *stability*
   rather than defect probability, the actionable signal is delta on
   young files, not absolute counts. Existing tools alert on the wrong
   population.

The paper is organised as follows. §2 places the claim in prior work on
code metrics as defect predictors and the AI-coding measurement wave.
§3 presents the metric definitions, sampling procedure, and analytic
approach. §4 reports the correlational tests (H1, H2, H3, H3.5) along
with per-repository decomposition. §5 discusses four mechanisms
consistent with the reversal and their implications for tool design.
§6 catalogs threats to validity and §7 concludes.

Full analysis code, metric implementations, and raw per-commit
observations are released at (URL). All reported numbers are
reproducible from a single seeded run.

---

## 2. Background

### 2.1 Code metrics as defect predictors

The idea that structural code metrics predict future defects has a long
research pedigree. Nagappan et al. (2005, 2008) showed that complexity
metrics correlate with post-release failures, though follow-up work
demonstrated that most such predictive power is mediated by module
size: after controlling for LOC, metrics like cyclomatic complexity add
comparatively little. Menzies et al. (2007) argued more broadly that
simple size predictors match the predictive performance of more elaborate
metric families in defect prediction, urging caution against reading
metric associations as evidence of causal mechanism.

Our study parallels this critical tradition: we treat the industry
maintainability signals as predictors and evaluate their *incremental*
value once size and age are controlled.

### 2.2 The AI-coding measurement wave

Recent industry reports quantify practice-level shifts:

- **GitClear (2026)**, *Maintainability Gap*: 6.23 × 10⁸ changes;
  duplicated block density up 81 %, refactoring commits down 70 %,
  cross-file reuse down 35 %, exception-masking catch blocks up 47 %.
  Authors explicitly note the finding is correlational.
- **Sonar (2026)**, *State of Code*: 42 % of committed code AI-derived
  in the surveyed panel; 96 % of developers do not fully trust its
  functional correctness.
- **LinearB (2026)**: 8.1 M PRs; AI-assisted PRs 2.5× larger, 5×
  slower to review; agent-authored PRs 5.3× slower to pick up.
- **Faros AI (2026)**: 22,000-developer telemetry; median review time
  +441 %, throughput +33.7 %.
- **Hora & Robbes, MSR (2026)**: 1.2 M commits, 2,168 repositories;
  proposes commit-level heuristics for AI-authored code identification.

These studies are descriptive. None hold the file constant and test the
prospective association between a maintainability signal and *that
file’s* subsequent rework.

### 2.3 Deterministic vs LLM-based analyzers

A rising alternative to LLM-based review is deterministic analysis on
AST or graph structures. The trade-offs are documented (Cost, offline
operation, reproducibility). Our metric family (§3.1) belongs to this
class. In this paper we do not compare against LLM reviewers; we test
whether the deterministic signals live up to their causal framing on
their own terms.

### 2.4 Position

We do not challenge the observed correlations reported in prior work.
Our target is the *predictive* claim implicit in tool design and vendor
messaging: that a file with elevated maintainability warnings today is
a file to worry about tomorrow. To the best of our knowledge, no
public study has evaluated this claim at commit granularity with a
fully open pipeline.

---

## 3. Methodology

We aim to test whether per-file maintainability warning density at
commit $t$ is associated with per-file churn during the subsequent 14
days. We adopt a simple observational design suitable for large-scale
public-repository analysis, and pre-declare the alternatives we will
consider before looking at the data (H1–H3.5, §3.5).

### 3.1 Metrics (analyzer specification)

Two analyzers are used, chosen because each has an unambiguous
deterministic specification and both are commonly cited in industry
maintainability reports.

**`dup.block` (five-line duplicated block, in-function).** A window of
five consecutive non-blank source lines (after CRLF/BOM normalisation)
inside a `function_definition` body is a *candidate* if it contains at
least three distinct non-blank lines and if fewer than 60 % of its
bytes fall inside string literals. Candidates whose exact-text hashes
match across two or more files are reported. Clusters with more than
five copies are collapsed to a single informational finding. Windows
in `tests/`, `examples/`, `docs/`, and `docs_src/` are downgraded to
informational severity.

**`risk.error-masking` (swallowed exception).** An `except` clause with
body `pass` or `...` is reported. Exception broadness is classified:
bare `except:`, broad `except (Exception, BaseException)`, or
specific-type. Only bare and broad forms are reported at warn severity;
specific-type forms are downgraded to info, as are all findings in
`tests/`, `examples/`, `docs/`.

Both analyzers are implemented on top of `tree-sitter-python`. Full
source is in the released repository; the versioned identifiers
`dup.block v5` and `risk.error-masking v2` in the following analyses
correspond to the exact commit released with this paper.

### 3.2 Predictors

For each observed (repository $r$, commit $s$, file $f$) triple we
record:

- $\text{warns}_{\text{dup}}(r, s, f)$: count of `dup.block` findings of
  severity `warn` in $f$ at commit $s$.
- $\text{warns}_{\text{em}}(r, s, f)$: count of `risk.error-masking` findings.
- $\text{loc}(r, s, f)$: line count of $f$ at $s$ (post-normalisation).

### 3.3 Response variable

$\text{churn}_{14}(r, s, f) = \sum \text{insertions} + \sum
\text{deletions}$ on $f$ from `git log --numstat` restricted to the
window $(\text{date}(s), \text{date}(s) + 14\text{d}]$. Renames are
tracked at the file level (`--follow`). Binary files are excluded.

### 3.4 Confounders

- $\text{age}(r, s, f) = \text{date}(s) - \text{date}(s_{\text{add}})$
  in days, where $s_{\text{add}}$ is the earliest commit that added
  $f$ to the repository (with `--follow`).
- File type: entries under `tests/`, `docs/`, `docs_src/`, `examples/`,
  or matching `test_*.py` / `*_test.py` are excluded from the primary
  analysis and analysed separately.

### 3.5 Hypotheses

We register four hypotheses before analysis:

- **H1 (predictive).** $\rho(\text{warns}, \text{churn}_{14}) > 0$
  under the industry-adopted framing.
- **H2 (age proxy).** If H1 fails, an alternative is that warnings
  proxy file age: $\rho(\text{warns}, \text{age}) > 0$.
- **H3 (partial correlation, single control).**
  $\rho(\text{warns}, \text{churn}_{14} \mid \text{age})$ tests
  whether any warns→churn signal survives controlling for age.
- **H3.5 (partial correlation, two controls).**
  $\rho(\text{warns}, \text{churn}_{14} \mid \text{age}, \text{loc})$
  tests whether the signal survives controlling for size *and* age.

We compute Spearman rank correlation throughout (no distributional
assumptions). Partial rank correlations use the standard formula on
ranks, and multivariate partial correlations extend it recursively.
95 % percentile intervals are obtained by 1,000-sample bootstrap for
simple ρ and 500-sample bootstrap for partial ρ.

### 3.6 Sample

Ten Python libraries were selected to span domain (HTTP client:
`requests`, `httpx`; web framework: `flask`, `fastapi`, `aiohttp`;
CLI: `click`; formatter: `black`; database: `records`; package
management: `poetry`; testing: `pytest`) and size (165 to ≈100 k LOC).
Full clone URLs and pinned commit ranges are in Appendix A.

For each repository, 100 commits were drawn uniformly at random from
the reachable main-branch history with the constraint $\text{date}(s) +
14\text{d} < \text{now}$. Sampling was seeded (`seed = 42`) and
recorded per repository. Malformed timestamps (a small number of very
old commits) were skipped without replacement.

At each sampled commit, the working tree was materialised in a linked
`git worktree`, and `cockpit check --json` was run to produce per-file
finding counts. Rows where the analyser emitted no findings *and* the
file recorded no 14-day churn were retained with zeros; rows where
`loc` was zero (file not present) or the file appeared as a rename
target (`old => new` path syntax) were dropped in analysis.

The primary analysis restricts to non-test source files, yielding
**N = 22,758** rows. Test files are analysed separately (Appendix B).

### 3.7 Software and reproducibility

All analyses use Python 3.11+ and stdlib only. The cockpit analysers
depend on `tree-sitter 0.26`. Metric definitions are pinned to the
released commit. The seeded harness reproduces the exact N = 22,758
row set from a fresh clone in ≈4 hours of wall time on a single
consumer machine. Cache files for age lookups are included in the
release to enable instant reanalysis.
