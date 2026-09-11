"""test.always-true-assertion — assertions that can never fail.

BRIEF §5 test.authenticity 축. Patterns:
- `assert True`, `assert 1`, `assert "x"` (truthy constant)
- `assert x == x` (identifier compared to itself)
- `assert isinstance(x, object)` (always true)
- `self.assertTrue(True)`, `self.assertEqual(x, x)`

Test 파일에 한정 (assertion_free와 동일한 파일 필터).

**Severity: info** — P0 pilot (n=7 findings) showed 6/7 fp: `assert x == x` is
almost always deliberate `__eq__` reflexivity verification, not dead code.
Kept as info: the one real tp caught (`assert b"123", data["name"]` — 2-arg
assert misuse) is genuine, but not enough signal density to warn."""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes
from .assertion_free import _is_test_file


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


# Constants whose truthiness is fixed at parse time.
_TRUTHY_LITERALS = {"true", "1", "-1"}
# Any nonzero int/float literal that appears as an assertion expr is always true.


def _node_text(n: Any) -> str:
    return n.text.decode("utf-8", "replace")


def _is_always_true_expr(expr: Any) -> str | None:
    """Return a kind label if `expr` is trivially always-true, else None.
    Handles the common patterns; conservative for complex expressions."""
    t = _node_text(expr).strip()
    if t.lower() in _TRUTHY_LITERALS:
        return "constant-true"
    # Nonzero int/float literal
    if expr.type == "integer":
        return "constant-true" if t not in ("0", "0x0", "0o0", "0b0") else None
    if expr.type == "float":
        try:
            return "constant-true" if float(t) != 0.0 else None
        except ValueError:
            return None
    # String / bytes literal — truthy unless empty
    if expr.type == "string":
        # Strip quotes and prefix chars to check emptiness
        inner = t
        i = 0
        while i < len(inner) and inner[i] in "rRbBuUfF":
            i += 1
        if i < len(inner) and inner[i] in ("'", '"'):
            q = inner[i]
            if inner[i:i + 3] == q * 3:
                inner = inner[i + 3:-3]
            else:
                inner = inner[i + 1:-1]
        return "constant-true" if inner else None
    # x == x  or  x != x (never)
    if expr.type == "comparison_operator":
        # comparison_operator has children: operand op operand ...
        parts = [c for c in expr.children if c.is_named]
        if len(parts) == 2:
            left, right = parts
            if left.type == "identifier" and right.type == "identifier":
                if _node_text(left) == _node_text(right):
                    return "self-comparison"
    # isinstance(x, object)
    if expr.type == "call":
        fn = expr.child_by_field_name("function")
        args = expr.child_by_field_name("arguments")
        if fn is not None and args is not None and _node_text(fn) == "isinstance":
            arg_children = [c for c in args.children if c.is_named]
            if len(arg_children) == 2 and _node_text(arg_children[1]) == "object":
                return "isinstance-object"
    return None


def _classify_assert_stmt(stmt: Any) -> str | None:
    """`assert <expr>` — return kind if trivially-true, else None."""
    if stmt.type != "assert_statement":
        return None
    # Children: 'assert' keyword, expression, (optional) ',', message
    named = [c for c in stmt.children if c.is_named]
    if not named:
        return None
    return _is_always_true_expr(named[0])


def _classify_assert_call(call: Any) -> str | None:
    """`self.assertTrue(True)`, `self.assertEqual(x, x)` etc."""
    if call.type != "call":
        return None
    fn = call.child_by_field_name("function")
    args = call.child_by_field_name("arguments")
    if fn is None or args is None:
        return None
    tail = _node_text(fn).rsplit(".", 1)[-1]
    args_named = [c for c in args.children if c.is_named]
    if tail in ("assertTrue", "assert_") and len(args_named) >= 1:
        return _is_always_true_expr(args_named[0])
    if tail == "assertFalse" and len(args_named) >= 1:
        # assertFalse(False) / assertFalse(0) — always passes
        first = args_named[0]
        text = _node_text(first).strip().lower()
        if text in ("false", "0", "0.0", '""', "''"):
            return "constant-false"
        return None
    if tail in ("assertEqual", "assertEquals", "assertIs") and len(args_named) >= 2:
        a, b = args_named[0], args_named[1]
        if a.type == "identifier" and b.type == "identifier" and _node_text(a) == _node_text(b):
            return "self-comparison"
    return None


class AlwaysTrueAssertion:
    id = "test.always-true-assertion"
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
            for _, caps in QueryCursor(q).matches(tree.root_node):
                fn_node = caps["fn"][0]
                name = caps["name"][0].text.decode("utf-8", "replace")
                if not name.startswith("test_"):
                    continue
                # Walk the function body for trivial assertions.
                stack = [fn_node]
                seen_lines: set[int] = set()
                while stack:
                    n = stack.pop()
                    kind = _classify_assert_stmt(n) or _classify_assert_call(n)
                    if kind is not None:
                        line = n.start_point[0] + 1
                        if line in seen_lines:
                            continue
                        seen_lines.add(line)
                        out.append(Finding(
                            analyzer_id=self.id, analyzer_version=self.version,
                            severity="info", file=fc.path,
                            span=(line, n.end_point[0] + 1),
                            symbol=name,
                            message=f"assertion in `{name}` is trivially true ({kind})",
                            evidence={"kind": kind, "text": _node_text(n)[:200]},
                        ))
                    stack.extend(n.children)
        return out


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    src = b"""\
def test_trivial_bool():
    assert True

def test_trivial_int():
    assert 1

def test_self_cmp():
    x = 5
    assert x == x

def test_isinstance_object():
    assert isinstance("s", object)

class T:
    def test_assert_true(self):
        self.assertTrue(True)
    def test_assert_equal_self(self):
        y = 1
        self.assertEqual(y, y)

def test_real_assertion():
    x = 1 + 1
    assert x == 2
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "test_x.py").write_bytes(src)
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = AlwaysTrueAssertion().analyze(cs, indices)
        names = sorted({f.symbol for f in findings})
        assert names == [
            "test_assert_equal_self", "test_assert_true", "test_isinstance_object",
            "test_self_cmp", "test_trivial_bool", "test_trivial_int",
        ], names
        print("always-true-assertion ok", names)


if __name__ == "__main__":
    demo()
