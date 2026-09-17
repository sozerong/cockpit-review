"""Incremental scanner — cache per-file indices + per-analyzer per-file findings.

Full scan on cold start, then only touch files whose mtime changed. Analyzers
listed in `analyzers.CROSS_FILE` re-run over the whole ChangeSet on every
scan (dup.block windows match across files, no-test-for-public checks a
symbol-to-test-file mapping). Single-file analyzers see a mini ChangeSet
of the changed files only; findings for unchanged files come from cache.

Goal: fastapi (1138 files) go from 5.8s full scan → sub-second on a
single-file save. Measured in tests/test_incremental.py.

Persistence: save()/load() dump the caches to `.cockpit/state/scanner-v1.json`
so a fresh `cockpit check` on an unchanged repo hits the warm path instead
of repaying the 5.8s cold scan. Version-stamped by cockpit __version__ →
any upgrade invalidates automatically (analyzer version bumps ride along).
"""
from __future__ import annotations
import itertools
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .analyzers import ANALYZERS, CROSS_FILE
from .changeset import ChangeSet, FileChange, full_scan
from .finding import Finding, to_json
from .indexer import FileIndex, Symbol, _next_generation, index_file

_STATE_SCHEMA = 1
_STATE_FILE = "scanner-v1.json"


PhaseSetter = Callable[[str, str], None]


@dataclass
class IncrementalScanner:
    indices: dict[str, FileIndex] = field(default_factory=dict)
    mtimes: dict[str, float] = field(default_factory=dict)
    # analyzer_id -> file_path -> list[Finding]
    cache: dict[str, dict[str, list[Finding]]] = field(default_factory=dict)

    def reset(self) -> None:
        self.indices.clear()
        self.mtimes.clear()
        self.cache.clear()

    def save(self, repo: Path) -> None:
        """Dump indices/mtimes/cache to `.cockpit/state/scanner-v1.json`.
        Silent on any error — persistence is best-effort, not load-bearing."""
        try:
            state_dir = repo / ".cockpit" / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": _STATE_SCHEMA,
                "cockpit_version": __version__,
                "indices": {p: _index_to_dict(idx) for p, idx in self.indices.items()},
                "mtimes": self.mtimes,
                "cache": {
                    aid: {p: [_finding_to_dict(f) for f in fs]
                          for p, fs in files.items()}
                    for aid, files in self.cache.items()
                },
            }
            target = state_dir / _STATE_FILE
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            pass

    def load(self, repo: Path) -> bool:
        """Rehydrate from disk. Return True on hit, False on miss/corrupt.
        Any exception → treat as absent (same policy as baseline.load)."""
        p = repo / ".cockpit" / "state" / _STATE_FILE
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        if not isinstance(data, dict): return False
        if data.get("schema") != _STATE_SCHEMA: return False
        if data.get("cockpit_version") != __version__: return False
        try:
            indices = {p: _index_from_dict(d) for p, d in data["indices"].items()}
            mtimes = {p: float(m) for p, m in data["mtimes"].items()}
            cache = {
                aid: {p: [_finding_from_dict(fd) for fd in fs]
                      for p, fs in files.items()}
                for aid, files in data["cache"].items()
            }
        except (KeyError, TypeError, ValueError):
            return False
        # Advance the module-level generation counter past every loaded id
        # so a newly indexed file cannot collide with a rehydrated one.
        max_gen = max((idx.generation for idx in indices.values()), default=0)
        from .indexer import _bump_generation_past
        _bump_generation_past(max_gen)
        self.indices = indices
        self.mtimes = mtimes
        self.cache = cache
        return True

    def scan(self, repo: Path, force_full: bool = False,
             set_phase: PhaseSetter | None = None) -> dict:
        """Run analyzers, return schema-1 envelope + timings + errors + incremental stats.

        force_full: bypass the cache. Use for cold start or when the analyzer
        roster has changed.
        set_phase: optional callback (phase, detail) → None for progress
        instrumentation (see cockpit.serve)."""
        _phase = set_phase or (lambda p, d="": None)
        t0 = time.perf_counter()

        _phase("scanning", "changeset")
        cs = full_scan(repo)
        cur_paths: dict[str, FileChange] = {fc.path: fc for fc in cs.files}
        cur_mtimes: dict[str, float] = {}
        for p, fc in cur_paths.items():
            try:
                cur_mtimes[p] = fc.absolute.stat().st_mtime
            except OSError:
                cur_mtimes[p] = 0.0
        t_cs = time.perf_counter()

        # Detect what needs reindexing.
        if force_full or not self.indices:
            changed = set(cur_paths)
            removed: set[str] = set()
            mode = "cold"
        else:
            removed = set(self.mtimes) - set(cur_paths)
            changed = {p for p in cur_paths if self.mtimes.get(p) != cur_mtimes[p]}
            mode = "warm"

        # Drop removed files from every cache layer.
        for p in removed:
            self.indices.pop(p, None)
            self.mtimes.pop(p, None)
            for cache in self.cache.values():
                cache.pop(p, None)

        # Reindex changed files.
        index_errors: list[dict] = []
        _phase("scanning", f"indexing {len(changed)} files")
        for p in changed:
            try:
                self.indices[p] = index_file(p, cur_paths[p].absolute)
                self.mtimes[p] = cur_mtimes[p]
            except Exception as e:
                index_errors.append({
                    "file": p, "kind": type(e).__name__, "message": str(e)[:200],
                })
                self.indices.pop(p, None)
                self.mtimes[p] = cur_mtimes[p]   # remember mtime so we don't retry
        t_idx = time.perf_counter()

        # Build the mini-ChangeSet used by single-file analyzers.
        mini_files = tuple(cur_paths[p] for p in changed if p in cur_paths)
        mini_cs = ChangeSet(repo=cs.repo, kind="watch", base=None,
                            head=cs.head, files=mini_files)

        # Analyzers: cross-file → full re-run; else → mini + merge.
        analyzer_timings: list[dict] = []
        analyzer_errors: list[dict] = []
        for a in ANALYZERS:
            _phase("scanning", f"analyze {a.id}")
            ta = time.perf_counter()
            cache = self.cache.setdefault(a.id, {})
            is_cross = a.id in CROSS_FILE
            n_new = 0
            try:
                if is_cross or mode == "cold":
                    fresh = a.analyze(cs, self.indices)
                    cache.clear()
                    for f in fresh:
                        cache.setdefault(f.file, []).append(f)
                    n_new = len(fresh)
                else:
                    for p in changed:
                        cache[p] = []
                    fresh = a.analyze(mini_cs, self.indices) if mini_files else []
                    for f in fresh:
                        cache.setdefault(f.file, []).append(f)
                    n_new = len(fresh)
            except Exception as e:
                analyzer_errors.append({
                    "analyzer": a.id, "kind": type(e).__name__, "message": str(e)[:200],
                })
            analyzer_timings.append({
                "id": a.id,
                "ms": round((time.perf_counter() - ta) * 1000),
                "findings": n_new,
                "cross_file": is_cross,
            })

        _phase("emitting")
        all_findings = [f for fs_map in self.cache.values() for fs in fs_map.values() for f in fs]

        env = to_json(
            repo=str(repo.resolve()),
            scope={
                "kind": "full" if force_full else "incremental",
                "base": None,
                "head": "working",
            },
            findings=all_findings,
            files_scanned=len(self.indices),
        )
        env["timings"] = {
            "total_ms": round((time.perf_counter() - t0) * 1000),
            "changeset_ms": round((t_cs - t0) * 1000),
            "index_ms": round((t_idx - t_cs) * 1000),
            "analyzers": analyzer_timings,
        }
        env["errors"] = {
            "index": index_errors[:20],
            "analyzer": analyzer_errors,
            "index_total": len(index_errors),
        }
        env["incremental"] = {
            "mode": mode,
            "reindexed": len(changed),
            "removed": len(removed),
            "cached_files": len(cur_paths) - len(changed),
        }
        return env


