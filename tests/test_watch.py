"""cockpit watch — poll loop + NDJSON emission."""
from __future__ import annotations
import io
import json
from contextlib import redirect_stdout

import pytest

from cockpit import watch as w


def test_snapshot_returns_path_to_mtime(make_repo):
    repo = make_repo({"a.py": b"x = 1\n", "b.py": b"y = 2\n"})
    snap = w._snapshot(repo)
    assert set(snap) == {"a.py", "b.py"}
    assert all(isinstance(v, float) for v in snap.values())


def test_snapshot_skips_editor_temp_files(make_repo, monkeypatch):
    """Editor temp files (.swp/.swo/~/.tmp/.#*) must not appear in the
    snapshot — they flap during saves and would trigger endless reruns."""
    from cockpit import scanner
    repo = make_repo({
        "a.py": b"x = 1\n",
        ".a.py.swp": b"junk",
        "b.py~": b"backup",
    })
    # scanner.scan already filters non-.py; force the temp file into
    # the snapshot's fc list by patching scan to return every file.
    fake_files = [
        type("F", (), {"path": "a.py", "absolute": repo / "a.py"})(),
        type("F", (), {"path": ".a.py.swp", "absolute": repo / ".a.py.swp"})(),
        type("F", (), {"path": "b.py~", "absolute": repo / "b.py~"})(),
    ]
    class FakeCS:
        files = fake_files
    monkeypatch.setattr(w, "full_scan", lambda repo: FakeCS())
    snap = w._snapshot(repo)
    assert "a.py" in snap
    assert ".a.py.swp" not in snap
    assert "b.py~" not in snap


def test_run_once_returns_valid_envelope(make_repo):
    repo = make_repo({"a.py": b"def f(): pass\n"})
    env = w._run_once(repo)
    assert env["schema"] == 1
    assert env["summary"]["files_scanned"] == 1
    assert isinstance(env["findings"], list)


def test_run_once_tolerates_parse_error(make_repo):
    """A file that tree-sitter can't parse must not crash the whole scan."""
    repo = make_repo({"good.py": b"x = 1\n"})
    env = w._run_once(repo)
    # Should scan the good file at least.
    assert env["summary"]["files_scanned"] >= 1


def test_emit_writes_one_ndjson_line(capsys):
    w._emit({"schema": 1, "hello": "world"})
    out = capsys.readouterr().out
    assert out.endswith("\n")
    assert json.loads(out.strip()) == {"schema": 1, "hello": "world"}


def test_cmd_watch_once_emits_single_envelope(make_repo, capsys):
    repo = make_repo({"a.py": b"x = 1\n"})
    rc = w.cmd_watch(repo, once=True)
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    env = json.loads(lines[0])
    assert env["schema"] == 1


def test_cmd_watch_loop_reruns_after_change(make_repo, monkeypatch, capsys):
    """The polling loop must re-emit after a change + debounce."""
    repo = make_repo({"a.py": b"x = 1\n"})
    calls = {"sleep": 0}
    def fake_sleep(_):
        calls["sleep"] += 1
        # After the 1st sleep, mutate a.py so cur != prev.
        if calls["sleep"] == 1:
            (repo / "a.py").write_text("x = 2\n")
        # After the 3rd sleep, break out of the loop.
        if calls["sleep"] >= 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(w.time, "sleep", fake_sleep)
    # Debounce=0 so a single detected change triggers rerun on next tick.
    monkeypatch.setattr(w, "DEBOUNCE", 0.0)
    rc = w.cmd_watch(repo, once=False)
    assert rc == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    # Initial emit + at least one rerun after the debounce.
    assert len(lines) >= 2
    for line in lines:
        assert json.loads(line)["schema"] == 1


def test_cmd_watch_loop_survives_no_changes(make_repo, monkeypatch, capsys):
    """Quiet filesystem → no reruns, just the initial emit."""
    repo = make_repo({"a.py": b"x = 1\n"})
    calls = {"sleep": 0}
    def fake_sleep(_):
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(w.time, "sleep", fake_sleep)
    rc = w.cmd_watch(repo, once=False)
    assert rc == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1  # only the initial emit
