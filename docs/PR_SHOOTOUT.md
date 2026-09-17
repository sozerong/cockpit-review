# PR shootout — cockpit vs CodeRabbit

Prove the moat before v0.3.0 scope is locked. If cockpit's deterministic
analyzers don't beat (or meaningfully differ from) an LLM PR reviewer on real
Python PRs, we pivot v0.3.0 from breadth to depth.

## Goal

Prove cockpit finds >=7 real bugs across 20 real PRs that CodeRabbit misses
(or vice versa) — where "real bug" means a block/warn severity finding a
maintainer would act on. Decision gate for v0.3.0 scope.

## Sample selection

20 PRs from mid-sized OSS Python repos. Candidate repos:

- fastapi/fastapi
- encode/httpx
- pydantic/pydantic
- sqlalchemy/sqlalchemy
- django/django

PR filters:

- merged (not just opened) — signals real, non-trivial change
- touches >=3 files — enough surface for cross-file analyzers to fire
- merged in the last 6 months — current style, current dependencies
- exclude pure-docs, pure-deps, pure-typing PRs
- 4 PRs per repo, balanced across bug-fix / refactor / feature

## Protocol

For each PR:

1. Check out PR base commit. Run `cockpit check --format json` → `base.json`.
2. Check out PR head commit. Run `cockpit check --format json` → `head.json`.
3. Diff → `cockpit_findings.json` (new + changed only).
4. Post PR to CodeRabbit free tier (fork + PR-into-fork if needed). Wait
   for full pass. Export findings → `coderabbit_findings.json`.
5. Manually triage every unique finding from both sides:
   - **TP** — real bug or real smell a maintainer would fix
   - **FP** — wrong, or triggered on unrelated code
   - **style-only** — technically correct but cosmetic; excluded from score
6. Record wall time for each tool (cockpit: measured; CodeRabbit: from
   comment timestamps).

Triage is done blind where possible — score cockpit's findings without
knowing CodeRabbit's, and vice versa, then reconcile overlaps.

## Scorecard

One row per PR. Columns:

| PR URL | cockpit-unique TP | CR-unique TP | both TP | cockpit FP | CR FP | cockpit wall | CR wall | notes |

Aggregate row at bottom: totals + precision (TP / (TP + FP)) per tool.

## Decision rule

- **>=7 cockpit-unique actionable TPs across 20 PRs** (>=1 per 3 PRs,
  block/warn severity, not info): current analyzer breadth is
  differentiated. v0.3.0 = add TypeScript + more analyzers per M0.5 plan.
- **<7**: breadth is not the moat. Pivot v0.3.0 to depth — kill the
  weakest 3-4 analyzers, double down on the top 2 (likely `dup.block` +
  `risk.error-masking`), and ship an evidence quality upgrade
  (dataflow-aware, cross-file taint, etc).
- **CodeRabbit dominates on unique TPs by 2×+**: hard rethink — either
  deterministic-only is the wrong bet for PR review, or the analyzer set
  is far behind. Escalate to full strategy review before continuing.

## Timeline

- **Day 1**: pick the 20 PRs, freeze the list in `bench/shootout/prs.txt`.
- **Day 2-3**: run cockpit on all 40 base/head pairs. Automate.
- **Day 3-5**: run CodeRabbit on all 20. Manual, rate-limited.
- **Day 6**: triage. Two passes (blind, then reconciled).
- **Day 7**: write up scorecard + decision. Land before v0.3.0 planning.

## Out of scope

- **Perf comparison** — already established: 27× incremental on fastapi.
  Not the question here.
- **UI comparison** — cockpit's live dashboard is a separate axis of
  moat; CodeRabbit is a PR-comment product. Apples/oranges.
- **Paid CodeRabbit features** — we compare what an OSS maintainer would
  see on the free tier.

## Open questions

1. How do we handle CodeRabbit's paid-tier features (custom rules,
   learnings from past PRs) that we don't have access to — footnote and
   move on, or attempt a trial?
2. Who does the triage? Solo-founder triage is fast but biased toward
   cockpit; is it worth paying one external Python reviewer for a
   second-pass on unique findings?
3. What counts as "actionable" for the decision rule — do we require the
   original PR author to confirm, or is a maintainer-plausible bug
   enough? (Author-confirmation is stronger but adds weeks.)
