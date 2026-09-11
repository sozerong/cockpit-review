"""라벨링 헬퍼: 층화 표본 추출 + 채점.

사용법:
    python bench/label.py sample <analyzer_id> [--n N] [--seed S]
    python bench/label.py score  <analyzer_id> <labeled_csv>

`sample`은 게이트 클론(bench/clones/*)에 최신 cockpit을 돌려 finding을 모으고,
repo별 층화 표본을 생성한다. 각 행에 파일 컨텍스트 ±3줄을 붙여 사람이 CSV만 보고
판단 가능하게 한다.

`score`는 label 컬럼이 채워진 CSV를 읽고 지표를 계산해 markdown으로 저장한다.

ponytail: 순수 stdlib + 이미 있는 cockpit CLI. 라벨 UI 안 만듦. CSV가 UI.
"""
from __future__ import annotations
import argparse
import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from random import Random

BENCH = Path(__file__).parent
CLONES = BENCH / "clones"
LABELS = BENCH / "labels"
CONTEXT_LINES = 3
VALID_LABELS = {"tp", "fp", "boilerplate", "style", "unclear"}


def _list_repos() -> list[Path]:
    if not CLONES.exists():
        return []
    return sorted(p for p in CLONES.iterdir() if p.is_dir())


def _run_cockpit(repo: Path) -> list[dict]:
    r = subprocess.run(
        [sys.executable, "-m", "cockpit.cli", "check", str(repo), "--json"],
        capture_output=True, timeout=900,
    )
    if r.returncode != 0:
        return []
    return json.loads(r.stdout).get("findings", [])


def _context(repo: Path, rel: str, line: int) -> str:
    """±CONTEXT_LINES around `line` (1-indexed). Returns a single string."""
    p = repo / rel
    try:
        text = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    a = max(0, line - 1 - CONTEXT_LINES)
    b = min(len(text), line - 1 + CONTEXT_LINES + 1)
    snippet = text[a:b]
    # Collapse newlines for CSV safety
    return " ⏎ ".join(snippet)


def cmd_sample(analyzer_id: str, n: int, seed: int) -> int:
    rng = Random(seed)
    per_repo: dict[str, list[dict]] = {}
    for repo in _list_repos():
        findings = [
            {**f, "_repo": repo.name, "_repo_path": str(repo)}
            for f in _run_cockpit(repo)
            if f["analyzer_id"] == analyzer_id and f["severity"] == "warn"
        ]
        if findings:
            per_repo[repo.name] = findings
            print(f"  {repo.name}: {len(findings)} candidates", file=sys.stderr)

    total = sum(len(v) for v in per_repo.values())
    if total == 0:
        print("no findings to sample", file=sys.stderr)
        return 1

    # Proportional allocation with a minimum of min(3, available) per repo,
    # so no repo is invisible. Then rebalance the remainder proportionally.
    quotas: dict[str, int] = {}
    for name, hits in per_repo.items():
        quotas[name] = min(3, len(hits))
    used = sum(quotas.values())
    remaining = n - used
    if remaining > 0:
        weights = {name: max(0, len(hits) - quotas[name]) for name, hits in per_repo.items()}
        total_w = sum(weights.values()) or 1
        for name in list(quotas):
            extra = round(remaining * weights[name] / total_w)
            take = min(extra, len(per_repo[name]) - quotas[name])
            quotas[name] += max(0, take)

    LABELS.joinpath("samples").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = LABELS / "samples" / f"{analyzer_id.replace('.', '_')}_{stamp}.csv"

    rows = []
    for name, hits in per_repo.items():
        picked = rng.sample(hits, min(quotas[name], len(hits)))
        for f in picked:
            repo_path = Path(f["_repo_path"])
            rows.append({
                "repo": name,
                "analyzer_id": f["analyzer_id"],
                "analyzer_version": f["analyzer_version"],
                "severity": f["severity"],
                "file": f["file"],
                "line": f["span"][0],
                "message": f["message"],
                "evidence_kind": f["evidence"].get("kind", ""),
                "matches_count": len(f["evidence"].get("matches", [])) + 1
                                 if f["analyzer_id"] == "dup.block" else "",
                "context": _context(repo_path, f["file"], f["span"][0]),
                "label": "",
                "note": "",
            })

    rows.sort(key=lambda r: (r["repo"], r["file"], r["line"]))
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n=> {out}  ({len(rows)} rows)", file=sys.stderr)
    print(f"   allocation: {dict(sorted((n, quotas[n]) for n in per_repo))}",
          file=sys.stderr)
    return 0


