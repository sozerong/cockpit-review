"""cockpit CLI — `check`, `watch`, `baseline`.

Contracts:
- `check --json` emits the schema-1 envelope (PLAN §0 rule 1)
- `check --exit-code` returns non-zero on any warn (or higher) NEW to the
  baseline. CI target.
- `baseline save` snapshots current findings so future runs only see new ones.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from . import baseline as bl
from .analyzers import run_all
from .changeset import full_scan
from .finding import Finding, sort_key, to_json
from .indexer import index_file


_SEV_COLOR = {"block": "\033[31m", "warn": "\033[33m", "info": "\033[36m"}
_RESET = "\033[0m"
_EXIT_ORDER = {"info": 0, "warn": 1, "block": 2}


def _collect(repo: Path) -> tuple[list[Finding], int]:
    cs = full_scan(repo)
    indices = {}
    for fc in cs.files:
        try:
            indices[fc.path] = index_file(fc.path, fc.absolute)
        except Exception as e:
            print(f"warn: index {fc.path}: {e}", file=sys.stderr)
    return run_all(cs, indices), len(indices)


def cmd_check(repo: Path, as_json: bool, use_color: bool,
              exit_code: bool, exit_at: str, use_baseline: bool) -> int:
    findings, files_scanned = _collect(repo)
    baselined: set[str] | None = None
    if use_baseline:
        baselined = bl.load(repo)
        if baselined is None:
            print(f"warn: --baseline requested but no baseline at "
                  f"{bl.path(repo)}", file=sys.stderr)
        else:
            findings = [f for f in findings if f.id not in baselined]

    envelope = to_json(
        repo=str(repo.resolve()),
        scope={"kind": "full", "base": None, "head": "working"},
        findings=findings,
        files_scanned=files_scanned,
    )

    if as_json:
        json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        if baselined is not None:
            print(f"baseline: {len(baselined)} ids suppressed")
        _print_table(envelope, findings, use_color)

    if not exit_code:
        return 0
    threshold = _EXIT_ORDER[exit_at]
    for f in findings:
        if _EXIT_ORDER[f.severity] >= threshold:
            return 1
    return 0


def cmd_baseline_save(repo: Path) -> int:
    findings, _ = _collect(repo)
    p = bl.save(repo, findings)
    print(f"baseline: {len(set(f.id for f in findings))} ids -> {p}")
    return 0


def _print_table(env: dict, findings: list[Finding], use_color: bool) -> None:
    s = env["summary"]
    print(f"scanned {s['files_scanned']} files  "
          f"block={s['block']} warn={s['warn']} info={s['info']}")
    if not findings:
        print("no findings")
        return
    findings = sorted(findings, key=sort_key)
    locs = [f"{f.file}:{f.span[0]}" for f in findings]
    w = min(max(len(x) for x in locs), 60)
    for f, loc in zip(findings, locs):
        color = _SEV_COLOR.get(f.severity, "") if use_color else ""
        reset = _RESET if use_color else ""
        print(f"  {color}{f.severity:5}{reset}  {loc:<{w}}  "
              f"[{f.analyzer_id}] {f.message}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cockpit")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="Analyze a repository")
    c.add_argument("repo", nargs="?", default=".", type=Path)
    c.add_argument("--json", action="store_true", help="Emit JSON envelope")
    c.add_argument("--no-color", action="store_true")
    c.add_argument("--exit-code", action="store_true",
                   help="Exit 1 if any finding at or above --exit-at severity")
    c.add_argument("--exit-at", choices=["info", "warn", "block"], default="warn",
                   help="Minimum severity that triggers --exit-code (default: warn)")
    c.add_argument("--baseline", action="store_true",
                   help="Suppress findings whose ids are in .cockpit/baseline.json")

    w = sub.add_parser("watch", help="Re-run on file changes, NDJSON to stdout")
    w.add_argument("repo", nargs="?", default=".", type=Path)
    w.add_argument("--once", action="store_true", help="Emit once and exit")

    b = sub.add_parser("baseline", help="Manage the finding baseline")
    bsub = b.add_subparsers(dest="baseline_cmd", required=True)
    bs = bsub.add_parser("save", help="Snapshot current findings as baseline")
    bs.add_argument("repo", nargs="?", default=".", type=Path)

    r = sub.add_parser("report", help="Write a self-contained HTML report")
    r.add_argument("repo", nargs="?", default=".", type=Path)
    r.add_argument("--out", type=Path,
                   help="Output path (default: <repo>/cockpit-report.html)")

    args = p.parse_args(argv)
    if args.cmd == "check":
        use_color = sys.stdout.isatty() and not args.no_color
        return cmd_check(args.repo, args.json, use_color,
                         args.exit_code, args.exit_at, args.baseline)
    if args.cmd == "watch":
        from .watch import cmd_watch
        return cmd_watch(args.repo, once=args.once)
    if args.cmd == "baseline" and args.baseline_cmd == "save":
        return cmd_baseline_save(args.repo)
    if args.cmd == "report":
        from .ui import cmd_report
        return cmd_report(args.repo, args.out)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
