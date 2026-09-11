"""risk.error-masking — swallowed exceptions.

v1 flagged any empty-body except (pass/...) as warn regardless of exception
type. Labeling (99 samples) showed the only actionable signal is **exception
broadness**: bare `except:` and `except Exception:` catch too much and silently
drop. `except SpecificError: pass` is a legitimate Python pattern (optional
imports, cache misses, cleanup, sentinel).

v2 splits by broadness:
- bare-except / broad-except → warn
- specific-except → info

Path filter: findings in tests/examples/docs → info (same rationale as
dup.block v5)."""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes
from ._paths import is_non_source_path


# "Broad" exception classes: catching these silently is almost always wrong.
# BaseException/Exception hide bugs; SystemExit/KeyboardInterrupt/GeneratorExit
# subclass BaseException so `except BaseException` swallows Ctrl-C, sys.exit,
# and generator cleanup along with everything else.
_BROAD_NAMES = frozenset({"Exception", "BaseException"})


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


class ErrorMasking:
    id = "risk.error-masking"
    # v1: any empty except body flagged warn.
    # v2: split by exception broadness; non-source paths downgraded to info.
    version = "2"

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
                flag = _classify(clause, src)
                if flag is None:
                    continue
                kind, snippet = flag
                start = clause.start_point[0] + 1
                end = clause.end_point[0] + 1
                # Severity: broad exceptions in src/ → warn; specific or
                # non-source paths → info.
                if kind == "specific-except" or is_non_source_path(fc.path):
                    sev = "info"
                else:
                    sev = "warn"
                out.append(Finding(
                    analyzer_id=self.id, analyzer_version=self.version,
                    severity=sev, file=fc.path, span=(start, end),
                    symbol=None,
                    message=f"except clause swallows errors ({kind})",
                    evidence={"kind": kind, "snippet": snippet},
                ))
        return out


def _classify(clause: Any, src: bytes) -> tuple[str, str] | None:
    """Return (kind, snippet) if the clause is a masking pattern, else None.

    kind ∈ {bare-except, broad-except, specific-except}.
    """
    body = None
    type_node = None
    for c in clause.children:
        if c.type == "block":
            body = c
        elif c.is_named:
            type_node = c  # first named non-block child is the exception spec
    body_stmts = [c for c in (body.children if body else []) if c.is_named]
    only_noop = bool(body_stmts) and all(_is_noop(s) for s in body_stmts)
    if not only_noop:
        return None  # body does something (log, re-raise, cleanup) — not masking

    snippet = src[clause.start_byte:clause.end_byte].decode("utf-8", "replace")
    if type_node is None:
        return "bare-except", snippet
    return ("broad-except" if _is_broad_type(type_node) else "specific-except"), snippet


def _is_broad_type(node: Any) -> bool:
    """True if the exception spec catches BaseException/Exception.
    Walks the subtree collecting identifier text; a bare identifier match
    handles `except Exception:`, `except (Exception, ...):`, and
    `except Exception as e:` (the `as` alias is a separate child)."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "identifier":
            if n.text.decode("utf-8", "replace") in _BROAD_NAMES:
                return True
        stack.extend(n.children)
    return False


def _is_noop(stmt: Any) -> bool:
    if stmt.type == "pass_statement":
        return True
    if stmt.type == "expression_statement":
        kids = [c for c in stmt.children if c.is_named]
        return len(kids) == 1 and kids[0].type == "ellipsis"
    return False


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    src = b"""\
def a():
    try:
        risky()
    except:
        pass

def b():
    try:
        risky()
    except ValueError:
        pass

def c():
    try:
        risky()
    except Exception:
        pass

def d():
    try:
        risky()
    except (OSError, ValueError):
        pass

def e():
    try:
        risky()
    except (Exception, OSError):
        pass

def f():
    try:
        risky()
    except BaseException as be:
        pass

def g():
    try:
        risky()
    except Exception as e:
        log(e)
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "t.py").write_bytes(src)
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = ErrorMasking().analyze(cs, indices)
        by_kind = sorted((f.evidence["kind"], f.severity) for f in findings)
        assert by_kind == [
            ("bare-except", "warn"),
            ("broad-except", "warn"),
            ("broad-except", "warn"),
            ("broad-except", "warn"),
            ("specific-except", "info"),
            ("specific-except", "info"),
        ], by_kind
        # Path filter: same clause in tests/ path → info regardless of broadness.
        (root / "tests").mkdir()
        (root / "tests" / "t2.py").write_bytes(
            b"def h():\n    try:\n        risky()\n    except Exception:\n        pass\n"
        )
        cs2 = full_scan(root)
        idx2 = {fc.path: index_file(fc.path, fc.absolute) for fc in cs2.files}
        f2 = ErrorMasking().analyze(cs2, idx2)
        tests_sev = [f.severity for f in f2 if "tests/" in f.file]
        assert all(s == "info" for s in tests_sev), tests_sev
        print("error-masking v2 ok")


if __name__ == "__main__":
    demo()
