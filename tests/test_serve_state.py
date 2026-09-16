"""serve._State / _scan — the SYSTEM-panel data path.

Focus is behaviour that the UI actually shows: phase machine transitions
land in `events`, `snapshot_system` is thread-safe & self-consistent,
`_scan` produces the timings/errors keys the UI reads."""
from __future__ import annotations
import threading
import time

import pytest


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Reset the module-level singleton around each test."""
    from cockpit import serve
    monkeypatch.setattr(serve, "_state", serve._State())
    yield


def test_phase_transitions_land_in_events():
    from cockpit.serve import _state
    _state.set_phase("scanning", "cold start")
    _state.set_phase("emitting")
    _state.set_phase("idle")

    snap = _state.snapshot_system()
    phases = [e["phase"] for e in snap["events"]]
    assert phases[:3] == ["idle", "emitting", "scanning"]  # deque appendleft = reverse chrono


def test_snapshot_system_returns_alive_threads():
    from cockpit.serve import _state
    snap = _state.snapshot_system()
    names = [t["name"] for t in snap["threads"]]
    assert "MainThread" in names
    # Uptime is present and reasonable.
    assert 0 <= snap["uptime_s"] < 3600


def test_scan_emits_timings_and_errors_keys(tmp_path):
    (tmp_path / "t.py").write_bytes(b"def f(x=[]): pass\n")
    from cockpit.serve import _scan
    env = _scan(tmp_path)
    # Envelope schema (v1) plus serve additions.
    assert env["schema"] == 1
    assert env["summary"]["files_scanned"] == 1
    assert env["has_baseline"] in (True, False)
    assert env["timings"]["total_ms"] >= 0
    assert env["timings"]["index_ms"] >= 0
    assert env["timings"]["changeset_ms"] >= 0
    assert isinstance(env["timings"]["analyzers"], list)
    assert env["errors"]["index_total"] == 0
    assert env["errors"]["analyzer"] == []


def test_scan_each_analyzer_gets_a_timing_entry(tmp_path):
    from cockpit.analyzers import ANALYZERS
    from cockpit.serve import _scan
    (tmp_path / "t.py").write_bytes(b"def f(): pass\n")
    env = _scan(tmp_path)
    ids = {t["id"] for t in env["timings"]["analyzers"]}
    expected = {a.id for a in ANALYZERS}
    assert ids == expected


def test_scan_annotates_findings_with_rationale(tmp_path):
    (tmp_path / "t.py").write_bytes(b"def f(x=[]): pass\n")
    from cockpit.serve import _scan
    env = _scan(tmp_path)
    hit = next(f for f in env["findings"] if f["analyzer_id"] == "arg.mutable-default")
    assert hit["rationale"]              # EN rationale attached
    assert hit["rationale_ko"]           # KO rationale attached
    assert "call" in hit["rationale"] or "def" in hit["rationale"]


def test_wait_after_returns_immediately_when_version_ahead():
    from cockpit.serve import _state
    _state.version = 5
    _state.envelope = {"schema": 1}
    t0 = time.perf_counter()
    v, env, scanning = _state.wait_after(since=3, timeout=5)
    assert time.perf_counter() - t0 < 0.05
    assert v == 5


def test_wait_after_wakes_on_phase_change():
    """A phase transition notifies waiters — client will re-poll."""
    from cockpit.serve import _state
    _state.envelope = {"schema": 1}

    def flip():
        time.sleep(0.05)
        _state.set_phase("scanning")

    t = threading.Thread(target=flip)
    t.start()
    t0 = time.perf_counter()
    _state.wait_after(since=0, timeout=1.5)
    assert time.perf_counter() - t0 < 0.3   # notified, not timed out
    t.join()
