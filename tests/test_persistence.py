"""Scanner state persistence: save/load survives a fresh process."""
from __future__ import annotations
import json

import pytest

from cockpit.incremental import IncrementalScanner, _STATE_FILE


def test_save_creates_state_file(make_repo):
    repo = make_repo({"a.py": b"x = 1\n"})
    s = IncrementalScanner()
    s.scan(repo)
    s.save(repo)
    p = repo / ".cockpit" / "state" / _STATE_FILE
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert "a.py" in data["indices"]


def test_load_round_trip_preserves_findings(make_repo):
    # Two files with an identical 5-line block → dup.block emits findings.
    block = b"def f(x):\n    a = x\n    b = a + 1\n    c = b * 2\n    return c\n"
    repo = make_repo({"a.py": block, "b.py": block})
    s1 = IncrementalScanner()
    env1 = s1.scan(repo)
    s1.save(repo)
    assert env1["incremental"]["mode"] == "cold"

    s2 = IncrementalScanner()
    assert s2.load(repo) is True
    assert set(s2.indices) == set(s1.indices)
    assert set(s2.cache) == set(s1.cache)

    env2 = s2.scan(repo)
    # No file changed → warm hit, zero reindexed.
    assert env2["incremental"]["mode"] == "warm"
    assert env2["incremental"]["reindexed"] == 0


def test_load_returns_false_on_missing(tmp_path):
    s = IncrementalScanner()
    assert s.load(tmp_path) is False


def test_load_returns_false_on_corrupt(make_repo):
    repo = make_repo({"a.py": b"x = 1\n"})
    (repo / ".cockpit" / "state").mkdir(parents=True)
    (repo / ".cockpit" / "state" / _STATE_FILE).write_text("{not json")
    s = IncrementalScanner()
    assert s.load(repo) is False


def test_load_returns_false_on_version_mismatch(make_repo):
    repo = make_repo({"a.py": b"x = 1\n"})
    IncrementalScanner().scan(repo)
    p = repo / ".cockpit" / "state"
    p.mkdir(parents=True, exist_ok=True)
    (p / _STATE_FILE).write_text(json.dumps({
        "schema": 1, "cockpit_version": "0.0.0-not-us",
        "indices": {}, "mtimes": {}, "cache": {},
    }))
    s = IncrementalScanner()
    assert s.load(repo) is False


def test_load_advances_generation_counter(make_repo):
    """A rehydrated FileIndex must not share a generation with any freshly
    indexed one — CPython id() reuse regression + persistence collision."""
    repo = make_repo({"a.py": b"x = 1\n"})
    s1 = IncrementalScanner()
    s1.scan(repo)
    s1.save(repo)
    loaded_gen = next(iter(s1.indices.values())).generation

    s2 = IncrementalScanner()
    s2.load(repo)
    # Force a fresh index of a NEW file; its generation must exceed the loaded one.
    (repo / "b.py").write_bytes(b"y = 2\n")
    s2.scan(repo)
    new_gen = s2.indices["b.py"].generation
    assert new_gen > loaded_gen, (new_gen, loaded_gen)


def test_save_is_atomic(make_repo, monkeypatch):
    """A crash mid-write must not leave a half-written scanner-v1.json."""
    repo = make_repo({"a.py": b"x = 1\n"})
    s = IncrementalScanner()
    s.scan(repo)
    s.save(repo)

    # Corrupt tmp file — save() must not leave it dangling as the real one.
    import os
    p = repo / ".cockpit" / "state" / _STATE_FILE
    orig = p.read_text(encoding="utf-8")

    real_replace = os.replace
    def fail_replace(*a, **kw):
        raise OSError("simulated crash")
    monkeypatch.setattr(os, "replace", fail_replace)
    s.save(repo)  # swallowed
    # Original untouched.
    assert p.read_text(encoding="utf-8") == orig
