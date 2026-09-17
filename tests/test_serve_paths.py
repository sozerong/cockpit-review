"""Fill the serve.py coverage gap (v0.3.0 QA gate ≥65%): _State.set,
_counts_by_analyzer, _changed_paths, watch-loop change detection, and
handler responses for /, /state.json, /system.json, 404."""
from __future__ import annotations
import json
import socket
import threading
import time

import pytest
from http.server import ThreadingHTTPServer

from cockpit import serve


# ── _State + helpers ──────────────────────────────────────────────────

def test_state_set_publishes_and_bumps_version():
    st = serve._State()
    env = {
        "findings": [{"id": "a", "analyzer_id": "x", "severity": "warn"}],
        "summary": {"files_scanned": 1},
    }
    v0 = st.version
    st.set(env)
    assert st.version == v0 + 1
    assert st.envelope is env
    # Publishes activity + analyzer_counts.
    assert "activity" in env
    assert env["activity"][0]["new"] == 1
    assert env["activity"][0]["gone"] == 0
    assert env["analyzer_counts"][0]["id"] == "x"


def test_state_set_computes_deltas_across_scans():
    st = serve._State()
    st.set({
        "findings": [{"id": "a", "analyzer_id": "x", "severity": "warn"}],
        "summary": {"files_scanned": 1},
    })
    st.set({
        "findings": [{"id": "b", "analyzer_id": "x", "severity": "warn"}],
        "summary": {"files_scanned": 1},
    })
    # Second envelope: new=1 (b), gone=1 (a).
    activity = st.envelope["activity"][0]
    assert activity["new"] == 1
    assert activity["gone"] == 1


def test_counts_by_analyzer_sorts_by_total_desc():
    findings = [
        {"analyzer_id": "a", "severity": "info"},
        {"analyzer_id": "b", "severity": "warn"},
        {"analyzer_id": "b", "severity": "info"},
        {"analyzer_id": "b", "severity": "block"},
    ]
    counts = serve._counts_by_analyzer(findings)
    assert counts[0]["id"] == "b"
    assert counts[0]["total"] == 3
    assert counts[1]["id"] == "a"


def test_changed_paths_reports_added_removed_modified():
    prev = {"a.py": 1.0, "b.py": 2.0, "c.py": 3.0}
    cur = {"a.py": 1.0, "b.py": 9.0, "d.py": 4.0}
    got = serve._changed_paths(prev, cur)
    assert set(got) == {"b.py", "c.py", "d.py"}


def test_changed_paths_truncates_at_20():
    prev = {f"f{i}.py": 0.0 for i in range(30)}
    cur = {f"f{i}.py": float(i) for i in range(30)}
    assert len(serve._changed_paths(prev, cur)) == 20


# ── watch loop (via monkeypatched sleep) ──────────────────────────────

def test_watch_loop_detects_change_then_debounces(make_repo, monkeypatch):
    """The loop must transition phase to `debouncing` when files change."""
    repo = make_repo({"a.py": b"x = 1\n"})
    monkeypatch.setattr(serve, "_state", serve._State())
    monkeypatch.setattr(serve, "_scanner", serve.IncrementalScanner())
    calls = {"n": 0}
    scans = {"n": 0}

    def fake_scan(r, force_full=False):
        scans["n"] += 1
        return {
            "findings": [],
            "summary": {"files_scanned": 1},
            "timings": {}, "errors": {}, "incremental": {"mode": "cold"},
        }
    monkeypatch.setattr(serve, "_scan", fake_scan)

    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] == 1:
            (repo / "a.py").write_text("x = 2\n")
        if calls["n"] >= 4:
            raise KeyboardInterrupt
    monkeypatch.setattr(serve.time, "sleep", fake_sleep)
    monkeypatch.setattr(serve, "DEBOUNCE", 0.0)

    with pytest.raises(KeyboardInterrupt):
        serve._watch_loop(repo)
    # Initial cold scan + at least one rerun after debounce.
    assert scans["n"] >= 2


# ── HTTP handler paths ────────────────────────────────────────────────

@pytest.fixture
def running_server():
    """Boot a real ThreadingHTTPServer on an ephemeral port, tear down
    cleanly. Yields the (port, sock_addr) so tests hit real sockets."""
    serve._ALLOWED_HOSTS.clear()
    serve._ALLOWED_HOSTS.update({"127.0.0.1", "localhost"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve._Handler)
    port = httpd.server_address[1]
    serve._ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


def _get(port: int, path: str, host: str = None) -> tuple[str, str]:
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    h = host or f"127.0.0.1:{port}"
    s.sendall(f"GET {path} HTTP/1.0\r\nHost: {h}\r\n\r\n".encode())
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    header, _, body = data.partition(b"\r\n\r\n")
    return header.decode("latin-1"), body.decode("utf-8", "replace")


def test_handler_serves_root_html(running_server):
    h, body = _get(running_server, "/")
    assert "200" in h.splitlines()[0]
    assert "Content-Security-Policy" in h
    assert "<title>" in body


def test_handler_serves_system_json(running_server):
    h, body = _get(running_server, "/system.json")
    assert "200" in h.splitlines()[0]
    js = json.loads(body)
    assert "phase" in js and "uptime_s" in js


def test_handler_serves_state_json(running_server):
    h, body = _get(running_server, "/state.json?since=-1")
    assert "200" in h.splitlines()[0]
    js = json.loads(body)
    assert "version" in js
    assert "system" in js


def test_handler_returns_404_for_unknown_path(running_server):
    h, _ = _get(running_server, "/nope")
    assert "404" in h.splitlines()[0]


def test_handler_rejects_bad_url(running_server):
    """A path with a raw non-URL byte trips urlparse's ValueError branch."""
    s = socket.create_connection(("127.0.0.1", running_server), timeout=2)
    s.sendall(b"GET http://[bad HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
    data = s.recv(1024)
    s.close()
    # Either 400 (bad url) or 404 (path not matched) — server must not crash.
    assert b"400" in data or b"404" in data


def test_handler_head_request_omits_body(running_server):
    """do_HEAD reuses do_GET; HEAD must not write the body."""
    s = socket.create_connection(("127.0.0.1", running_server), timeout=2)
    s.sendall(f"HEAD / HTTP/1.0\r\nHost: 127.0.0.1:{running_server}\r\n\r\n".encode())
    data = s.recv(65536)
    s.close()
    header, _, body = data.partition(b"\r\n\r\n")
    assert b"200" in header.splitlines()[0]
    # HEAD response must have empty body.
    assert body == b""
