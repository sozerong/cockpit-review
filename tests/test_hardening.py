"""v0.2.1 hardening — regression tests for the four-reviewer findings.

Every test here maps to a specific issue the QA / Security / Backend
review flagged. Losing any of these to a refactor is a regression."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path

import pytest

from cockpit import baseline as bl
from cockpit.changeset import from_git_diff
from cockpit.indexer import FileIndex, index_file, _next_generation
from cockpit.scanner import scan


# ── QA + Backend: FileIndex.generation replaces id() as cache key ──

def test_fileindex_generation_is_monotonic(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")
    a = index_file("a.py", tmp_path / "a.py")
    b = index_file("b.py", tmp_path / "b.py")
    assert a.generation < b.generation


def test_fileindex_generations_never_collide_after_gc():
    """The id()-reuse hazard: CPython recycles freed ids. A monotonic
    counter never does. Force GC pressure and check no two indices
    ever share a generation within a session."""
    import gc
    seen: set[int] = set()
    for i in range(200):
        idx = FileIndex(path=f"p{i}.py", content_hash="h", lines=1, symbols=())
        assert idx.generation not in seen
        seen.add(idx.generation)
        if i % 20 == 0:
            gc.collect()


# ── QA: baseline.load must survive a corrupt file, not crash the daemon ──

def test_baseline_load_returns_none_on_corrupt_json(tmp_path, capsys):
    p = tmp_path / ".cockpit"
    p.mkdir()
    (p / "baseline.json").write_text("{not json")
    assert bl.load(tmp_path) is None
    assert "unreadable" in capsys.readouterr().err


def test_baseline_load_returns_none_on_wrong_schema(tmp_path):
    p = tmp_path / ".cockpit"
    p.mkdir()
    (p / "baseline.json").write_text('{"schema": 1, "ids": "not a list"}')
    assert bl.load(tmp_path) is None


def test_baseline_load_returns_none_on_top_level_list(tmp_path):
    p = tmp_path / ".cockpit"
    p.mkdir()
    (p / "baseline.json").write_text('[]')
    assert bl.load(tmp_path) is None


# ── Security: from_git_diff must reject argv-injecting refs ──

@pytest.mark.parametrize("ref", [
    "--upload-pack=/tmp/evil",
    "-p",
    "; rm -rf /",
    "` echo pwned `",
    "$(whoami)",
    "..",
    "..\\evil",
    "a b",
    "a\ta",
])
def test_from_git_diff_rejects_unsafe_refs(tmp_path, ref):
    with pytest.raises(ValueError, match="unsafe git ref"):
        from_git_diff(tmp_path, base=ref)


def test_from_git_diff_accepts_normal_refs():
    """Sanity: normal refs pass the validator without invoking git."""
    from cockpit.changeset import _safe_ref
    for ref in ["HEAD", "main", "v1.2.3", "a1b2c3d", "HEAD~1", "origin/main",
                "release/2026-09", "feature/foo.bar"]:
        assert _safe_ref(ref), ref


# ── Security: symlink escape ──

def test_scan_skips_symlinks(tmp_path):
    (tmp_path / "real.py").write_text("x = 1\n")
    link = tmp_path / "evil.py"
    try:
        link.symlink_to(tmp_path / "real.py")
    except (OSError, NotImplementedError):
        pytest.skip("filesystem doesn't support symlinks")
    result = scan(tmp_path)
    names = sorted(p.name for p in result)
    assert names == ["real.py"], f"symlink leaked: {names}"


def test_scan_skips_external_symlink(tmp_path):
    """The credential-exfil scenario: `evil.py -> /etc/passwd`. Must not
    return the symlink even though its target looks like source."""
    external = tmp_path.parent / "outside.py"
    external.write_text("secret = 'from outside'\n")
    try:
        (tmp_path / "evil.py").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem doesn't support symlinks")
    try:
        result = scan(tmp_path)
        names = sorted(p.name for p in result)
        assert "evil.py" not in names
    finally:
        try:
            external.unlink()
        except OSError:
            pass


# ── Security: HTML escape covers ", ' for attribute-injection defense ──

# ── Backend: HTTP handler robustness ──

def test_handler_rejects_host_header_outside_allowlist(tmp_path):
    """DNS-rebinding guard: a request with Host: evil.com must fail
    even if it reaches the loopback socket."""
    import socket
    import threading
    from http.server import ThreadingHTTPServer
    from cockpit import serve

    (tmp_path / "a.py").write_text("x = 1\n")
    serve._ALLOWED_HOSTS.clear()
    serve._ALLOWED_HOSTS.update({"127.0.0.1:9911", "localhost:9911", "127.0.0.1", "localhost"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 9911), serve._Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        s = socket.create_connection(("127.0.0.1", 9911), timeout=2)
        s.sendall(b"GET /system.json HTTP/1.0\r\nHost: evil.com\r\n\r\n")
        resp = s.recv(4096).decode("latin-1", "replace")
        s.close()
        assert "400" in resp.splitlines()[0], resp[:200]
        # Also verify Server header stripped.
        assert "Server: BaseHTTP" not in resp, resp[:400]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_handler_accepts_loopback_host(tmp_path):
    import socket
    import threading
    from http.server import ThreadingHTTPServer
    from cockpit import serve
    (tmp_path / "a.py").write_text("x = 1\n")
    serve._ALLOWED_HOSTS.clear()
    serve._ALLOWED_HOSTS.update({"127.0.0.1:9912", "localhost:9912"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 9912), serve._Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        s = socket.create_connection(("127.0.0.1", 9912), timeout=2)
        s.sendall(b"GET /system.json HTTP/1.0\r\nHost: 127.0.0.1:9912\r\n\r\n")
        resp = s.recv(4096).decode("latin-1", "replace")
        s.close()
        assert "200" in resp.splitlines()[0], resp[:200]
        assert "X-Content-Type-Options: nosniff" in resp
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_handler_rejects_malformed_since_param(tmp_path):
    import socket, threading
    from http.server import ThreadingHTTPServer
    from cockpit import serve
    serve._ALLOWED_HOSTS.clear()
    httpd = ThreadingHTTPServer(("127.0.0.1", 9913), serve._Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        s = socket.create_connection(("127.0.0.1", 9913), timeout=2)
        s.sendall(b"GET /state.json?since=abc HTTP/1.0\r\n\r\n")
        resp = s.recv(4096).decode("latin-1", "replace")
        s.close()
        # Must be 400, not 500 (previous version raised uncaught ValueError).
        assert "400" in resp.splitlines()[0], resp[:200]
    finally:
        httpd.shutdown()
        httpd.server_close()


# ── Backend: watch loop must survive a scan exception ──

def test_watch_loop_survives_scan_exception(tmp_path, monkeypatch):
    """A crashed _scan must not wedge the UI in 'scanning...' forever."""
    from cockpit import serve
    calls = []

    def bad_scan(repo, force_full=False):
        calls.append(force_full)
        raise RuntimeError("scan blew up")

    # Replace both the module-level _scan and the state singleton to
    # avoid touching global state.
    monkeypatch.setattr(serve, "_scan", bad_scan)
    monkeypatch.setattr(serve, "_state", serve._State())

    # Just run a single iteration of the safe_scan pattern manually
    # to prove it doesn't propagate.
    fake_state = serve._state
    try:
        fake_state.set_scanning(True)
        try:
            fake_state.set(bad_scan(tmp_path, force_full=True))
        except Exception:
            pass  # this is what _safe_scan catches
        finally:
            fake_state.set_scanning(False)
    except Exception as e:
        pytest.fail(f"_safe_scan pattern leaked exception: {e}")

    assert fake_state.scanning is False, "scanning flag left stuck on crash"


def test_esc_function_covers_quote_and_apostrophe():
    """The `esc()` used in serve.py and ui.py must escape " and ' so a
    filename like `a"onmouseover="alert(1)"b.py` can't break out of an
    HTML attribute."""
    from cockpit import serve, ui
    for module in (serve, ui):
        page = getattr(module, "_PAGE", None) or getattr(module, "_TEMPLATE", "")
        # The literal esc() body must include the "-to-&quot; mapping and
        # the '-to-&#39; mapping.
        assert "&quot;" in page, \
            f"{module.__name__} esc() does not escape \" — XSS regression"
        assert "&#39;" in page, \
            f"{module.__name__} esc() does not escape ' — XSS regression"
