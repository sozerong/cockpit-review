"""test.time.sleep — sleeps inside test functions.

`time.sleep(n)` in a test is a flakiness antipattern: the test either waits
too long (slow suite) or too short (heisenbug). Real async code should use
event-driven waits (`asyncio.wait_for`, `pytest-timeout`, fixtures that
signal readiness).

v1 flags:
- `time.sleep(...)` attribute call
- bare `sleep(...)` call when `from time import sleep` reaches this file
  (checked as: any `from time import ...` with `sleep` in the imported names)

Scope: functions whose name matches `^test_` inside a test file (same
filename heuristic as test.assertion-free v2).

Severity: `warn`. Legitimate cases (rate-limit tests, timing calibration)
exist — see BRIEF §13.5 stop-criterion policy for the label pass."""
from __future__ import annotations
from functools import lru_cache
import re
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes
from .assertion_free import _is_test_file


_QUERY = "(function_definition name: (identifier) @name) @fn"


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


class TestTimeSleep:
    id = "test.time.sleep"
    version = "1"

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
            has_bare_sleep = _imports_bare_sleep(tree.root_node, src)
            for _, caps in QueryCursor(q).matches(tree.root_node):
                name_node = caps["name"][0]
                if not name_node.text.decode("utf-8", "replace").startswith("test_"):
                    continue
                fn_node = caps["fn"][0]
                for sleep_call in _find_sleep_calls(fn_node, has_bare_sleep):
                    call_node, kind = sleep_call
                    start = call_node.start_point[0] + 1
                    end = call_node.end_point[0] + 1
                    snippet = src[call_node.start_byte:call_node.end_byte]\
                        .decode("utf-8", "replace")
                    out.append(Finding(
                        analyzer_id=self.id, analyzer_version=self.version,
                        severity="warn", file=fc.path, span=(start, end),
                        symbol=name_node.text.decode("utf-8", "replace"),
                        message=f"`{snippet}` inside test - flaky signal",
                        evidence={"kind": kind, "snippet": snippet},
                    ))
        return out


_FROM_TIME_IMPORT = re.compile(rb"^\s*from\s+time\s+import\s+([^\n]+)", re.M)


def _imports_bare_sleep(root: Any, src: bytes) -> bool:
    """True if the module has `from time import ... sleep ...` (any variant)."""
    # ponytail: regex over source is enough — this catches "from time import sleep",
    # "from time import sleep, monotonic", and parenthesised multiline imports well
    # enough that the false-negative rate on real code is negligible.
    for m in _FROM_TIME_IMPORT.finditer(src):
        names = m.group(1).decode("utf-8", "replace")
        for tok in re.split(r"[\s,()]+", names):
            if tok.strip() == "sleep":
                return True
    return False


def _find_sleep_calls(fn_node: Any, has_bare_sleep: bool):
    """Yield (call_node, kind) for every sleep call reachable inside fn body."""
    stack = list(fn_node.children)
    while stack:
        n = stack.pop()
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is not None:
                text = fn.text.decode("utf-8", "replace")
                if text == "time.sleep":
                    yield n, "time.sleep"
                elif has_bare_sleep and text == "sleep":
                    yield n, "sleep"
        stack.extend(n.children)


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    src = b"""\
import time
from time import sleep, monotonic

def test_a():
    time.sleep(1)
    assert True

def test_b():
    sleep(0.1)

def helper():
    time.sleep(2)  # not a test - no finding

def test_c():
    assert 1 + 1 == 2

def test_d():
    if slow_env:
        time.sleep(5)  # nested still hits

"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "test_x.py").write_bytes(src)
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = TestTimeSleep().analyze(cs, indices)
        # Expect: test_a (time.sleep), test_b (bare sleep), test_d (nested time.sleep).
        assert len(findings) == 3, [f.evidence for f in findings]
        syms = sorted(f.symbol for f in findings)
        assert syms == ["test_a", "test_b", "test_d"], syms
        kinds = sorted(f.evidence["kind"] for f in findings)
        assert kinds == ["sleep", "time.sleep", "time.sleep"], kinds

    # Non-test file: no findings even with time.sleep in test_-shaped fn.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "app.py").write_bytes(
            b"import time\ndef test_ish():\n    time.sleep(1)\n"
        )
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = TestTimeSleep().analyze(cs, indices)
        assert findings == [], findings
    print("test-time-sleep v1 ok")


if __name__ == "__main__":
    demo()
