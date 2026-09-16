"""Incremental scanner — cache per-file indices + per-analyzer per-file findings.

Full scan on cold start, then only touch files whose mtime changed. Analyzers
listed in `analyzers.CROSS_FILE` re-run over the whole ChangeSet on every
scan (dup.block windows match across files, no-test-for-public checks a
symbol-to-test-file mapping). Single-file analyzers see a mini ChangeSet
of the changed files only; findings for unchanged files come from cache.

Goal: fastapi (1138 files) go from 5.8s full scan → sub-second on a
single-file save. Measured in tests/test_incremental.py.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .analyzers import ANALYZERS, CROSS_FILE
from .changeset import ChangeSet, FileChange, full_scan
from .finding import Finding, to_json
from .indexer import FileIndex, index_file


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
