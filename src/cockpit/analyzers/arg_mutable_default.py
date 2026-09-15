"""arg.mutable-default — mutable default argument.

Python evaluates default arguments once at function-definition time, so
`def f(x=[]):` shares one list across every call. State leaks between
invocations — the classic gotcha.

v1 flags four shapes: `x=[]`, `x={}`, `x=set()`, `x=list()`/`x=dict()`.
Deterministic single AST shape. Tuples are immutable; `x=None` with an
in-body assignment is the canonical fix and never a finding here."""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes


_QUERY = "(default_parameter) @dp"
_MUTABLE_CALLS = frozenset({"list", "dict", "set"})


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


class ArgMutableDefault:
    id = "arg.mutable-default"
    version = "1"

    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
        from tree_sitter import QueryCursor
        _, q = _query()
        out: list[Finding] = []
        for fc in cs.files:
            if fc.status == "deleted" or fc.path not in indices:
                continue
            src = normalize_bytes(fc.absolute.read_bytes())
            tree = _parser().parse(src)
            for _, caps in QueryCursor(q).matches(tree.root_node):
                dp = caps["dp"][0]
                hit = _classify(dp, src)
                if hit is None:
                    continue
                kind, param, snippet = hit
                start = dp.start_point[0] + 1
                end = dp.end_point[0] + 1
                out.append(Finding(
                    analyzer_id=self.id, analyzer_version=self.version,
                    severity="warn", file=fc.path, span=(start, end),
                    symbol=param,
                    message=f"mutable default `{param}={snippet}` is shared across calls",
                    evidence={"kind": kind, "param": param, "snippet": snippet},
                ))
        return out


def _classify(dp: Any, src: bytes) -> tuple[str, str, str] | None:
    """Return (kind, param_name, snippet) if the default is mutable, else None."""
    param = None
    value = None
    seen_eq = False
    for c in dp.children:
        if not seen_eq and c.type == "identifier":
            param = c.text.decode("utf-8", "replace")
        elif c.type == "=":
            seen_eq = True
        elif seen_eq and c.is_named:
            value = c
            break
    if value is None or param is None:
        return None
    if value.type == "list":
        return "list-literal", param, "[]"
    if value.type == "dictionary":
        return "dict-literal", param, "{}"
    if value.type == "set":
        return "set-literal", param, src[value.start_byte:value.end_byte].decode("utf-8", "replace")
    if value.type == "call":
        fn = value.children[0] if value.children else None
        if fn is not None and fn.type == "identifier":
            name = fn.text.decode("utf-8", "replace")
            if name in _MUTABLE_CALLS:
                return f"{name}-call", param, f"{name}()"
    return None


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    src = b"""\
def a(x=[]):
    pass

def b(x=1, y={}):
    pass

def c(x=set()):
    pass

def d(x=list()):
    pass

def e(x=dict()):
    pass

def f(x=None):
    pass

def g(x=(1, 2)):
    pass

def h(x="literal"):
    pass

def i(x=frozenset()):
    pass

def j(x={1, 2}):
    pass
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "t.py").write_bytes(src)
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = ArgMutableDefault().analyze(cs, indices)
        kinds = sorted(f.evidence["kind"] for f in findings)
        assert kinds == [
            "dict-call", "dict-literal",
            "list-call", "list-literal",
            "set-call", "set-literal",
        ], kinds
        assert all(f.severity == "warn" for f in findings)
        print("arg-mutable-default v1 ok")


if __name__ == "__main__":
    demo()
