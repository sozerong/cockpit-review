"""Direct in-process CLI tests. Subprocess integration tests in
`tests/integration/` verify the wire-through; these hit cli.py directly
so pytest-cov actually measures the paths (subprocess coverage requires
a coveragerc dance we don't want).
"""
from __future__ import annotations
import json

import pytest

from cockpit.cli import main


def _run(argv: list[str]) -> int:
    return main(argv)


def test_check_exits_zero_on_clean_repo(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n")
    rc = _run(["check", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no findings" in out or "scanned" in out


def test_check_json_emits_valid_envelope(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n")
    rc = _run(["check", str(tmp_path), "--json"])
    out = capsys.readouterr().out
    env = json.loads(out)
    assert env["schema"] == 1
    assert env["summary"]["files_scanned"] == 1
    assert isinstance(env["findings"], list)
    assert rc == 0


def test_check_finds_dup_block(tmp_path, capsys):
    # dup.block scans WINDOWS INSIDE function bodies; body itself must be
    # >= 5 non-blank lines, so give the function a 6-line body.
    block = ("def f(x):\n"
             "    a = x + 1\n"
             "    b = a * 2\n"
             "    c = b - 3\n"
             "    d = c + 4\n"
             "    e = d * 5\n"
             "    return e\n")
    (tmp_path / "a.py").write_text(block)
    (tmp_path / "b.py").write_text(block)
    rc = _run(["check", str(tmp_path), "--json"])
    env = json.loads(capsys.readouterr().out)
    ids = {f["analyzer_id"] for f in env["findings"]}
    assert "dup.block" in ids
    assert rc == 0  # info severity by default


def test_check_exit_code_flag(tmp_path, capsys):
    """--exit-code + a warn-level finding → rc 1."""
    (tmp_path / "a.py").write_text("def f(x=[]): x.append(1)\n")
    rc = _run(["check", str(tmp_path), "--exit-code", "--exit-at", "warn"])
    _ = capsys.readouterr()
    assert rc == 1


def test_check_no_color_output(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def f(x=[]): x.append(1)\n")
    rc = _run(["check", str(tmp_path), "--no-color"])
    out = capsys.readouterr().out
    # ANSI escape must not appear when --no-color.
    assert "\x1b[" not in out
    assert rc == 0


def test_baseline_save_then_check_with_baseline(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def f(x=[]): x.append(1)\n")
    assert _run(["baseline", "save", str(tmp_path)]) == 0
    _ = capsys.readouterr()
    # With baseline, the same finding is suppressed.
    assert _run(["check", str(tmp_path), "--baseline",
                 "--exit-code", "--exit-at", "warn"]) == 0
    _ = capsys.readouterr()


def test_check_with_baseline_missing_warns(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n")
    _run(["check", str(tmp_path), "--baseline"])
    err = capsys.readouterr().err
    assert "no baseline" in err


def test_report_writes_html(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def f(x=[]): x.append(1)\n")
    out = tmp_path / "r.html"
    rc = _run(["report", str(tmp_path), "--out", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "<title>cockpit" in text
    assert "arg.mutable-default" in text


def test_diff_command_receipt(tmp_path, capsys):
    (tmp_path / "a.py").write_text("def f(x=[]): x.append(1)\n")
    _run(["check", str(tmp_path), "--json"])
    base_env = json.loads(capsys.readouterr().out)
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base_env), encoding="utf-8")

    (tmp_path / "a.py").write_text("def f(x=[]): x.append(1)\ndef g(y={}): pass\n")
    _run(["check", str(tmp_path), "--json"])
    head_env = json.loads(capsys.readouterr().out)
    head_path = tmp_path / "head.json"
    head_path.write_text(json.dumps(head_env), encoding="utf-8")

    rc = _run(["diff", str(base_path), str(head_path), "--format", "markdown"])
    md = capsys.readouterr().out.lower()
    assert rc == 0
    assert "added" in md or "resolved" in md
