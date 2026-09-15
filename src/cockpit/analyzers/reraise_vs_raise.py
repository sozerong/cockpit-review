"""except.reraise-vs-raise — `raise e` in `except X as e:` drops traceback.

`raise` alone re-raises the current exception with its original traceback
intact. `raise e` starts a new raise chain and truncates the traceback to
the re-raise site — the original failure point is lost from the stack.

v1: flag `except <anything> as <alias>: ... raise <alias>` where the
identifier raised is the alias. Deterministic, single AST shape."""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes


_QUERY = "(except_clause) @clause"


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


class ReraiseVsRaise:
    id = "except.reraise-vs-raise"
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
                clause = caps["clause"][0]
                hit = _find_reraise(clause, src)
                if hit is None:
                    continue
                raise_node, alias = hit
                start = raise_node.start_point[0] + 1
                end = raise_node.end_point[0] + 1
                out.append(Finding(
                    analyzer_id=self.id, analyzer_version=self.version,
                    severity="warn", file=fc.path, span=(start, end),
                    symbol=None,
                    message=f"`raise {alias}` truncates traceback; use bare `raise`",
                    evidence={
                        "alias": alias,
                        "snippet": src[raise_node.start_byte:raise_node.end_byte]
                            .decode("utf-8", "replace"),
                    },
                ))
        return out


def _find_reraise(clause: Any, src: bytes) -> tuple[Any, str] | None:
    """Return (raise_node, alias_name) if the clause is `except ... as X: raise X`."""
    alias = _as_alias(clause)
    if alias is None:
        return None
    body = next((c for c in clause.children if c.type == "block"), None)
    if body is None:
        return None
    # Walk the body's raise statements at any depth (a `raise e` inside an if
    # is still a traceback truncation).
    stack = list(body.children)
    while stack:
        n = stack.pop()
        if n.type == "raise_statement":
            named = [c for c in n.children if c.is_named]
            # `raise X` — single identifier target, no `from`, no chain.
            if len(named) == 1 and named[0].type == "identifier":
                if named[0].text.decode("utf-8", "replace") == alias:
                    return n, alias
        stack.extend(n.children)
    return None


def _as_alias(clause: Any) -> str | None:
    """Return the identifier bound by `except ... as X`, or None.
    tree-sitter-python nests it: except_clause > as_pattern > as_pattern_target > identifier."""
    for c in clause.children:
        if c.type != "as_pattern":
            continue
        for target in c.children:
            if target.type == "as_pattern_target":
                for ident in target.children:
                    if ident.type == "identifier":
                        return ident.text.decode("utf-8", "replace")
    return None


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    src = b"""\
def a():
    try:
        risky()
    except Exception as e:
        raise e

def b():
    try:
        risky()
    except Exception as e:
        raise

def c():
    try:
        risky()
    except Exception as e:
        raise RuntimeError("wrapped") from e

def d():
    try:
        risky()
    except Exception as e:
        if debug:
            raise e

def e():
    try:
        risky()
    except Exception:
        raise
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "t.py").write_bytes(src)
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = ReraiseVsRaise().analyze(cs, indices)
        # Expect hits on fn `a` and fn `d` only.
        assert len(findings) == 2, findings
        assert all(f.severity == "warn" for f in findings)
        assert all(f.evidence["alias"] == "e" for f in findings)
        print("reraise-vs-raise v1 ok")


if __name__ == "__main__":
    demo()
