"""test.assertion-free — test_* functions with no assertion of any kind.

Detects: `assert` statement, `self.assert*(...)`, `self.fail(...)`,
pytest.raises context, unittest assert helpers via any receiver.

**Severity: info** — P0 pilot (100-row label) showed ~4% actionable rate.
Dominant fp: assertions living in helper wrappers (`self.invokeBlack(exit_code=1)`,
`check_solver_result(...)`) that this analyzer can't cross into. Kept as info
so the signal surfaces for reviewers without triggering CI failures until a
smarter cross-helper detection lands (BRIEF §14 M4+)."""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes


# Test-file heuristic tightened for v2: match by filename convention only
# (test_*.py / *_test.py). The "any file under tests/" rule from v1 pulled in
# fixture data — black/tests/data/cases/*.py is a formatter regression corpus,
# not test suites. Filename convention is the reliable signal.
def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if not name.endswith(".py"):
        return False
    if name.startswith("test_") or name.endswith("_test.py"):
        parts = path.split("/")
        # Still guard against fixture directories that happen to hold test_-named files.
        if "data" in parts or "fixtures" in parts:
            return False
        return True
    return False


_QUERY = """
(function_definition name: (identifier) @name) @fn
"""


@lru_cache(maxsize=1)
def _query() -> tuple[Any, Any]:
    import tree_sitter_python
    from tree_sitter import Language, Query
    lang = Language(tree_sitter_python.language())
    return lang, Query(lang, _QUERY)


@lru_cache(maxsize=1)
def _parser() -> Any:
    from tree_sitter import Parser
    lang, _ = _query()
    return Parser(lang)


def _has_assertion(node: Any) -> bool:
    """Walk subtree; return True on first assertion-like construct."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "assert_statement":
            return True
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is not None:
                text = fn.text.decode("utf-8", "replace")
                # any *.assert*, *.fail, pytest.raises, pytest.warns
                tail = text.rsplit(".", 1)[-1]
                if tail.startswith("assert") or tail == "fail" \
                        or text.endswith("pytest.raises") \
                        or text.endswith("pytest.warns"):
                    return True
        stack.extend(n.children)
    return False


class AssertionFree:
    id = "test.assertion-free"
    # v1: match "any file under tests/". v2: filename-only + fixtures exclude.
    version = "2"

    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
        from tree_sitter import QueryCursor
        _, q = _query()
        out: list[Finding] = []
        for fc in cs.files:
            if fc.status == "deleted" or fc.path not in indices:
                continue
            if not _is_test_file(fc.path):
                continue
            src = normalize_bytes(fc.absolute.read_bytes())
            tree = _parser().parse(src)
            for _, caps in QueryCursor(q).matches(tree.root_node):
                fn = caps["fn"][0]
                name = caps["name"][0].text.decode("utf-8", "replace")
                if not name.startswith("test_"):
                    continue
                if _has_assertion(fn):
                    continue
                out.append(Finding(
                    analyzer_id=self.id, analyzer_version=self.version,
                    severity="info", file=fc.path,
                    span=(fn.start_point[0] + 1, fn.end_point[0] + 1),
                    symbol=name,
                    message=f"test `{name}` has no assertion",
                    evidence={"function": name},
                ))
        return out


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    src = b"""\
def test_empty():
    x = 1 + 1

def test_asserts():
    assert 1 + 1 == 2

def test_unittest(self):
    self.assertEqual(1, 1)

def test_pytest_raises():
    import pytest
    with pytest.raises(ValueError):
        int('x')

def helper():
    pass
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "test_thing.py").write_bytes(src)
        cs = full_scan(root)
        from ..indexer import index_file
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = AssertionFree().analyze(cs, indices)
        names = sorted(f.symbol for f in findings)
        assert names == ["test_empty"], names
        print("assertion-free ok", names)


if __name__ == "__main__":
    demo()
