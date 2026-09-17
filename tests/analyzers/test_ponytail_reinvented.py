"""ponytail.reinvented v1 — precision-focused stdlib reinvention detection."""
from __future__ import annotations

import pytest

from cockpit.analyzers.ponytail_reinvented import PonytailReinvented


def _run(make_repo, src: bytes) -> list:
    from cockpit.changeset import full_scan
    from cockpit.indexer import index_file
    repo = make_repo({"t.py": src})
    cs = full_scan(repo)
    indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
    return PonytailReinvented().analyze(cs, indices)


# ── manual sum ────────────────────────────────────────────────────────

def test_flags_manual_sum(make_repo):
    findings = _run(make_repo, b"""
def f(xs):
    total = 0
    for x in xs:
        total += x
    return total
""")
    assert len(findings) == 1
    assert findings[0].evidence["kind"] == "sum"
    assert "sum(xs)" in findings[0].evidence["replacement"]
    assert findings[0].severity == "info"


def test_does_not_flag_nonzero_seed(make_repo):
    findings = _run(make_repo, b"""
def f(xs):
    total = 5
    for x in xs:
        total += x
    return total
""")
    assert findings == []


def test_does_not_flag_expression_body(make_repo):
    """`total += x.value` is not a literal sum(xs) reinvention."""
    findings = _run(make_repo, b"""
def f(xs):
    total = 0
    for x in xs:
        total += x.value
    return total
""")
    assert findings == []


def test_does_not_flag_multi_stmt_body(make_repo):
    """Any side-effect in the loop body kills the pattern."""
    findings = _run(make_repo, b"""
def f(xs):
    total = 0
    for x in xs:
        print(x)
        total += x
    return total
""")
    assert findings == []


def test_does_not_flag_when_seed_not_immediately_before(make_repo):
    findings = _run(make_repo, b"""
def f(xs):
    total = 0
    print("noise")
    for x in xs:
        total += x
    return total
""")
    assert findings == []


# ── manual max ────────────────────────────────────────────────────────

def test_flags_manual_max(make_repo):
    findings = _run(make_repo, b"""
def f(xs):
    m = xs[0]
    for x in xs:
        if x > m:
            m = x
    return m
""")
    assert len(findings) == 1
    assert findings[0].evidence["kind"] == "max"
    assert "max(xs)" in findings[0].evidence["replacement"]


def test_does_not_flag_max_over_different_iterable(make_repo):
    """m = ys[0] but for x in xs — not a canonical max reinvention."""
    findings = _run(make_repo, b"""
def f(xs, ys):
    m = ys[0]
    for x in xs:
        if x > m:
            m = x
    return m
""")
    assert findings == []


def test_does_not_flag_max_with_extra_statement(make_repo):
    findings = _run(make_repo, b"""
def f(xs):
    m = xs[0]
    for x in xs:
        if x > m:
            m = x
            log(x)
    return m
""")
    assert findings == []


# ── noise: real accumulators that shouldn't be flagged ────────────────

def test_does_not_flag_reduce_style(make_repo):
    """Multiplicative accumulator has a valid sum-like shape but the
    seed is 1, not 0 — should NOT be flagged as sum reinvention."""
    findings = _run(make_repo, b"""
def f(xs):
    product = 1
    for x in xs:
        product += x
    return product
""")
    assert findings == []


def test_evidence_span_covers_both_statements(make_repo):
    """Finding span should stretch from the seed line to the for-end,
    so the user sees the whole pattern in evidence."""
    findings = _run(make_repo, b"""
def f(xs):
    total = 0
    for x in xs:
        total += x
    return total
""")
    assert len(findings) == 1
    start, end = findings[0].span
    # seed on L3, for on L4, body L5 → span [3,5] end-inclusive.
    assert start == 3
    assert end == 5
