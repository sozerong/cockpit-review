"""except.reraise-vs-raise v1."""
from cockpit.analyzers.reraise_vs_raise import ReraiseVsRaise


def test_aliased_reraise_fires(make_repo, run_analyzer):
    root = make_repo({"t.py": b"""
def a():
    try:
        risky()
    except Exception as e:
        raise e
"""})
    findings = run_analyzer(ReraiseVsRaise(), root)
    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert findings[0].evidence["alias"] == "e"


def test_bare_raise_is_clean(make_repo, run_analyzer):
    root = make_repo({"t.py": b"""
def a():
    try:
        risky()
    except Exception as e:
        raise
"""})
    assert run_analyzer(ReraiseVsRaise(), root) == []


def test_raise_from_is_clean(make_repo, run_analyzer):
    """`raise X from e` is an explicit chain — traceback preserved via __cause__."""
    root = make_repo({"t.py": b"""
def a():
    try:
        risky()
    except Exception as e:
        raise RuntimeError("wrapped") from e
"""})
    assert run_analyzer(ReraiseVsRaise(), root) == []


def test_nested_reraise_still_caught(make_repo, run_analyzer):
    root = make_repo({"t.py": b"""
def a():
    try:
        risky()
    except Exception as e:
        if debug:
            raise e
        return None
"""})
    findings = run_analyzer(ReraiseVsRaise(), root)
    assert len(findings) == 1


def test_no_alias_no_finding(make_repo, run_analyzer):
    """`except Exception:` without `as` cannot be a re-raise-alias pattern."""
    root = make_repo({"t.py": b"""
def a():
    try:
        risky()
    except Exception:
        cleanup()
        raise
"""})
    assert run_analyzer(ReraiseVsRaise(), root) == []
