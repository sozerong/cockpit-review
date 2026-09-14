# §4 Results (draft)

## 4.1 Descriptive summary

Table 1 summarises the analytic dataset.

| Quantity | Value |
|---|---:|
| Repositories | 10 |
| Commits sampled | 1,000 (100 per repo) |
| (repo, commit, file) observations, pre-filter | ≈ 32 k |
| Observations after filter (src files only, `loc > 0`, no renames) | **22,758** |
| Observations with age available | 22,714 |
| Median `warns_dup` | 0 |
| 90th percentile `warns_dup` | 4 |
| Median `warns_em` | 0 |
| Median `churn_14d` | 0 |
| 90th percentile `churn_14d` | 47 |
| Median `loc` | 168 |
| Median `age_days` | 1,082 |

The distributions of `warns_dup`, `warns_em`, and `churn_14d` are all
heavily right-tailed with a mass at zero. All subsequent analyses use
`log(x + 1)` transforms.

## 4.2 H1 — the predictive claim

We test whether $\rho(\log(\text{warns}+1), \log(\text{churn}_{14}+1))$
is positive, as the industry-adopted framing implies. Table 2 reports
Spearman rank correlations with bootstrap 95 % confidence intervals.

**Table 2. H1: warning density vs subsequent 14-day churn.**

| Variable | ρ | 95 % CI |
|---|---:|---|
| log(warns_dup + 1) → log(churn₁₄ + 1) | **−0.439** | [−0.452, −0.426] |
| log(warns_em + 1) → log(churn₁₄ + 1)  | −0.090 | [−0.103, −0.076] |
| log(loc + 1) → log(churn₁₄ + 1) (baseline) | +0.034 | — |

The dup coefficient is large by observational-study standards, and its
confidence interval decisively excludes zero. The sign is opposite to
the direction the industry framing predicts. The `em` coefficient is
small but consistent in direction. Line count, notably, has essentially
no bivariate association with 14-day churn on this dataset.

**H1 is rejected in favour of a strongly reversed association.**

## 4.3 H2 — is warning density an age proxy?

Faced with H1’s reversal, the natural alternative is that
maintainability warnings simply proxy file age: warns accumulate as
files persist, and old files by definition are files nobody has yet
touched. Table 3 reports the direct correlation.

**Table 3. H2: warning density vs file age (days since first commit).**

| Variable | ρ | 95 % CI |
|---|---:|---|
| log(warns_dup + 1) → log(age + 1) | **+0.046** | [+0.033, +0.058] |
| log(warns_em + 1) → log(age + 1)  | +0.104 | [+0.091, +0.118] |
| log(loc + 1) → log(age + 1) (baseline) | +0.343 | — |

Contrary to our own initial conjecture, `warns_dup` is essentially
uncorrelated with age. `loc` is the far stronger age proxy. On four of
ten repositories the sign inverts: fastapi (−0.175) and flask (−0.064)
have their warning-heavy files skewed toward *newer* code, consistent
with framework routing code accumulating dup patterns as it grows.

**H2 is not supported at scale**, though on some repos (records +0.599,
httpx +0.492) it holds strongly, indicating meaningful heterogeneity
that we return to in §4.6.

## 4.4 H3 — partial correlation controlling for age

Even where the bivariate H2 correlation is small, age could still
confound H1 heterogeneously across the sample. We compute the partial
Spearman correlation on ranks:

$$\rho(\text{warns}, \text{churn} \mid \text{age}) = \frac{\rho_{wc}
- \rho_{wa}\rho_{ca}}{\sqrt{(1 - \rho_{wa}^2)(1 - \rho_{ca}^2)}}$$

**Table 4. H3: partial correlation with age controlled.**

| Variable | ρ ∣ age | 95 % CI |
|---|---:|---|
| log(warns_dup + 1) ∣ age | **−0.437** | [−0.451, −0.425] |
| log(warns_em + 1) ∣ age  | −0.084 | [−0.097, −0.071] |

The dup partial correlation is essentially indistinguishable from the
bivariate H1 estimate (−0.439). Controlling for age changes the answer
by less than half a hundredth. **Age is not the confounder.**

## 4.5 H3.5 — multivariate partial correlation, age *and* size controlled

An alternative explanation for a reviewer to raise is that large files
have both more warnings and more churn, and that some of the H1
reversal is nonetheless age- and size-mediated. We compute the recursive
two-variable partial:

$$\rho(w, c \mid a, l) = \frac{\rho(w, c \mid a) - \rho(w, l \mid a)
\rho(c, l \mid a)}{\sqrt{(1 - \rho(w, l \mid a)^2)(1 - \rho(c, l \mid a)^2)}}$$

