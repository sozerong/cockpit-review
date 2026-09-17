"""ponytail.reinvented — you reinvented a stdlib primitive.

The user's own idea: "difficult custom code, turns out a library had it in
three lines." Well-defined, high-confidence local patterns only — this
analyzer would rather miss a re-invention than false-positive on a real
custom accumulator.

v1 patterns (both severity=info; they're suggestions, not bugs):

1. **manual sum**:
       total = 0
       for x in xs:
           total += x
   → `sum(xs)`

2. **manual max via first-element seed**:
       m = xs[0]
       for x in xs:
           if x > m:
               m = x
   → `max(xs)`

Precision-first shape rules for v1:
- The accumulator/seed must be initialized in the statement IMMEDIATELY
  before the `for` (no intervening code).
- The `for` body must be a single-statement block (no side effects).
- The augmenting expression must be the exact loop variable identifier
  (`total += x`, not `total += x.value`) so `sum(xs)` is a literal fix.

Extend the pattern list when a real case shows up, not before.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes


_QUERY = "(for_statement) @for"


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


class PonytailReinvented:
    id = "ponytail.reinvented"
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
                for_node = caps["for"][0]
                hit = _match_manual_sum(for_node, src) or _match_manual_max(for_node, src)
                if hit is None:
                    continue
                kind, iter_text, replacement = hit
                start = _prev_stmt(for_node).start_point[0] + 1
                end = for_node.end_point[0] + 1
                out.append(Finding(
                    analyzer_id=self.id, analyzer_version=self.version,
                    severity="info", file=fc.path, span=(start, end),
                    symbol=None,
                    message=f"reinvented {kind}(); try `{replacement}`",
                    evidence={"kind": kind, "replacement": replacement,
                              "iterable": iter_text},
                ))
        return out


# ── pattern matchers ──────────────────────────────────────────────────

def _prev_stmt(for_node: Any) -> Any:
    """The `for`'s previous named sibling (usually the seed assignment)."""
    prev = for_node.prev_named_sibling
    return prev if prev is not None else for_node


def _match_manual_sum(for_node: Any, src: bytes) -> tuple[str, str, str] | None:
    """total = 0 ; for x in xs: total += x  →  sum(xs)"""
    seed = _seed_assignment(for_node)
    if seed is None:
        return None
    accum_name, seed_val = seed
    if seed_val != "0":
        return None
    loop_var, iter_text = _for_head(for_node)
    if loop_var is None:
        return None
    body_stmt = _single_body_stmt(for_node)
    if body_stmt is None or body_stmt.type != "augmented_assignment":
        return None
    op = body_stmt.child_by_field_name("operator")
    if op is None or op.text != b"+=":
        return None
    left = body_stmt.child_by_field_name("left")
    right = body_stmt.child_by_field_name("right")
    if left is None or right is None:
        return None
    if left.type != "identifier" or right.type != "identifier":
        return None
    if left.text.decode("utf-8", "replace") != accum_name:
        return None
    if right.text.decode("utf-8", "replace") != loop_var:
        return None
    return "sum", iter_text, f"{accum_name} = sum({iter_text})"


