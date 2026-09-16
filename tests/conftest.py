"""Shared test helpers.

Ponytail: no factories, no mocking libraries. Just the stdlib and a
small `make_repo` helper — every analyzer test needs a tiny repo, so
build one from a dict of {path: source_bytes}.
"""
from __future__ import annotations
from pathlib import Path

import pytest


@pytest.fixture
def make_repo(tmp_path):
    """Return a callable that writes {path: bytes|str} into tmp_path.

    Example:
        root = make_repo({
            "a.py": b"def f():\\n    pass\\n",
            "tests/test_b.py": "def test_x():\\n    assert True\\n",
        })
    Returns the root Path so tests can pass it to analyzers directly.
    """
    def _write(files: dict[str, bytes | str]) -> Path:
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                content = content.encode("utf-8")
            p.write_bytes(content)
        return tmp_path
    return _write


@pytest.fixture
def run_analyzer():
    """Run a single analyzer against a repo path; return list[Finding]."""
    from cockpit.changeset import full_scan
    from cockpit.indexer import index_file

    def _run(analyzer, repo: Path):
        cs = full_scan(repo)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        return analyzer.analyze(cs, indices)
    return _run
