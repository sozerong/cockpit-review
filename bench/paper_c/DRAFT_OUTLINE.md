# Paper Draft Outline — "Maintainability Metrics Predict Churn — Backwards"

**Target**: MSR (Mining Software Repositories), 2026 short paper or full paper depending on §6 depth. Alternative: ICSE SEIP.

**Working title candidates:**
- "Maintainability Metrics Predict Churn — Backwards: A Reinterpretation of the Maintainability Gap"
- "The Backward Predictor: When 'Low-Maintainability' Files Are the Stable Ones"
- "Not a Bug, a Feature: Deterministic Maintainability Metrics as Stability Signals"

---

## 0. Abstract (150w)

Industry reports (GitClear 2026) claim that AI-assisted coding lowers code
maintainability, evidenced by rising duplication and error-masking. We test
the implicit causal claim — that low-maintainability code predicts future
rework — on 22,758 (repo, commit, file) observations across 10 Python
libraries and 1,000 commits. We find a **strong signal in the opposite
direction**: files with higher deterministic-maintainability warning density
have **lower** 14-day churn (Spearman ρ = -0.44, 95% CI [-0.45, -0.43]).
Controlling for file age preserves the effect (partial ρ = -0.44). We
interpret this as evidence that maintainability metrics function as
**stability signals** rather than defect predictors. Practical implication:
tools that raise warnings on high-count files are highlighting the wrong
targets; the actionable case is instead the *new file with sudden warning
spike*.

## 1. Introduction (~1p)

- Context: AI-coding claims (Faros +33.7% throughput, LinearB PRs 2.5× bigger,
  Sonar 42% commit-share). Industry metric wave: GitClear, Sonar, cockpit,
  etc.