def _match_manual_max(for_node: Any, src: bytes) -> tuple[str, str, str] | None:
    """m = xs[0] ; for x in xs: if x > m: m = x  →  max(xs)"""
    seed = _seed_assignment(for_node)
    if seed is None:
        return None
    accum_name, seed_val = seed
    # Seed pattern m = xs[0] — value must be `<iterable>[0]`. Check via text.
    if not (seed_val.endswith("[0]") and len(seed_val) > 3):
        return None
    seed_iter = seed_val[:-3]
    loop_var, iter_text = _for_head(for_node)
    if loop_var is None or iter_text != seed_iter:
        return None
    body_stmt = _single_body_stmt(for_node)
    if body_stmt is None or body_stmt.type != "if_statement":
        return None
    # Condition: <loop_var> > <accum_name>
    cond = body_stmt.child_by_field_name("condition")
    if cond is None or cond.type != "comparison_operator":
        return None
    parts = [c for c in cond.children if c.is_named]
    if len(parts) != 2:
        return None
    if parts[0].text.decode("utf-8", "replace") != loop_var:
        return None
    if parts[1].text.decode("utf-8", "replace") != accum_name:
        return None
    ops = [c for c in cond.children if not c.is_named and c.text == b">"]
    if not ops:
        return None
    # Consequence: <accum> = <loop_var> (single statement)
    conseq = body_stmt.child_by_field_name("consequence")
    if conseq is None or conseq.type != "block":
        return None
    stmts = [c for c in conseq.children if c.is_named]
    if len(stmts) != 1 or stmts[0].type != "expression_statement":
        return None
    assign = next((c for c in stmts[0].children if c.type == "assignment"), None)
    if assign is None:
        return None
    al = assign.child_by_field_name("left")
    ar = assign.child_by_field_name("right")
    if al is None or ar is None:
        return None
    if al.text.decode("utf-8", "replace") != accum_name:
        return None
    if ar.text.decode("utf-8", "replace") != loop_var:
        return None
    return "max", iter_text, f"{accum_name} = max({iter_text})"


def _seed_assignment(for_node: Any) -> tuple[str, str] | None:
    """The previous named sibling must be `<name> = <value>`.
    Return (name, value_text) or None."""
    prev = for_node.prev_named_sibling
    if prev is None or prev.type != "expression_statement":
        return None
    assign = next((c for c in prev.children if c.type == "assignment"), None)
    if assign is None:
        return None
    left = assign.child_by_field_name("left")
    right = assign.child_by_field_name("right")
    if left is None or right is None or left.type != "identifier":
        return None
    return (left.text.decode("utf-8", "replace"),
            right.text.decode("utf-8", "replace"))


def _for_head(for_node: Any) -> tuple[str | None, str]:
    """Return (loop_var_name, iterable_text). Loop var must be a bare
    identifier — tuple unpacking not supported in v1."""
    left = for_node.child_by_field_name("left")
    right = for_node.child_by_field_name("right")
    if left is None or right is None:
        return None, ""
    if left.type != "identifier":
        return None, ""
    return (left.text.decode("utf-8", "replace"),
            right.text.decode("utf-8", "replace"))


def _single_body_stmt(for_node: Any) -> Any | None:
    """The body must be exactly one statement (no side effects)."""
    body = for_node.child_by_field_name("body")
    if body is None or body.type != "block":
        return None
    stmts = [c for c in body.children if c.is_named]
    if len(stmts) != 1:
        return None
    inner = stmts[0]
    if inner.type == "expression_statement":
        # Unwrap: `total += x` shows as expression_statement > augmented_assignment.
        named = [c for c in inner.children if c.is_named]
        if len(named) == 1:
            return named[0]
    return inner


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    src = b"""\
def total_a(xs):
    total = 0
    for x in xs:
        total += x
    return total

def max_a(xs):
    m = xs[0]
    for x in xs:
        if x > m:
            m = x
    return m

def total_ok_expression(xs):
    total = 0
    for x in xs:
        total += x.value
    return total

def total_ok_with_sideeffect(xs):
    total = 0
    for x in xs:
        print(x)
        total += x
    return total

def total_ok_seed_far_from_for(xs):
    # `total = 0` is NOT the immediately-preceding statement -> skipped
    total = 0
    print("hello")
    for x in xs:
        total += x
    return total

def total_ok_nonzero_seed(xs):
    # seed value != 0 -> not a canonical `sum` reinvention
    total = 5
    for x in xs:
        total += x
    return total
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "t.py").write_bytes(src)
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = PonytailReinvented().analyze(cs, indices)
        kinds = sorted(f.evidence["kind"] for f in findings)
        assert kinds == ["max", "sum"], kinds
        print("ponytail.reinvented v1 ok", kinds)


if __name__ == "__main__":
    demo()
