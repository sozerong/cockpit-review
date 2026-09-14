# §5 Discussion (draft)

## 5.1 Four mechanisms consistent with the reversal

The correlation reported in §4 is robust: across 22,758 observations
and ten repositories, files with higher maintainability-warning density
receive substantially less code change in the following 14 days, and
the relationship survives controlling for file age and file size
individually and jointly. Our data cannot definitively separate the
mechanisms that could generate this pattern, but at least four
candidates are compatible with what we observe.

**M1 — Responsibility stability.** Utility or helper modules
accumulate structural patterns (duplicated bodies, defensive `except`
clauses) as they grow to cover many callers. Because they *are* the
utilities, they are called from everywhere and are risky to change,
which suppresses future churn. In our per-repository decomposition
this best fits repositories with strong signal but modest age–warns
correlation (fastapi ρ_wa = −0.18; flask ρ_wa = −0.06): warns cluster
in *newer* framework code that immediately fills a utility role.

**M2 — Maturity resistance.** Once a file exceeds a complexity
threshold, further modification becomes cognitively expensive and is
routed elsewhere (into new files or extensions). The warning density
is not a cause of avoidance so much as a co-symptom of complexity that
is itself the deterrent. This is the "code becomes concrete" thesis
familiar from Lehman's laws.

**M3 — Attention deprivation.** Files that have been allowed to
accumulate warnings without cleanup are also files that no one on the
team feels ownership of. Neglected code stays neglected. This
hypothesis predicts long tails of both high warns *and* long stretches
without any commit — a pattern we plan to test in follow-up work with
authorship density as a covariate.

**M4 — Framework core saturation.** The strongest reversal in our
sample appears in framework code (fastapi ρ = −0.62, flask ρ = −0.65).
Framework cores concentrate routing, decorator, and dispatch patterns
that inevitably repeat structurally, and their public API stability
constrains change. Warnings here are less a maintainability signal and
more a *structural fingerprint of the framework role*.

These mechanisms are not mutually exclusive; each may dominate in
different repositories. What they share is the negation of the
industry-adopted causal frame: none imply that warnings **cause**
future problems, and all imply that intervening to lower warnings on
high-count files would be at best inert and at worst counterproductive
(reducing the code's stability signal without addressing whatever real
defects exist).

## 5.2 The two-part relationship

§4.8 refines the aggregate pattern into a hurdle structure:

1. **Touch probability.** High-warns files are much less likely to be
   modified at all in the next 14 days. This is where the negative
   aggregate signal lives.
2. **Touch volume (conditional).** Among files that are modified, high
   warns is weakly associated with **more** modification (ρ ≈ +0.16).

Interpretation. The four mechanisms in §5.1 explain the touch-
probability effect: framework core (M4), maturity resistance (M2), and
responsibility stability (M1) all reduce the probability that a
utility file will be touched at all. But **conditional on being
opened** for change, high-warns files are structurally harder to
modify surgically — one dup pattern touched leads to related patterns
also touched, one broad `except` clause modified likely surfaces a
second one. This is the (M2) maturity-resistance mechanism operating
*inside* a commit rather than at the commit boundary.

For a review tool, the practical distinction matters: the alert should
fire not on "high warns" (predicts non-change) but on "high warns *and*
now being changed" (predicts wider-than-expected blast radius). We
return to this in §5.3.

## 5.3 Implications for AI-code review tools

If the metric family we test does not predict future rework, tools
that surface it need to reconsider what they alert on.

**From absolute count to delta.** The natural correction is to alert
on rate-of-change: a file whose warning density suddenly spikes
represents a departure from its own baseline, which is a signal our
data does not falsify. On old files, warnings are structural; on young
files, warnings are historical anomalies worth reviewing.

**From file to lifecycle stage.** A file's age is not the confounder
of the warns→churn signal (§4.4), but age is the natural axis for
*whom to alert*. A new file with sudden warnings looks like a helper
being born prematurely — patterns typical of mature utility code
appearing in code the reviewer has not yet had a chance to shape. In
our data this population is under-served: the tools flag old files
that are stable and rarely flag new files that would benefit most from
review.

