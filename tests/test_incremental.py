"""Incremental scanner — the M0.2 UX blocker (fastapi 5.8s → sub-second).

Semantics: an incremental scan must produce the same findings as a fresh
full scan. Timing: reindex + re-analyze only what changed."""
from __future__ import annotations
import time

import pytest

from cockpit.incremental import IncrementalScanner


def _write(root, path, content):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def _finding_ids(env):
    return {(f["analyzer_id"], f["file"], tuple(f["span"])) for f in env["findings"]}


def test_cold_scan_populates_cache(tmp_path):
    _write(tmp_path, "a.py", "def f(x=[]): pass\n")
    scan = IncrementalScanner()
    env = scan.scan(tmp_path)
    assert env["incremental"]["mode"] == "cold"
    assert env["incremental"]["reindexed"] == 1
    assert "a.py" in scan.indices
    assert env["summary"]["files_scanned"] == 1


def test_warm_scan_with_no_changes_reindexes_nothing(tmp_path):
    _write(tmp_path, "a.py", "def f(x=[]): pass\n")
    scan = IncrementalScanner()
    scan.scan(tmp_path)   # cold populates cache
    env = scan.scan(tmp_path)  # warm — nothing changed
    assert env["incremental"]["mode"] == "warm"
    assert env["incremental"]["reindexed"] == 0
    assert env["incremental"]["cached_files"] == 1


def test_modifying_one_file_reindexes_only_that_file(tmp_path):
    _write(tmp_path, "a.py", "def f(): pass\n")
    _write(tmp_path, "b.py", "def g(): pass\n")
    _write(tmp_path, "c.py", "def h(): pass\n")
    scan = IncrementalScanner()
    scan.scan(tmp_path)

    time.sleep(0.05)   # ensure mtime tick on all filesystems
    _write(tmp_path, "b.py", "def g(x=[]): pass\n")

    env = scan.scan(tmp_path)
    assert env["incremental"]["reindexed"] == 1
    assert env["incremental"]["cached_files"] == 2
    # New finding surfaces from b.py.
    hits = [f for f in env["findings"] if f["analyzer_id"] == "arg.mutable-default"]
    assert len(hits) == 1
    assert hits[0]["file"] == "b.py"


def test_deleting_a_file_drops_its_findings(tmp_path):
    _write(tmp_path, "a.py", "def f(x=[]): pass\n")
    _write(tmp_path, "b.py", "def g(x=[]): pass\n")
    scan = IncrementalScanner()
    env0 = scan.scan(tmp_path)
    assert len([f for f in env0["findings"] if f["analyzer_id"] == "arg.mutable-default"]) == 2

    (tmp_path / "b.py").unlink()
    env1 = scan.scan(tmp_path)
    assert env1["incremental"]["removed"] == 1
    hits = [f for f in env1["findings"] if f["analyzer_id"] == "arg.mutable-default"]
    assert len(hits) == 1
    assert hits[0]["file"] == "a.py"
    assert "b.py" not in scan.indices


def test_incremental_equivalent_to_full_scan(tmp_path):
    """Findings after a series of incremental scans must match a fresh
    full scan of the final state."""
    _write(tmp_path, "a.py", "def f(x=[]): pass\n")
    _write(tmp_path, "b.py", "def g(): pass\n")
    _write(tmp_path, "c.py", "import time\ndef test_h():\n    time.sleep(1)\n")

    scan = IncrementalScanner()
    scan.scan(tmp_path)

    time.sleep(0.05)
    _write(tmp_path, "b.py", "def g():\n    try: x()\n    except Exception as e: raise e\n")
    scan.scan(tmp_path)

    time.sleep(0.05)
    _write(tmp_path, "d.py", "def i(y={}): pass\n")
    env_incr = scan.scan(tmp_path)

    # Fresh full scan for comparison.
    fresh = IncrementalScanner()
    env_full = fresh.scan(tmp_path, force_full=True)

    assert _finding_ids(env_incr) == _finding_ids(env_full)


def test_cross_file_analyzer_full_reruns(tmp_path):
    """dup.block cross-file — a change in file A can affect file B's
    findings, so its cache must be rebuilt from scratch each scan."""
    # Two files with identical function bodies → dup.block should match.
    body = "def f():\n    x = 1\n    y = 2\n    z = 3\n    w = 4\n    return x + y + z + w\n"
    _write(tmp_path, "a.py", body)
    _write(tmp_path, "b.py", body)
    scan = IncrementalScanner()
    env0 = scan.scan(tmp_path)
    dup0 = [f for f in env0["findings"] if f["analyzer_id"] == "dup.block"]

    # Modify b.py to a UNIQUE body — dup.block finding for a.py must vanish
    # even though a.py itself was not re-indexed.
    time.sleep(0.05)
    _write(tmp_path, "b.py", "def g():\n    return 42\n")
    env1 = scan.scan(tmp_path)
    dup1 = [f for f in env1["findings"] if f["analyzer_id"] == "dup.block"]
    assert len(dup1) < len(dup0), \
        f"dup.block should re-evaluate a.py when b.py changed; got {dup0=} -> {dup1=}"


def test_index_error_does_not_break_scan(tmp_path):
    _write(tmp_path, "good.py", "def f(x=[]): pass\n")
    _write(tmp_path, "bad.py", b"\xff\xfe not utf-8\x00")
    scan = IncrementalScanner()
    env = scan.scan(tmp_path)
    # good.py analyzed normally; bad.py logged as an index error.
    good_hits = [f for f in env["findings"] if f["file"] == "good.py" and f["analyzer_id"] == "arg.mutable-default"]
    assert len(good_hits) == 1
    # bad.py may or may not raise depending on indexer — assert we didn't crash.
    assert isinstance(env["errors"]["index_total"], int)


def test_reset_clears_all_caches(tmp_path):
    _write(tmp_path, "a.py", "def f(x=[]): pass\n")
    scan = IncrementalScanner()
    scan.scan(tmp_path)
    assert scan.indices
    scan.reset()
    assert not scan.indices and not scan.mtimes and not scan.cache


def test_analyzer_timings_have_cross_file_flag(tmp_path):
    _write(tmp_path, "a.py", "def f(): pass\n")
    env = IncrementalScanner().scan(tmp_path)
    by_id = {t["id"]: t for t in env["timings"]["analyzers"]}
    assert by_id["dup.block"]["cross_file"] is True
    assert by_id["arg.mutable-default"]["cross_file"] is False