# ── serialization helpers ─────────────────────────────────────────────

def _index_to_dict(idx: FileIndex) -> dict[str, Any]:
    return {
        "path": idx.path,
        "content_hash": idx.content_hash,
        "lines": idx.lines,
        "symbols": [[s.name, s.kind, s.span[0], s.span[1]] for s in idx.symbols],
        "generation": idx.generation,
    }


def _index_from_dict(d: dict[str, Any]) -> FileIndex:
    symbols = tuple(
        Symbol(name=s[0], kind=s[1], span=(int(s[2]), int(s[3])))
        for s in d["symbols"]
    )
    return FileIndex(
        path=d["path"], content_hash=d["content_hash"],
        lines=int(d["lines"]), symbols=symbols,
        generation=int(d["generation"]),
    )


def _finding_to_dict(f: Finding) -> dict[str, Any]:
    return {
        "aid": f.analyzer_id, "av": f.analyzer_version, "sev": f.severity,
        "file": f.file, "span": [f.span[0], f.span[1]],
        "sym": f.symbol, "msg": f.message, "ev": f.evidence,
    }


def _finding_from_dict(d: dict[str, Any]) -> Finding:
    return Finding(
        analyzer_id=d["aid"], analyzer_version=d["av"], severity=d["sev"],
        file=d["file"], span=(int(d["span"][0]), int(d["span"][1])),
        symbol=d["sym"], message=d["msg"], evidence=d["ev"],
    )
