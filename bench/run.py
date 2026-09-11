"""Week 3 gate harness. PLAN §4.

For each repo in repos.txt:
  1. shallow clone
  2. `cockpit check --json`
  3. `ruff check --select BLE001,S110,E722,PIE790` (error-masking overlap set)
  4. per finding: does ruff fire at the same file:line ± TOLERANCE?

Output:
  bench/out/overlap.json   -- per-repo summary
  bench/out/unique.csv     -- cockpit findings NOT covered by ruff, ready for labeling
  bench/out/summary.md     -- overlap % + counts, README-ready

Ponytail: no pylint / no SonarQube CE yet. Ruff's error-masking rule set
already dominates pylint here, and Sonar needs a running server. Add when the
overlap number is inconclusive.
"""
from __future__ import annotations
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TOLERANCE = 3  # lines — same finding if within this range
CLONE_DEPTH = 1
BENCH = Path(__file__).parent
OUT = BENCH / "out"
CLONES = BENCH / "clones"

# ruff rules that flag the same class of thing as risk.error-masking
# BLE001 = blind except, S110 = try/except/pass, E722 = bare except, PIE790 = unnecessary pass
RUFF_RULES = "BLE001,S110,E722,PIE790"


@dataclass
class RepoResult:
    name: str
    files_scanned: int
    cockpit_findings: int
    ruff_findings: int
    overlap: int
    unique_to_cockpit: int
    error: str = ""


def _sh(cmd: list[str], cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout)