**Deterministic-vs-LLM framing revisited.** The rise of LLM-based
review has been justified in part by the alleged inadequacy of
deterministic metrics. Our finding is orthogonal to that debate:
deterministic metrics are informative, but *about a different thing*.
An LLM reviewer that adopts the industry causal frame ("warns high →
risk high → prompt user to refactor") will inherit the same
misdirection. The corrective is upstream of the review-engine choice.

## 5.3 What this study does not settle

We do not argue that duplication or exception-swallowing are
*good*. We argue only that measuring their density in a snapshot is a
weak predictor of the outcome (14-day rework) that industry framing
assumes. A stronger predictor may exist within the same data. In
particular:

- Delta measures over prior windows (per §5.2) are untested here.
- The bug-fix subset of churn (as opposed to feature churn) is not
  separated; the reversal may be weaker or absent in that subset.
- The AI-authored subset of commits is not isolated; the reversal
  might be different in commits produced with AI assistance, which is
  the original motivating population.

Each of these is a natural follow-up we invite others to run against
the released dataset.

---

# §6 Threats to Validity

**Rename tracking.** File-level rename tracking is applied to the age
lookup (`git log --follow`) but not to the churn window computation
(`git log --numstat` at repo scope). Files renamed within the 14-day
window may have their churn under-attributed. The direction of this
bias is toward the null: a stronger churn signal would strengthen
whatever direction the H1 correlation takes, so our finding of a
significant negative correlation survives.

**Repository selection.** All ten repositories are popular Python
libraries; enterprise and monorepo settings may exhibit different
dynamics. We prioritized reproducibility and metric-comparable code
style over representativeness; a follow-up on the top 100 PyPI
projects, or on an internal monorepo, would strengthen the
generalizability claim.

**Random commit selection.** Uniform sampling across a repository's
history over-represents periods with dense committing and
under-represents periods with sparse activity. Sampling was seeded so
that the resulting distribution is reproducible; a stratified sample
by year or by activity phase would be a robustness check we did not
run.

**Multivariate confounder space.** We control for age and file size.
Other candidate confounders — file authorship density, module ownership
concentration, whether the file has ever appeared in a bug-fix commit
— are not observed here. The suppressor pattern in §4.5 (loc
partial makes the effect *stronger*) is consistent with unmodeled
positive-confounder structure of file size; we cannot rule out
analogous structure elsewhere.

**Cockpit-metric specificity.** The result depends on the exact metric
definitions in `dup.block v5` and `risk.error-masking v2` released
with this paper. Alternative operationalizations of "duplication" or
"error-masking" may yield different correlations. We release the full
metric specification and code to enable replications with alternative
metric families.

**Aggregation granularity.** We work at file granularity. Function-
or line-level analyses may reveal patterns hidden by file-level
aggregation. This is a natural extension and a follow-up we plan.

**Publication bias.** This reversal is favorable to a broader critical
narrative about AI-coding measurement. We pre-declared H1–H3.5 before
looking at the data and we release the raw observations; readers may
inspect the pipeline and rerun analyses of their choosing.

---

# §7 Conclusion

The industry consensus around AI-assisted coding treats deterministic
maintainability metrics — duplication density, error-masking density —
as leading indicators of trouble. This framing is causal-directional
and consequential: it justifies review tools that alert on absolute
warning counts and prompt refactoring on high-count files.

We tested the *predictive* claim implicit in this framing on
22,758 (repository, commit, file) observations across ten Python
libraries and 1,000 commits. The relationship goes in the opposite
direction: files with higher warning density receive substantially
less code change in the next 14 days (Spearman ρ = −0.44). The
reversal is robust to controlling for file age (partial ρ = −0.44) and
strengthens under joint control of age and file size (ρ = −0.50). The
direction is consistent across every one of the ten repositories in
the sample.

The most parsimonious re-interpretation is that maintainability
metrics function as *stability signals* rather than defect predictors:
they mark code that has settled into a role and is unlikely to churn,
not code that is about to fail. This reframing has a concrete
consequence for AI-code review tooling: alerts should be delta-based
and lifecycle-aware, focused on young files whose warning density
departs from their baseline, rather than on old high-count files that
represent the population these tools currently prioritize.

We release the full analysis pipeline, per-commit observations, and
the deterministic analyzer code as `cockpit-review` at
`github.com/sozerong/cockpit-review`. All correlations and confidence
intervals reported here reproduce from a single seeded run.

---

## Appendices (outlines only — full tables in released artifacts)

**Appendix A. Repository list and clone pins.** URLs, sampled commit
ranges, seed values.

**Appendix B. Test-file subgroup analysis.** Same H1–H3.5 tables
restricted to `tests/`, `docs/`, `examples/` files. Preliminary run
suggests attenuated but same-direction signal — noise from fixture
churn.

**Appendix C. Robustness tables.** 7-day and 30-day churn window,
weighted per-repo aggregation, raw-count (no log) alternative.

**Appendix D. Analyzer specification.** Exact `tree-sitter` queries,
severity/downgrade rules, deterministic hashing scheme.

**Appendix E. Illustrative flagged files.** A handful of dup-heavy
and dup-light files from each repo with 14-day churn observed,
annotated for hand inspection.