**Table 5. H3.5: partial with age AND loc controlled.**

| Variable | ρ ∣ age, loc | 95 % CI |
|---|---:|---|
| log(warns_dup + 1) ∣ age, loc | **−0.495** | [−0.507, −0.485] |
| log(warns_em + 1) ∣ age, loc  | −0.091 | [−0.103, −0.077] |

The dup coefficient becomes **larger** in absolute value after
controlling for size. This is a positive-suppressor pattern: size is
positively associated with both `warns_dup` and `churn_14d`, so partial
correlation removes a variance component that was masking the pure
warns→churn relationship. The reversal is not driven by size; if
anything, size was hiding some of it.

The `em` partial is unchanged.

## 4.6 Per-repository decomposition

**Table 6. Per-repository correlations (dup only; em omitted where CI
crosses zero at repository scale).**

| Repo | N | H1 ρ | H2 ρ | H3 ρ ∣ age |
|---|---:|---:|---:|---:|
| aiohttp | 2,605 | −0.320 | +0.195 | −0.317 |
| black | 1,110 | −0.261 | +0.055 | −0.257 |
| click | 1,245 | −0.373 | +0.446 | −0.266 |
| fastapi | 3,649 | **−0.623** | −0.175 | **−0.608** |
| flask | 926 | **−0.649** | −0.064 | **−0.653** |
| httpx | 1,238 | −0.288 | +0.492 | −0.106 |
| poetry | 5,280 | −0.411 | +0.133 | −0.394 |
| pytest | 4,809 | −0.252 | +0.154 | −0.268 |
| records | 165 | −0.279 | +0.599 | −0.280 |
| requests | 1,731 | −0.345 | −0.041 | −0.356 |

Three qualitative patterns are visible.

- **Strong reversal, age-independent** (fastapi, flask, requests): H1 is
  large and negative; H2 is near zero or negative; H3 preserves the H1
  magnitude. These are the framework-heavy or protocol-implementation
  repositories.
- **Signal present, age partially confounds** (click, httpx): H2 is
  positive and large; H3 shrinks by 30 %–60 %. These have proportionally
  more stable utility helpers whose age scales with dup accumulation.
- **Weak but consistent** (black, pytest): H1 modest, H3 similar; small
  size effects but same direction.

Across all ten repositories the direction of the H1 coefficient is
negative; not a single repository shows the industry-implied positive
sign. This consistency, more than the aggregate magnitude, is the
paper's central empirical claim.

## 4.7 Robustness (Appendix summary — full tables in App. C)

- **Fisher-z weighted per-repo mean.** ρ̄_dup = **−0.413**, 95 % CI
  [−0.424, −0.401]. Per-repo z transformed, weighted by n − 3,
  aggregated, back-transformed. All ten repos contribute negative z;
  the aggregate is not driven by one repo.
- **Raw-count (no log).** ρ_dup = −0.429. Spearman is rank-invariant,
  so log transformation is only a display choice.
- **Alternate churn windows (7d, 30d).** Not run — pipeline supports it
  (one column addition in `harness.py`) but re-running takes ~4 h.
  Scheduled as follow-up. See App. C4.
- **Test-file subgroup.** N = 10,997. ρ ≈ 0 because `dup.block v5` and
  `risk.error-masking v2` downgrade tests/ findings to info, leaving
  almost no warn variance in that subset. Confirms the downgrade rule
  is working as intended; not a claim about test-file dynamics.

## 4.8 Zero-churn population drives the aggregate direction

A subgroup analysis reveals additional nuance that the aggregate ρ
alone conceals. Restricting to rows where 14-day churn was positive
(N = 13,620 of 20,859 src-file rows, 65 %), the correlation **reverses
sign**:

| Subset | N | ρ (warns_dup, churn_14d) | 95 % CI |
|---|---:|---:|---|
| All src rows (H1) | 20,859 | −0.439 | [−0.452, −0.426] |
| Restricted to churn > 0 | 13,620 | **+0.163** | [+0.147, +0.180] |

The negative aggregate is therefore driven by the *zero-churn mass*:
high-warns files are disproportionately likely to have **zero** churn
in the following 14 days. Conditional on being touched at all, higher
warns is associated with slightly *more* churn — the direction the
industry framing predicts.

We do not treat this as a contradiction of §4.2 but as a refinement
of it: the primary signal in the data is a hurdle effect at the
first-touch boundary. Once a file is being modified, warnings weakly
predict the *volume* of modification; but warnings much more strongly
predict whether the file will be modified at all. §5 discusses the
implication for the "stability signal" interpretation.