def _load_repos() -> list[tuple[str, str, str]]:
    """Return [(name, ref, url)]."""
    out = []
    for line in (BENCH / "repos.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        ref, url = parts[0], parts[1]
        name = url.rsplit("/", 1)[-1].removesuffix(".git")
        out.append((name, ref, url))
    return out


def _clone(name: str, ref: str, url: str) -> Path:
    dest = CLONES / name
    if dest.exists():
        return dest
    print(f"  cloning {name}…", flush=True)
    r = _sh(["git", "clone", "--depth", str(CLONE_DEPTH), "--branch", ref, url, str(dest)])
    if r.returncode != 0:
        # some repos use main vs master — retry without --branch
        shutil.rmtree(dest, ignore_errors=True)
        r = _sh(["git", "clone", "--depth", str(CLONE_DEPTH), url, str(dest)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode("utf-8", "replace")[:500])
    return dest


def _run_cockpit(repo: Path) -> dict:
    r = _sh([sys.executable, "-m", "cockpit.cli", "check", str(repo), "--json"],
            timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"cockpit failed: {r.stderr.decode()[:500]}")
    return json.loads(r.stdout)


def _run_ruff(repo: Path) -> list[dict]:
    """Return list of {filename, location:{row}, code} dicts."""
    r = _sh(["ruff", "check", str(repo), "--select", RUFF_RULES,
             "--output-format", "json", "--no-cache"])
    # ruff returns non-zero when it finds violations — that's fine.
    if not r.stdout:
        return []
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []


def _index_ruff(repo: Path, ruff_hits: list[dict]) -> dict[str, list[int]]:
    """path (repo-relative posix) -> sorted list of row numbers."""
    idx: dict[str, list[int]] = {}
    root = repo.resolve()
    for h in ruff_hits:
        fn = Path(h["filename"]).resolve()
        try:
            rel = fn.relative_to(root).as_posix()
        except ValueError:
            continue
        idx.setdefault(rel, []).append(h["location"]["row"])
    for v in idx.values():
        v.sort()
    return idx


def _covered_by_ruff(finding: dict, ruff_idx: dict[str, list[int]]) -> bool:
    rows = ruff_idx.get(finding["file"])
    if not rows:
        return False
    start = finding["span"][0]
    # any ruff row within TOLERANCE of the finding span start counts
    for r in rows:
        if abs(r - start) <= TOLERANCE:
            return True
    return False


def process(name: str, ref: str, url: str, unique_writer: csv.writer) -> RepoResult:
    try:
        repo = _clone(name, ref, url)
        env = _run_cockpit(repo)
        ruff_hits = _run_ruff(repo)
    except Exception as e:
        return RepoResult(name, 0, 0, 0, 0, 0, error=str(e)[:200]), {}

    ruff_idx = _index_ruff(repo, ruff_hits)
    # Only compare risk.error-masking to ruff — dup and assertion-free have no ruff analog
    error_findings = [f for f in env["findings"] if f["analyzer_id"] == "risk.error-masking"]
    dup_findings = [f for f in env["findings"] if f["analyzer_id"] == "dup.block"]
    assn_findings = [f for f in env["findings"] if f["analyzer_id"] == "test.assertion-free"]
    overlap = 0
    unique = 0
    for f in error_findings:
        if _covered_by_ruff(f, ruff_idx):
            overlap += 1
        else:
            unique += 1
            unique_writer.writerow([
                name, f["file"], f["span"][0], f["evidence"].get("kind", ""),
                f["message"], "",  # label column, blank for hand-tagging
            ])

    return RepoResult(
        name=name,
        files_scanned=env["summary"]["files_scanned"],
        cockpit_findings=len(error_findings),
        ruff_findings=len(ruff_hits),
        overlap=overlap,
        unique_to_cockpit=unique,
    ), {"dup.block": len(dup_findings), "test.assertion-free": len(assn_findings)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    CLONES.mkdir(parents=True, exist_ok=True)

    with (OUT / "unique.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["repo", "file", "line", "kind", "message", "label"])
        results: list[RepoResult] = []
        extras: dict[str, dict[str, int]] = {}
        for name, ref, url in _load_repos():
            print(f"[{name}]")
            r, extra = process(name, ref, url, writer)
            results.append(r)
            extras[name] = extra
            if r.error:
                print(f"  ERROR: {r.error}")
            else:
                print(f"  files={r.files_scanned} em(cockpit)={r.cockpit_findings} "
                      f"em(ruff)={r.ruff_findings} overlap={r.overlap} "
                      f"unique={r.unique_to_cockpit} "
                      f"dup={extra.get('dup.block',0)} "
                      f"assn={extra.get('test.assertion-free',0)}")

    (OUT / "overlap.json").write_text(
        json.dumps([r.__dict__ for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    ok = [r for r in results if not r.error]
    total_cockpit_em = sum(r.overlap + r.unique_to_cockpit for r in ok)
    total_overlap = sum(r.overlap for r in ok)
    total_unique = sum(r.unique_to_cockpit for r in ok)
    total_ruff = sum(r.ruff_findings for r in ok)
    total_files = sum(r.files_scanned for r in ok)
    overlap_pct = (100 * total_overlap / total_cockpit_em) if total_cockpit_em else 0
    unique_pct = (100 * total_unique / total_cockpit_em) if total_cockpit_em else 0

    md = f"""# Week 3 Gate — Overlap Report

Repos analyzed: {len(ok)} / {len(results)}
Total files scanned: {total_files}
Ruff rules compared: `{RUFF_RULES}`
Tolerance: ±{TOLERANCE} lines

## Error-masking overlap

| | Count |
|---|---|
| cockpit `risk.error-masking` total | {total_cockpit_em} |
| ruff hits (all files) | {total_ruff} |
| **overlap** (same file:line ±{TOLERANCE}) | {total_overlap} ({overlap_pct:.1f}%) |
| **unique to cockpit** | {total_unique} ({unique_pct:.1f}%) |

## Per repo (all analyzers)

| repo | files | em (cockpit) | em (ruff) | overlap | em unique | dup.block | assertion-free |
|---|---:|---:|---:|---:|---:|---:|---:|
""" + "\n".join(
        f"| {r.name} | {r.files_scanned} | {r.cockpit_findings} | "
        f"{r.ruff_findings} | {r.overlap} | {r.unique_to_cockpit} | "
        f"{extras.get(r.name, {}).get('dup.block', 0)} | "
        f"{extras.get(r.name, {}).get('test.assertion-free', 0)} |"
        for r in ok
    ) + "\n"

    if any(r.error for r in results):
        md += "\n## Errors\n" + "\n".join(
            f"- {r.name}: {r.error}" for r in results if r.error
        ) + "\n"

    (OUT / "summary.md").write_text(md, encoding="utf-8")
    print(f"\n=> {OUT/'summary.md'}")
    print(f"=> {OUT/'unique.csv'}  ({total_unique} rows to label)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