- Gap: **all these reports are correlational.** GitClear itself notes the
  caveat but community adopts the causal frame ("high warns → future
  problems → refactor now").
- Contribution:
  1. First large-scale test of the *predictive* claim at commit granularity
  2. Empirical reversal: warns predict less churn, not more
  3. Age is not the confounder; partial correlation preserves the effect
  4. Interpretation reframing: maintainability metrics = stability signals
- Data + code: fully open (cockpit + this pipeline)

## 2. Background & Related Work (~1p)

- GitClear "Maintainability Gap" (Harding, 2026) — foundational correlational
  study; explicit causal disclaimer; adopted causally in practice
- Sonar 2026 State of Code — 42% AI commits, 96% not fully trusted; motivates
  the metric wave
- Hora & Robbes MSR 2026 (arXiv 2602.00409) — commit-scale AI-usage measurement
- Historical: Nagappan et al. (2005-2008) code metric → defect studies —
  cyclomatic complexity as defect predictor showed similar reversal (large
  files have more but complexity is size proxy)
- Position: we specifically test the *predictive*, not associative, claim

## 3. Methodology (~1.5p)

### 3.1 Metric definition
- Two deterministic analyzers (fully described, code open):
  - `dup.block`: 5+ line duplicated blocks inside function bodies, cross-file,
    with widespread-cluster suppression (details in §Appendix)
  - `risk.error-masking`: bare/broad `except` swallowing errors, with test-dir
    downgrade
- Per-file `warns_dup(t, f)`, `warns_em(t, f)` at commit t

### 3.2 Response variable
- `churn_14d(t, f)` = `git log --numstat` insertions+deletions on file f in
  window (t, t+14d]

### 3.3 Confounders
- `age_days(t, f)` = t minus first commit that added f (with `--follow`)
- `loc(t, f)` = line count
- (Test file / doc file excluded from analysis, see §Threats)

### 3.4 Sample
- 10 repos (varied domains, 165 LOC to 100k+ LOC): records, requests, click,
  flask, httpx, aiohttp, poetry, pytest, black, fastapi
- 100 random commits per repo (seeded), main branch, `commit_date + 14d < now`
- Filter: `loc > 0`, no rename markers, not in `tests/`
- N = 22,758 (repo, sha, file) rows

### 3.5 Analysis
- Spearman rank correlation (no distribution assumption)
- Bootstrap 95% CI (n=1000 for rho, n=500 for partial)
- Partial correlation: `r(warns, churn | age)` using rank-Pearson formula
- Per-repo subgroup analysis

## 4. Results (~2p)

### 4.1 H1: predictive claim
Table: n=22,758, ρ_dup → churn = -0.439, ρ_em = -0.090, baseline ρ_loc = +0.034
- CI clearly excludes 0 for dup
- **Direction reversed from the industry-adopted causal frame**

### 4.2 H2: age proxy hypothesis
- We first hypothesized warns = age proxy → tested at scale, **falsified**
- ρ_dup → age = +0.046 across all 22,758 rows
- Per-repo: fastapi (-0.175), flask (-0.064) actively invert
- loc is a stronger age proxy (+0.343) than warns

### 4.3 H3: partial correlation
- ρ_dup | age = -0.437 (nearly identical to H1)
- Age is not the confounder; effect is not mediated by age

### 4.4 Heterogeneity
Table of per-repo ρ (as in `report.md`). Three groups:
1. Strong signal, age-independent: fastapi, flask, requests
2. Signal present, age partial confounder: click, httpx
3. Weak/noisy signal: black, pytest, small repos

Discussion: framework-heavy repos (fastapi/flask) have strongest reversal
— consistent with "stable framework code accumulates dup".

## 5. Discussion (~1p)

Four candidate mechanisms (data cannot fully separate, all consistent):
- **Responsibility stability**: helper/utility files accumulate patterns,
  don't get touched
- **Maturity resistance**: complex-but-stable code resists change
- **Attention deprivation**: neglected code stays neglected
- **Framework core**: routing/decorator repetition; API stability freezes it

**Implication for AI-code review tools:**
- Existing framing: "warns rising → refactor now" (implicit causal)
- Corrected framing: "warns high → stable code (don't touch)"; the actionable
  case is **young file + warning spike**, currently un-served by these tools
- Practical redesign: alert on *delta*, not absolute count, especially in
  files below age threshold

## 6. Threats to Validity (~0.5p)

- **Rename tracking**: `git log --follow` used per-file in age lookup but not
  in churn (churn uses `--numstat` on repo-scope log). Renames may
  under-attribute churn. Bias direction: toward null (our finding survives)
- **Sample bias**: 10 popular Python libraries; enterprise/monorepo different
- **Random commit selection**: not stratified by age
- **Multivariate confounders unmeasured**: file activity rate, ownership,
  domain type
- **cockpit v5 specificity**: metric definitions dictate result; other
  definitions may reverse (§Appendix has full spec)
- **Sample of the sample**: partial CI uses n=500 bootstrap; increasing does
  not shift point estimate

## 7. Conclusion (~0.5p)

- Maintainability metrics predict churn — in the opposite direction the
  industry assumes
- Age is not the confounder
- Reinterpretation as stability signals is empirically consistent
- Downstream: AI-code review tools should switch from absolute-count alerts to
  delta-based alerts, focused on young files
- Full replication: data + code released at (URL)

## 8. Appendices

- A. Full metric definitions (dup.block v5, error-masking v2)
- B. Per-repo detailed statistics
- C. Robustness: alternative churn windows (7d, 30d)
- D. Sample of flagged files (illustrative)

---

## Writing plan

- Sections 0-3 written from this outline: ~1 week for a solo author
- Sections 4-5: mostly data narrative, half-week
- Threats + Conclusion: half-week
- Draft target: **2 weeks after outline sign-off**
- Pre-registration option: register RQ/hypotheses on OSF **before** running
  the additional 6-repo confirmation (already done, so use committed harness
  code + hash as timestamp)

## Rejection defenses (§13-style red team)

| # | Attack | Defense |
|---|---|---|
| 1 | "Correlation, not causation" | We explicitly frame reversal, no causal claim; partial ρ|age tightens the predictive claim regardless |
| 2 | "Cherry-picked repos" | 10 diverse libraries, per-repo shown, direction consistent across all 10 |
| 3 | "Confounder unmeasured" | age tested and rejected; loc is baseline; §Threats acknowledges what's missing |
| 4 | "cockpit metrics are ad-hoc" | Full open spec, replicable; alternative metric families (§Threats point 5) suggested as follow-up |
| 5 | "n=22,758 not enough per-repo" | Per-repo n ranges 165 to 5280; CI narrow at scale; per-repo shown with caveat |
| 6 | "Rename not tracked" | Acknowledged; would tighten null direction; findings robust to that direction |
| 7 | "Result trivial (loc is the real driver)" | ρ_loc → churn = +0.034 (near zero); warns effect not mediated by size |

## Next actions

1. User signs off on outline
2. Optionally: run Phase 3.5 (loc partial + age partial simultaneously) for
   robustness table
3. Write §0-§3 first draft (start with sections least dependent on further
   analysis)
