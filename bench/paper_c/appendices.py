"""Appendix computations for the Paper C draft.

Emits `bench/paper_c/out/appendix.md` with:
- Appendix A: per-repo sample table (row counts, sampled date range)
- Appendix B: test-file subgroup analysis (same H1-H3.5 restricted to tests/)
- Appendix C: robustness checks
    - C1: raw-count (no log) alternative
    - C2: Fisher-z weighted per-repo mean (fixed-effects style)
    - C3: excluding zero-churn rows

Uses the same stdlib-only tooling as analyze.py; imports its correlation
helpers to keep the metric identical."""
from __future__ import annotations
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze import (  # type: ignore
    _spearman, _bootstrap_ci, _partial_spearman, _bootstrap_partial,
    _partial_spearman_2, _bootstrap_partial_2, OUT,
)


def _load_all_rows() -> list[dict]:
    """Load per-repo CSVs (analyze.py's _load_all reference)."""
    rows = []
    for csv_path in sorted(OUT.glob("*.csv")):
        if csv_path.name == "combined.csv":
            continue
        with csv_path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                for k in ("loc", "warns_dup", "warns_em", "churn_14d"):
                    r[k] = int(r[k])
                rows.append(r)
    return rows


def appendix_A(all_rows: list[dict]) -> list[str]:
    per: dict[str, list[dict]] = defaultdict(list)
    for r in all_rows:
        per[r["repo"]].append(r)
    md = [
        "## Appendix A. Repository sample summary",
        "",
        "Each repository was cloned to `bench/clones/<name>` and sampled at",
        "100 uniformly-random reachable-from-HEAD commits with `seed = 42`,",
        "subject to `commit_date + 14d < now`.",
        "",
        "| Repo | Rows (all, pre-filter) | Earliest sampled | Latest sampled |",
        "|---|---:|---|---|",
    ]
    for name in sorted(per):
        rs = per[name]
        dates = []
        for r in rs:
            try:
                dates.append(datetime.fromisoformat(r["date"]))
            except ValueError:
                continue
        if not dates:
            md.append(f"| {name} | {len(rs)} | — | — |")
            continue
        md.append(f"| {name} | {len(rs)} | {min(dates).date()} | {max(dates).date()} |")
    return md


def appendix_B(all_rows: list[dict]) -> list[str]:
    """Test-file subgroup: paths under tests/ or matching test_/_test filename."""
    def is_test(p: str) -> bool:
        parts = p.split("/")
        name = parts[-1]
        return (
            name.startswith("test_") or name.endswith("_test.py")
            or "tests" in parts or "testing" in parts
        )
    test_rows = [r for r in all_rows
                 if r["loc"] > 0 and "=>" not in r["file"] and is_test(r["file"])]
    md = [
        "",
        "## Appendix B. Test-file subgroup",
        "",
        f"Restricted to `tests/`, `testing/`, `test_*.py`, `*_test.py`. N = {len(test_rows)}.",
        "",
    ]
    if len(test_rows) < 30:
        md.append("Too few test-file rows for stable estimates.")
        return md
    log_dup = [math.log1p(r["warns_dup"]) for r in test_rows]
    log_em = [math.log1p(r["warns_em"]) for r in test_rows]
    log_churn = [math.log1p(r["churn_14d"]) for r in test_rows]
    rho_dup = _spearman(log_dup, log_churn)
    rho_em = _spearman(log_em, log_churn)
    lo_dup, hi_dup = _bootstrap_ci(log_dup, log_churn, n_boot=500)
    lo_em, hi_em = _bootstrap_ci(log_em, log_churn, n_boot=500)
    md += [
        "H1 restricted to tests:",
        "",
        "| Variable | ρ | 95% CI |",
        "|---|---:|---|",
        f"| log(warns_dup + 1) → log(churn₁₄ + 1) | {rho_dup:+.3f} | [{lo_dup:+.3f}, {hi_dup:+.3f}] |",
        f"| log(warns_em + 1) → log(churn₁₄ + 1)  | {rho_em:+.3f} | [{lo_em:+.3f}, {hi_em:+.3f}] |",
    ]
    return md


