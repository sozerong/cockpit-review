"""arg.mutable-default v1."""
import pytest

from cockpit.analyzers.arg_mutable_default import ArgMutableDefault


@pytest.mark.parametrize("src,expected_kinds", [
    (b"def f(x=[]): pass",           ["list-literal"]),
    (b"def f(x={}): pass",           ["dict-literal"]),
    (b"def f(x={1,2}): pass",        ["set-literal"]),
    (b"def f(x=list()): pass",       ["list-call"]),
    (b"def f(x=dict()): pass",       ["dict-call"]),
    (b"def f(x=set()): pass",        ["set-call"]),
    (b"def f(x=1, y={}): pass",      ["dict-literal"]),
])
def test_flags_mutable_defaults(make_repo, run_analyzer, src, expected_kinds):
    root = make_repo({"t.py": src})
    kinds = sorted(f.evidence["kind"] for f in run_analyzer(ArgMutableDefault(), root))
    assert kinds == expected_kinds


@pytest.mark.parametrize("src", [
    b"def f(x=None): pass",
    b"def f(x=1): pass",
    b"def f(x=(1,2)): pass",       # tuple is immutable
    b"def f(x='literal'): pass",
    b"def f(x=frozenset()): pass",  # frozenset is immutable
])
def test_does_not_flag_immutable_defaults(make_repo, run_analyzer, src):
    root = make_repo({"t.py": src})
    assert run_analyzer(ArgMutableDefault(), root) == []


def test_multi_param_only_flags_the_bad_one(make_repo, run_analyzer):
    root = make_repo({"t.py": b"def f(a, b=None, c=[], d=1): pass"})
    findings = run_analyzer(ArgMutableDefault(), root)
    assert len(findings) == 1
    assert findings[0].evidence["param"] == "c"


def test_severity_is_warn(make_repo, run_analyzer):
    root = make_repo({"t.py": b"def f(x=[]): pass"})
    assert run_analyzer(ArgMutableDefault(), root)[0].severity == "warn"
