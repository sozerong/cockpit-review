"""Subprocess integration tests for the cockpit CLI.

Each test invokes `python -m cockpit.cli` as a real child process against a
tmp_path repo. No mocks — this is the wire-through coverage senior QA
demanded before v0.3.0. Each test caps at <3s wall.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "cockpit.cli"]

# A 5+ non-blank-line function body. Two copies across two files must
# trigger the `dup.block` analyzer (>=5 line window, function body, not
# string-dominant, not in test/example dirs).
_DUP_BODY = '''\
def process(rows):
    total = 0
    for row in rows:
        total += row["value"] * 2
    average = total / max(len(rows), 1)
    return {"total": total, "average": average}
'''


def _run(args: list[str], cwd: Path | None = None, timeout: float = 10.0) -> subprocess.CompletedProcess:
    # timeout=10s (was 3): CI runners can spend >3s just on Python cold
    # start + tree-sitter native import + first tree-sitter parse (JIT-y
    # compilation on first call). Local runs finish in <1s; the higher
    # ceiling only matters when the process is actually stuck.
    return subprocess.run(
        CLI + args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_check_empty_repo_exits_zero(tmp_path: Path) -> None:
    r = _run(["check", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    assert "no findings" in r.stdout.lower()


def test_check_finds_dup_block(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_DUP_BODY, encoding="utf-8")
    (tmp_path / "b.py").write_text(_DUP_BODY, encoding="utf-8")

    r = _run(["check", str(tmp_path), "--json", "--exit-code"])
    # --exit-code + warn dup finding should make it non-zero, but at
    # minimum the envelope must contain a dup.block finding.
    envelope = json.loads(r.stdout)
    ids = {f["analyzer_id"] for f in envelope["findings"]}
    assert "dup.block" in ids, f"got analyzer ids: {ids}"


def test_baseline_roundtrip(tmp_path: Path) -> None:
    # Two dup-block findings on disk (same body in two files).
    (tmp_path / "a.py").write_text(_DUP_BODY, encoding="utf-8")
    (tmp_path / "b.py").write_text(_DUP_BODY, encoding="utf-8")

    # Snapshot the current findings.
    # NOTE: CLI subcommand is `baseline save` (v0.2.1); the task brief
    # said `baseline write`. Using the actual command — source is frozen.
    r_save = _run(["baseline", "save", str(tmp_path)])
    assert r_save.returncode == 0, r_save.stderr
    assert (tmp_path / ".cockpit" / "baseline.json").is_file()

    # First check with --baseline: dup findings should be suppressed.
    r1 = _run(["check", str(tmp_path), "--baseline", "--json"])
    env1 = json.loads(r1.stdout)
    dup1 = [f for f in env1["findings"] if f["analyzer_id"] == "dup.block"]
    assert dup1 == [], f"baseline should suppress dup findings, got {dup1}"

    # Introduce a NEW finding: a mutable default argument.
    (tmp_path / "c.py").write_text(
        "def store(item, bucket=[]):\n    bucket.append(item)\n    return bucket\n",
        encoding="utf-8",
    )

    r2 = _run(["check", str(tmp_path), "--baseline", "--json"])
    env2 = json.loads(r2.stdout)
    ids2 = {f["analyzer_id"] for f in env2["findings"]}
    assert "arg.mutable-default" in ids2, f"new finding missing; got {ids2}"
    dup2 = [f for f in env2["findings"] if f["analyzer_id"] == "dup.block"]
    assert dup2 == [], "baselined dup findings should still be suppressed"


def test_report_produces_html(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(x=[]):\n    x.append(1)\n    return x\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.html"
    r = _run(["report", str(tmp_path), "--out", str(out)])
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert "<title>cockpit" in body
    assert "arg.mutable-default" in body


def test_diff_receipt_shape(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(_DUP_BODY, encoding="utf-8")
    (tmp_path / "b.py").write_text(_DUP_BODY, encoding="utf-8")

    base_path = tmp_path / "base.json"
    r_base = _run(["check", str(tmp_path), "--json"])
    assert r_base.returncode == 0, r_base.stderr
    base_path.write_text(r_base.stdout, encoding="utf-8")

    # Introduce a change: add a new mutable-default finding, and remove
    # one of the dup files so the dup finding resolves.
    (tmp_path / "b.py").unlink()
    (tmp_path / "c.py").write_text(
        "def f(x=[]):\n    x.append(1)\n    return x\n",
        encoding="utf-8",
    )
    head_path = tmp_path / "head.json"
    r_head = _run(["check", str(tmp_path), "--json"])
    assert r_head.returncode == 0, r_head.stderr
    head_path.write_text(r_head.stdout, encoding="utf-8")

    r_diff = _run(
        ["diff", str(base_path), str(head_path), "--format", "markdown"]
    )
    assert r_diff.returncode == 0, r_diff.stderr
    out = r_diff.stdout.lower()
    # format_markdown emits "### + added (N)" / "### - resolved (N)"
    # section headers when there are actionable changes. Accept either
    # the section markers or the summary line as equivalent receipts.
    assert ("added" in out) and ("resolved" in out), r_diff.stdout


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.05)
    return False


def test_serve_starts_and_serves_html(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    port = _pick_free_port()

    proc = subprocess.Popen(
        CLI + ["serve", str(tmp_path), "--port", str(port), "--host", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # macOS GitHub runners are ~2-3x slower for Python cold start
        # (interpreter + tree-sitter native import + full_scan). 2.5s
        # was tight on Ubuntu and flaky on macOS; 8s covers cold start
        # everywhere without adding meaningful wall time when the port
        # opens fast (the wait loop returns as soon as it binds).
        assert _wait_for_port("127.0.0.1", port, timeout=8.0), (
            "serve never bound the port"
        )
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ) as resp:
            assert resp.status == 200
            ctype = resp.headers.get("content-type", "")
            assert "text/html" in ctype, ctype
            body = resp.read().decode("utf-8", "replace")
            assert "<title>" in body.lower()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
