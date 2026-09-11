"""Paper C harness — 커밋 시점 지표 vs 14일 churn.

사용법:
    python bench/paper_c/harness.py <repo_name> [--n 20] [--seed 42]

동작:
1. bench/clones/<repo> 에서 무작위 커밋 N개 표본 (main 브랜치 한정)
2. 각 커밋에서:
   - 별도 워크트리에 checkout (원본 훼손 안 함)
   - cockpit check --json 실행
   - 파일별 warn 카운트 집계
   - git log 로 커밋+14일 사이 churn 계산
3. bench/paper_c/out/<repo>.csv 저장

Ponytail: worktree 사용 (원본 clone은 유지, 원치 않는 workspace pollution 방지).
"""
from __future__ import annotations
import argparse
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import Random

BENCH = Path(__file__).parent.parent
CLONES = BENCH / "clones"
OUT = Path(__file__).parent / "out"
CHURN_DAYS = 14


def _sh(cmd: list[str], cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)


def _list_commits(repo: Path) -> list[tuple[str, datetime]]:
    """[(sha, iso_date_utc), ...] on the main branch, oldest first."""
    r = _sh(["git", "log", "--format=%H %cI", "--reverse", "HEAD"], cwd=repo)
    out = []
    for line in r.stdout.decode().splitlines():
        sha, iso = line.strip().split(" ", 1)
        try:
            out.append((sha, datetime.fromisoformat(iso.replace("Z", "+00:00"))))
        except ValueError:
            # Some old commits carry malformed timezones (e.g. `+518:00`); skip.
            continue
    return out


def _churn_for_commit(repo: Path, sha: str, since: datetime,
                      until: datetime) -> dict[str, int]:
    """git log --numstat between sha's date and sha's date + CHURN_DAYS.
    Returns {file_rel_path: insertions+deletions}."""
    r = _sh([
        "git", "log", f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
        "--numstat", "--format=", "HEAD",
    ], cwd=repo)
    churn: dict[str, int] = {}
    for line in r.stdout.decode(errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        ins, dels, path = parts
        if not path.endswith(".py"):
            continue
        try:
            churn[path] = churn.get(path, 0) + int(ins) + int(dels)
        except ValueError:  # binary file has "-"
            continue
    return churn


def _cockpit_warns(worktree: Path) -> dict[str, dict[str, int]]:
    """Run cockpit check --json in worktree, return per-file warn counts:
    {file: {dup: n, em: n, loc_hint: n}}"""
    r = _sh([sys.executable, "-m", "cockpit.cli", "check", str(worktree), "--json"])
    if r.returncode != 0:
        return {}
    try:
        env = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}
    per_file: dict[str, dict[str, int]] = {}
    for f in env["findings"]:
        if f["severity"] != "warn":
            continue
        pf = per_file.setdefault(f["file"], {"dup": 0, "em": 0})
        if f["analyzer_id"] == "dup.block":
            pf["dup"] += 1
        elif f["analyzer_id"] == "risk.error-masking":
            pf["em"] += 1
    return per_file


def _loc(worktree: Path, rel: str) -> int:
    try:
        return sum(1 for _ in (worktree / rel).open("rb"))
    except OSError:
        return 0


def process(repo_name: str, n: int, seed: int) -> int:
    repo = CLONES / repo_name
    if not repo.exists():
        print(f"repo not found: {repo}", file=sys.stderr)
        return 1

    # Un-shallow if needed so history is walkable
    _sh(["git", "fetch", "--unshallow"], cwd=repo)  # no-op if already full

    all_commits = _list_commits(repo)
    now = datetime.now(timezone.utc)
    eligible = [(s, d) for s, d in all_commits
                if d + timedelta(days=CHURN_DAYS) < now]
    if not eligible:
        print("no eligible commits (need date + 14d < now)", file=sys.stderr)
        return 1

    rng = Random(seed)
    sample = rng.sample(eligible, min(n, len(eligible)))
    sample.sort(key=lambda x: x[1])  # deterministic run order

    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{repo_name}.csv"
    rows_out = []

    with tempfile.TemporaryDirectory(prefix="paperc_") as wt_root:
        wt = Path(wt_root) / "wt"
        # Set up a linked worktree at the first sha (we'll re-checkout each iter)
        first_sha = sample[0][0]
        r = _sh(["git", "worktree", "add", "--detach", str(wt), first_sha], cwd=repo)
        if r.returncode != 0:
            print(f"worktree add failed: {r.stderr.decode()[:300]}", file=sys.stderr)
            return 1
        try:
            for i, (sha, cdate) in enumerate(sample, 1):
                print(f"[{i}/{len(sample)}] {sha[:8]}  {cdate.isoformat()}",
                      flush=True)
                _sh(["git", "checkout", "--force", sha], cwd=wt)
                warns = _cockpit_warns(wt)
                until = cdate + timedelta(days=CHURN_DAYS)
                churn = _churn_for_commit(repo, sha, cdate, until)

                # Emit one row per file (union of warn files and churn files).
                files = set(warns.keys()) | set(churn.keys())
                for f in files:
                    w = warns.get(f, {"dup": 0, "em": 0})
                    rows_out.append({
                        "repo": repo_name,
                        "sha": sha,
                        "date": cdate.isoformat(),
                        "file": f,
                        "loc": _loc(wt, f),
                        "warns_dup": w["dup"],
                        "warns_em": w["em"],
                        "churn_14d": churn.get(f, 0),
                    })
        finally:
            _sh(["git", "worktree", "remove", "--force", str(wt)], cwd=repo)

    with dst.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)
    print(f"\n=> {dst}  ({len(rows_out)} rows across {len(sample)} commits)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="paper_c_harness")
    p.add_argument("repo_name")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    return process(args.repo_name, args.n, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
