"""Paper C 분석 — 커밋 시점 warns가 14일 churn을 예측하는가.

사용법:
    python bench/paper_c/analyze.py

동작:
1. bench/paper_c/out/*.csv 병합 → combined.csv
2. 각 (repo, file) 조합의 first-commit-date 조회 → age_days 공변량 계산 (cached)
3. Spearman rank correlation:
   - dup ~ churn, em ~ churn (원 가설)
   - dup ~ age, em ~ age (재해석 가설: warns가 age의 프록시)
4. 결과 report.md 저장

Ponytail: stdlib만 사용. git log 를 shell out으로 부름.
"""
from __future__ import annotations
import csv
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

OUT = Path(__file__).parent / "out"
CLONES = Path(__file__).parent.parent / "clones"
_AGE_CACHE = Path(__file__).parent / "out" / ".age_cache.json"


def _first_commit_date(repo: str, file: str) -> str | None:
    """Cached lookup of the earliest commit date for a file in the repo.
    Returns ISO date string, or None if unavailable."""
    cache = _load_age_cache()
    key = f"{repo}::{file}"
    if key in cache:
        return cache[key]
    repo_path = CLONES / repo
    if not repo_path.exists():
        cache[key] = None
        return None
    r = subprocess.run(
        ["git", "log", "--diff-filter=A", "--follow", "--format=%cI", "-1", "--", file],
        cwd=repo_path, capture_output=True, timeout=30,
    )
    val = r.stdout.decode().strip() or None
    cache[key] = val
    return val


def _load_age_cache() -> dict:
    global _cache_data
    try:
        return _cache_data
    except NameError:
        pass
    if _AGE_CACHE.exists():
        _cache_data = json.loads(_AGE_CACHE.read_text(encoding="utf-8"))
    else:
        _cache_data = {}
    return _cache_data


def _save_age_cache() -> None:
    data = _load_age_cache()
    _AGE_CACHE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def _age_days(commit_iso: str, first_iso: str | None) -> int | None:
    if not first_iso:
        return None
    try:
        c = datetime.fromisoformat(commit_iso)
        f = datetime.fromisoformat(first_iso)
    except ValueError:
        return None
    return max(0, (c - f).days)


def _load_all() -> list[dict]:
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