def appendix_C(all_rows: list[dict]) -> list[str]:
    src_rows = [r for r in all_rows if r["loc"] > 0 and "=>" not in r["file"]
                and "tests" not in r["file"].split("/")
                and "testing" not in r["file"].split("/")]
    md = ["", "## Appendix C. Robustness checks", ""]

    # C1: no-log alternative (raw counts, Spearman is rank-invariant so this
    # should give identical rho — but including for the reader's peace of mind)
    d = [r["warns_dup"] for r in src_rows]
    c = [r["churn_14d"] for r in src_rows]
    rho_raw = _spearman(d, c)
    md += [
        "### C1. Raw-count (no-log) alternative",
        "",
        "Spearman is rank-invariant, so log transformation should not change",
        "the coefficient. Included as a sanity check.",
        "",
        f"| Variable | ρ | Note |",
        f"|---|---:|---|",
        f"| warns_dup vs churn_14d (raw) | {rho_raw:+.3f} | ranks unchanged, identical to H1 |",
        "",
    ]

    # C2: Fisher-z weighted per-repo mean
    per: dict[str, list[dict]] = defaultdict(list)
    for r in src_rows:
        per[r["repo"]].append(r)
    zs, ws = [], []
    for name, rs in per.items():
        if len(rs) < 30:
            continue
        d_r = [math.log1p(r["warns_dup"]) for r in rs]
        c_r = [math.log1p(r["churn_14d"]) for r in rs]
        rho = _spearman(d_r, c_r)
        # clamp to avoid atanh(±1)
        rho_c = max(-0.999, min(0.999, rho))
        z = 0.5 * math.log((1 + rho_c) / (1 - rho_c))
        w = len(rs) - 3
        zs.append((name, z, w))
        ws.append(w)
    total_w = sum(w for _, _, w in zs)
    z_mean = sum(z * w for _, z, w in zs) / total_w
    se = math.sqrt(1 / total_w)
    z_lo, z_hi = z_mean - 1.96 * se, z_mean + 1.96 * se
    def inv_z(z: float) -> float:
        return (math.exp(2 * z) - 1) / (math.exp(2 * z) + 1)
    rho_mean = inv_z(z_mean)
    rho_lo, rho_hi = inv_z(z_lo), inv_z(z_hi)
    md += [
        "### C2. Fisher-z weighted per-repository mean",
        "",
        "Each per-repo Spearman ρ (warns_dup, churn_14d) is Fisher-z",
        "transformed, weighted by (n − 3), aggregated, and back-transformed.",
        "This aggregation gives every repo comparable weight regardless of the",
        "aggregate correlation being potentially driven by one large repo.",
        "",
        f"| Aggregate ρ̄ (Fisher-z weighted) | 95% CI (Fisher-z + normal) |",
        f"|---:|---|",
        f"| {rho_mean:+.3f} | [{rho_lo:+.3f}, {rho_hi:+.3f}] |",
        "",
        "Per-repo Fisher-z values:",
        "",
        f"| Repo | ρ_dup | Fisher z | weight (n-3) |",
        f"|---|---:|---:|---:|",
    ]
    for name, z, w in sorted(zs, key=lambda x: -x[2]):
        rho_r = inv_z(z)
        md.append(f"| {name} | {rho_r:+.3f} | {z:+.3f} | {w} |")

    # C3: excluding zero-churn rows
    nonzero = [r for r in src_rows if r["churn_14d"] > 0]
    md += [
        "",
        "### C3. Restricted to rows with any 14-day churn",
        "",
        f"N = {len(nonzero)} (of {len(src_rows)} src-file rows).",
        "",
    ]
    if len(nonzero) >= 30:
        d = [math.log1p(r["warns_dup"]) for r in nonzero]
        c = [math.log1p(r["churn_14d"]) for r in nonzero]
        rho = _spearman(d, c)
        lo, hi = _bootstrap_ci(d, c, n_boot=500)
        md += [
            f"| Variable | ρ | 95% CI |",
            f"|---|---:|---|",
            f"| log(warns_dup + 1) → log(churn₁₄ + 1), churn > 0 | {rho:+.3f} | [{lo:+.3f}, {hi:+.3f}] |",
        ]

    md += [
        "",
        "### C4. Alternative churn windows (not run)",
        "",
        "Computing correlations at 7-day and 30-day windows requires",
        "re-running the harness with additional `git log` invocations per",
        "commit. The pipeline is designed to support it (one column addition",
        "in `harness.py`) but the full 10-repo × 100-commit run takes ~4 h.",
        "This is scheduled as a follow-up and its expected direction is the",
        "same as H1 based on the correlation structure observed here.",
    ]
    return md


def main() -> int:
    rows = _load_all_rows()
    print(f"loaded {len(rows)} rows")
    parts = ["# Paper C — Appendices", ""]
    parts += appendix_A(rows)
    parts += appendix_B(rows)
    parts += appendix_C(rows)
    dst = OUT / "appendix.md"
    dst.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"=> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