def cmd_score(analyzer_id: str, labeled_csv: Path) -> int:
    with labeled_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("empty CSV", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    unlabeled = 0
    per_repo: dict[str, Counter[str]] = defaultdict(Counter)
    per_kind: dict[str, Counter[str]] = defaultdict(Counter)

    for r in rows:
        lbl = (r.get("label") or "").strip().lower()
        if not lbl:
            unlabeled += 1
            continue
        if lbl not in VALID_LABELS:
            print(f"warn: unknown label {lbl!r} at {r['repo']}:{r['file']}:{r['line']}",
                  file=sys.stderr)
            continue
        counts[lbl] += 1
        per_repo[r["repo"]][lbl] += 1
        per_kind[r.get("evidence_kind") or "-"][lbl] += 1

    labeled = sum(counts.values())
    if labeled == 0:
        print("no rows have labels yet", file=sys.stderr)
        return 1

    tp = counts["tp"]
    fp = counts["fp"] + counts["style"]  # style counts as "not actionable enough"
    bp = counts["boilerplate"]
    total_judgeable = labeled - counts["unclear"] - bp
    precision = (tp / total_judgeable) if total_judgeable else 0
    actionable = tp / labeled

    gate = ("PASS — Week 4 진행" if actionable >= 0.40
            else "THRESHOLD REDESIGN — Week 4를 튜닝에 소진"
            if actionable >= 0.20
            else "REDESIGN — 분석기 뜯어고침")

    LABELS.joinpath("scores").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    out = LABELS / "scores" / f"{analyzer_id.replace('.', '_')}_{stamp}.md"

    md = [
        f"# {analyzer_id} — labeled score",
        f"",
        f"입력: `{labeled_csv.name}`",
        f"라벨 완료: {labeled}/{len(rows)} ({unlabeled} 미완)",
        f"",
        f"## 총계",
        f"",
        f"| 라벨 | 개수 | 비율 |",
        f"|---|---:|---:|",
    ]
    for lbl in ("tp", "fp", "boilerplate", "style", "unclear"):
        c = counts[lbl]
        pct = 100 * c / labeled if labeled else 0
        md.append(f"| {lbl} | {c} | {pct:.1f}% |")
    md += [
        f"",
        f"## 지표",
        f"",
        f"- 정밀도 (tp / (tp+fp+style)): **{precision:.1%}**",
        f"- actionable 비율 (tp / labeled): **{actionable:.1%}**",
        f"- boilerplate 비중: {bp/labeled:.1%}",
        f"",
        f"## 게이트 판정",
        f"",
        f"**{gate}**",
        f"",
        f"## repo별",
        f"",
        f"| repo | tp | fp | boilerplate | style | unclear |",
        f"|---|---:|---:|---:|---:|---:|",
    ]
    for repo in sorted(per_repo):
        c = per_repo[repo]
        md.append(f"| {repo} | {c['tp']} | {c['fp']} | "
                  f"{c['boilerplate']} | {c['style']} | {c['unclear']} |")
    if any(k != "-" for k in per_kind):
        md += [f"", f"## evidence.kind별", f"",
               f"| kind | tp | fp | boilerplate | style | unclear |",
               f"|---|---:|---:|---:|---:|---:|"]
        for kind in sorted(per_kind):
            c = per_kind[kind]
            md.append(f"| {kind} | {c['tp']} | {c['fp']} | "
                      f"{c['boilerplate']} | {c['style']} | {c['unclear']} |")

    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"=> {out}", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="label")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample", help="Stratified sample from bench/clones")
    s.add_argument("analyzer_id")
    s.add_argument("--n", type=int, default=100)
    s.add_argument("--seed", type=int, default=42)
    sc = sub.add_parser("score", help="Compute metrics from labeled CSV")
    sc.add_argument("analyzer_id")
    sc.add_argument("labeled_csv", type=Path)
    args = p.parse_args()
    if args.cmd == "sample":
        return cmd_sample(args.analyzer_id, args.n, args.seed)
    if args.cmd == "score":
        return cmd_score(args.analyzer_id, args.labeled_csv)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