def _filter_rows(rows: list[dict]) -> list[dict]:
    """Skip rows that can't participate (deleted files, renames, empty)."""
    out = []
    for r in rows:
        if r["loc"] <= 0:
            continue  # file didn't exist at that commit (deleted / rename)
        if "=>" in r["file"]:
            continue  # git rename notation
        if r["file"].startswith("tests/") or "/tests/" in r["file"]:
            continue  # analysis focuses on src; test file churn is different
        out.append(r)
    return out


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation, average ranks for ties. Pure stdlib."""
    def ranks(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((r - mx) ** 2 for r in rx))
    dy = math.sqrt(sum((r - my) ** 2 for r in ry))
    return num / (dx * dy) if dx and dy else 0.0


def _partial_spearman(xs: list[float], ys: list[float],
                      zs: list[float]) -> float:
    """Spearman partial correlation of X and Y controlling for Z.
    r(XY|Z) = (r_XY - r_XZ * r_YZ) / sqrt((1 - r_XZ^2) * (1 - r_YZ^2))
    Computed on ranks (Spearman = Pearson on ranks)."""
    r_xy = _spearman(xs, ys)
    r_xz = _spearman(xs, zs)
    r_yz = _spearman(ys, zs)
    denom = math.sqrt(max(1e-12, (1 - r_xz**2) * (1 - r_yz**2)))
    return (r_xy - r_xz * r_yz) / denom


def _partial_spearman_2(xs: list[float], ys: list[float],
                        z1: list[float], z2: list[float]) -> float:
    """Spearman partial ρ(X, Y | Z1, Z2). Recursive formula:
    r(X,Y|Z1,Z2) = (r(X,Y|Z1) - r(X,Z2|Z1)·r(Y,Z2|Z1)) /
                   sqrt((1-r(X,Z2|Z1)²)(1-r(Y,Z2|Z1)²))"""
    r_xy_z1 = _partial_spearman(xs, ys, z1)
    r_xz2_z1 = _partial_spearman(xs, z2, z1)
    r_yz2_z1 = _partial_spearman(ys, z2, z1)
    denom = math.sqrt(max(1e-12, (1 - r_xz2_z1**2) * (1 - r_yz2_z1**2)))
    return (r_xy_z1 - r_xz2_z1 * r_yz2_z1) / denom


def _bootstrap_partial_2(xs: list[float], ys: list[float],
                         z1: list[float], z2: list[float],
                         n_boot: int = 500, seed: int = 42) -> tuple[float, float]:
    from random import Random
    rng = Random(seed)
    n = len(xs)
    vals = []
    for _ in range(n_boot):
        idx = [rng.randint(0, n - 1) for _ in range(n)]
        vals.append(_partial_spearman_2(
            [xs[i] for i in idx], [ys[i] for i in idx],
            [z1[i] for i in idx], [z2[i] for i in idx],
        ))
    vals.sort()
    return vals[int(n_boot * 0.025)], vals[int(n_boot * 0.975)]


def _bootstrap_partial(xs: list[float], ys: list[float], zs: list[float],
                       n_boot: int = 500, seed: int = 42) -> tuple[float, float]:
    """95% percentile CI for the partial-Spearman via bootstrap."""
    from random import Random
    rng = Random(seed)
    n = len(xs)
    vals = []
    for _ in range(n_boot):
        idx = [rng.randint(0, n - 1) for _ in range(n)]
        vals.append(_partial_spearman(
            [xs[i] for i in idx],
            [ys[i] for i in idx],
            [zs[i] for i in idx],
        ))
    vals.sort()
    return vals[int(n_boot * 0.025)], vals[int(n_boot * 0.975)]


def _bootstrap_ci(xs: list[float], ys: list[float], n_boot: int = 1000,
                  seed: int = 42) -> tuple[float, float]:
    """95% percentile CI of Spearman rho via bootstrap resample."""
    from random import Random
    rng = Random(seed)
    n = len(xs)
    rhos = []
    for _ in range(n_boot):
        idx = [rng.randint(0, n - 1) for _ in range(n)]
        rhos.append(_spearman([xs[i] for i in idx], [ys[i] for i in idx]))
    rhos.sort()
    lo = rhos[int(n_boot * 0.025)]
    hi = rhos[int(n_boot * 0.975)]
    return lo, hi


def analyze() -> int:
    rows = _load_all()
    print(f"loaded {len(rows)} rows from {OUT}")
    kept = _filter_rows(rows)
    print(f"after filter: {len(kept)} rows")
    if len(kept) < 30:
        print("too few rows for meaningful analysis", file=sys.stderr)
        return 1

    # Enrich with file age (days since first commit of that file in the repo).
    # Cached across analyze.py runs — first run is slow, later runs instant.
    print("enriching with file age (cached)…")
    for i, r in enumerate(kept):
        if i and i % 500 == 0:
            print(f"  {i}/{len(kept)}", flush=True)
            _save_age_cache()
        first = _first_commit_date(r["repo"], r["file"])
        r["age_days"] = _age_days(r["date"], first)
    _save_age_cache()

    # Save combined
    combined = OUT / "combined.csv"
    with combined.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(kept[0].keys()))
        w.writeheader()
        w.writerows(kept)

    # Log-transform (stability + interpretability)
    log_dup = [math.log1p(r["warns_dup"]) for r in kept]
    log_em = [math.log1p(r["warns_em"]) for r in kept]
    log_loc = [math.log1p(r["loc"]) for r in kept]
    log_churn = [math.log1p(r["churn_14d"]) for r in kept]

    rho_dup = _spearman(log_dup, log_churn)
    rho_em = _spearman(log_em, log_churn)
    rho_loc = _spearman(log_loc, log_churn)
    lo_dup, hi_dup = _bootstrap_ci(log_dup, log_churn)
    lo_em, hi_em = _bootstrap_ci(log_em, log_churn)

    # Re-interpretation hypothesis: warns is an age/stability proxy.
    aged = [r for r in kept if r["age_days"] is not None]
    part_dup_lo = part_dup_hi = part_em_lo = part_em_hi = 0.0
    part_dup = part_em = 0.0
    if aged:
        log_dup_a = [math.log1p(r["warns_dup"]) for r in aged]
        log_em_a = [math.log1p(r["warns_em"]) for r in aged]
        log_loc_a = [math.log1p(r["loc"]) for r in aged]
        log_age = [math.log1p(r["age_days"]) for r in aged]
        log_churn_a = [math.log1p(r["churn_14d"]) for r in aged]
        rho_dup_age = _spearman(log_dup_a, log_age)
        rho_em_age = _spearman(log_em_a, log_age)
        rho_loc_a = _spearman(log_loc_a, log_age)
        lo_dup_age, hi_dup_age = _bootstrap_ci(log_dup_a, log_age)
        lo_em_age, hi_em_age = _bootstrap_ci(log_em_a, log_age)
        # Phase 3: partial correlation of warns→churn CONTROLLING for age.
        part_dup = _partial_spearman(log_dup_a, log_churn_a, log_age)
        part_em = _partial_spearman(log_em_a, log_churn_a, log_age)
        part_dup_lo, part_dup_hi = _bootstrap_partial(log_dup_a, log_churn_a, log_age)
        part_em_lo, part_em_hi = _bootstrap_partial(log_em_a, log_churn_a, log_age)
        # Phase 3.5: two-variable partial, controlling for both age AND loc.
        part2_dup = _partial_spearman_2(log_dup_a, log_churn_a, log_age, log_loc_a)
        part2_em = _partial_spearman_2(log_em_a, log_churn_a, log_age, log_loc_a)
        part2_dup_lo, part2_dup_hi = _bootstrap_partial_2(
            log_dup_a, log_churn_a, log_age, log_loc_a)
        part2_em_lo, part2_em_hi = _bootstrap_partial_2(
            log_em_a, log_churn_a, log_age, log_loc_a)
    else:
        rho_dup_age = rho_em_age = rho_loc_a = 0.0
        lo_dup_age = hi_dup_age = lo_em_age = hi_em_age = 0.0
        part2_dup = part2_em = 0.0
        part2_dup_lo = part2_dup_hi = part2_em_lo = part2_em_hi = 0.0

    # Per-repo breakdown
    per_repo: dict[str, list[dict]] = defaultdict(list)
    for r in kept:
        per_repo[r["repo"]].append(r)

    md = [
        "# Paper C — 회귀 결과",
        f"",
        f"입력 rows (필터 후): {len(kept)}   |   age 있는 rows: {len(aged)}",
        f"저장소: {sorted(per_repo)}",
        f"",
        f"## H1 (원 가설): warns → 이후 churn",
        f"",
        f"| 변수 | ρ vs log(churn_14d + 1) | 95% CI |",
        f"|---|---:|---|",
        f"| log(warns_dup + 1)  | {rho_dup:+.3f} | [{lo_dup:+.3f}, {hi_dup:+.3f}] |",
        f"| log(warns_em + 1)   | {rho_em:+.3f} | [{lo_em:+.3f}, {hi_em:+.3f}] |",
        f"| log(loc + 1) (기저) | {rho_loc:+.3f} | — |",
        f"",
        f"## H2 (재해석 가설): warns → 파일 age",
        f"",
        f"| 변수 | ρ vs log(age_days + 1) | 95% CI |",
        f"|---|---:|---|",
        f"| log(warns_dup + 1)  | {rho_dup_age:+.3f} | [{lo_dup_age:+.3f}, {hi_dup_age:+.3f}] |",
        f"| log(warns_em + 1)   | {rho_em_age:+.3f} | [{lo_em_age:+.3f}, {hi_em_age:+.3f}] |",
        f"| log(loc + 1) (기저) | {rho_loc_a:+.3f} | — |",
        f"",
        f"## H3 (partial): warns → churn, **age 통제 후**",
        f"",
        f"| 변수 | ρ vs log(churn_14d + 1) \\| age | 95% CI |",
        f"|---|---:|---|",
        f"| log(warns_dup + 1) | {part_dup:+.3f} | [{part_dup_lo:+.3f}, {part_dup_hi:+.3f}] |",
        f"| log(warns_em + 1)  | {part_em:+.3f} | [{part_em_lo:+.3f}, {part_em_hi:+.3f}] |",
        f"",
        f"## H3.5 (multivariate partial): warns → churn, **age + loc 동시 통제**",
        f"",
        f"| 변수 | ρ vs log(churn_14d + 1) \\| age, loc | 95% CI |",
        f"|---|---:|---|",
        f"| log(warns_dup + 1) | {part2_dup:+.3f} | [{part2_dup_lo:+.3f}, {part2_dup_hi:+.3f}] |",
        f"| log(warns_em + 1)  | {part2_em:+.3f} | [{part2_em_lo:+.3f}, {part2_em_hi:+.3f}] |",
        f"",
        f"해석 지침:",
        f"- H1이 음수, H2가 양수, H3가 0에 수렴 → warns는 순수한 age 프록시. 예측력 없음.",
        f"- H3가 여전히 음수·유의 → age를 통제해도 warns는 churn을 낮추는 것과 연관 (도구 재정당화 재고 필요)",
        f"- H3가 양수·유의 (H1과 반대) → age가 confounder, warns 자체는 예측력 있음 (Simpson's paradox)",
        f"",
        f"## 저장소별 (dup 만 표시, em은 저장소별 CI 폭이 커서 전체 표에서만 신뢰)",
        f"",
        f"| repo | rows | H1 ρ_dup→churn | H2 ρ_dup→age | H3 partial (\\| age) |",
        f"|---|---:|---:|---:|---:|",
    ]
    for repo, rs in sorted(per_repo.items()):
        if len(rs) < 30:
            md.append(f"| {repo} | {len(rs)} | — | — | — |  <!-- too few -->")
            continue
        rs_aged = [r for r in rs if r.get("age_days") is not None]
        d = [math.log1p(r["warns_dup"]) for r in rs]
        c = [math.log1p(r["churn_14d"]) for r in rs]
        h1 = _spearman(d, c)
        if len(rs_aged) >= 30:
            d_a = [math.log1p(r["warns_dup"]) for r in rs_aged]
            a_a = [math.log1p(r["age_days"]) for r in rs_aged]
            c_a = [math.log1p(r["churn_14d"]) for r in rs_aged]
            h2 = _spearman(d_a, a_a)
            h3 = _partial_spearman(d_a, c_a, a_a)
            md.append(f"| {repo} | {len(rs)} | {h1:+.3f} | {h2:+.3f} | {h3:+.3f} |")
        else:
            md.append(f"| {repo} | {len(rs)} | {h1:+.3f} | — | — |")

    md += [
        f"",
        f"## 판정",
        f"",
    ]
    def excludes_zero(lo: float, hi: float) -> bool:
        return (lo > 0 and hi > 0) or (lo < 0 and hi < 0)

    dup_sig = excludes_zero(lo_dup, hi_dup)
    em_sig = excludes_zero(lo_em, hi_em)
    if dup_sig or em_sig:
        signs = []
        if dup_sig:
            signs.append(f"dup ρ={rho_dup:+.3f}")
        if em_sig:
            signs.append(f"em ρ={rho_em:+.3f}")
        direction = ("**양의 상관** (지표 높음 → 미래 churn 높음, 가설대로)"
                     if (dup_sig and rho_dup > 0) or (em_sig and rho_em > 0)
                     else "**음의 상관** (지표 높음 → 미래 churn 낮음, 가설의 반대)")
        md.append(f"**신호 있음** — CI 하한/상한이 0을 배제. {', '.join(signs)}")
        md.append(f"")
        md.append(f"방향: {direction}")
        if any((s and r < 0) for s, r in [(dup_sig, rho_dup), (em_sig, rho_em)]):
            md.append(f"")
            md.append(f"음의 상관은 재해석 필요:")
            md.append(f"- 가설: 유지보수성 낮은 파일이 재작업 많음")
            md.append(f"- 관찰: 유지보수성 낮은(warns 많은) 파일이 재작업 적음")
            md.append(f"- 대안 설명: warns가 많은 파일은 **오래된 안정 유틸 코드** — 아무도 안 건드림")
            md.append(f"- 재작업이 많은 파일은 **활발한 개발 중 신규 코드** — 자연히 warns 적음")
            md.append(f"- Paper C 재정의 필요: 지표는 예측력이 아닌 다른 특성 반영")
    else:
        md.append("**신호 없음** — CI가 0을 포함. Paper C 중단 판단.")

    report = OUT / "report.md"
    report.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"=> {report}")
    print(f"=> {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(analyze())
