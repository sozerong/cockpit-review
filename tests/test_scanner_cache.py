"""FileListCache — git-sentinel-based invalidation."""
from __future__ import annotations
import subprocess
import time

import pytest

from cockpit.scanner import FileListCache, _git_sentinels, scan


def _git_init(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)


def _commit(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "x"], check=True)


def test_sentinels_present_for_git_repo(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path)
    sentinels = _git_sentinels(tmp_path.resolve())
    assert sentinels is not None
    keys = [k for k, _ in sentinels]
    assert "index" in keys
    assert "HEAD" in keys


def test_sentinels_absent_for_non_git(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    assert _git_sentinels(tmp_path.resolve()) is None


def test_cache_hit_on_unchanged_git_repo(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path)

    cache = FileListCache()
    r1 = cache.scan(tmp_path)
    assert len(r1) == 1

    # Second scan should return the SAME list object — proves cache hit.
    r2 = cache.scan(tmp_path)
    assert r1 is r2


def test_cache_misses_on_new_commit(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path)

    cache = FileListCache()
    r1 = cache.scan(tmp_path)

    time.sleep(0.05)   # mtime tick
    (tmp_path / "b.py").write_text("y = 2\n")
    _commit(tmp_path)

    r2 = cache.scan(tmp_path)
    assert r1 is not r2, "cache should have invalidated after a new commit"
    assert len(r2) == 2


def test_cache_never_hits_non_git(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    cache = FileListCache()
    r1 = cache.scan(tmp_path)
    r2 = cache.scan(tmp_path)
    assert r1 is not r2, "non-git repo has no invalidation signal — must always rescan"


def test_reset_forces_next_call_to_miss(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path)

    cache = FileListCache()
    r1 = cache.scan(tmp_path)
    cache.reset()
    r2 = cache.scan(tmp_path)
    assert r1 is not r2


def test_module_level_scan_still_works(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path)
    result = scan(tmp_path)
    assert len(result) == 1
    assert result[0].name == "a.py"


def test_full_scan_honors_cache_when_passed(tmp_path):
    """Verify full_scan uses a shared FileListCache correctly."""
    from cockpit.changeset import full_scan
    _git_init(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit(tmp_path)

    cache = FileListCache()
    cs1 = full_scan(tmp_path, cache=cache)
    cs2 = full_scan(tmp_path, cache=cache)
    # ChangeSet objects differ (constructed fresh each call), but the
    # underlying scan list came from cache.
    assert cs1.files == cs2.files
