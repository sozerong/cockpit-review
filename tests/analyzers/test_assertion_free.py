"""test.assertion-free v2."""
from cockpit.analyzers.assertion_free import AssertionFree


def test_empty_test_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_empty():
    x = 1 + 1
"""})
    findings = run_analyzer(AssertionFree(), root)
    assert len(findings) == 1
    assert findings[0].analyzer_id == "test.assertion-free"
    assert findings[0].severity == "info"
    assert findings[0].symbol == "test_empty"


def test_assert_statement_is_clean(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_asserts():
    assert 1 + 1 == 2
"""})
    assert run_analyzer(AssertionFree(), root) == []


def test_unittest_self_assert_is_clean(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_unittest(self):
    self.assertEqual(1, 1)
"""})
    assert run_analyzer(AssertionFree(), root) == []


def test_pytest_raises_is_clean(make_repo, run_analyzer):
    """Common FP: pytest.raises context is a valid assertion — must NOT flag."""
    root = make_repo({"test_x.py": b"""
import pytest

def test_pytest_raises():
    with pytest.raises(ValueError):
        int('x')
"""})
    assert run_analyzer(AssertionFree(), root) == []


def test_non_test_function_ignored(make_repo, run_analyzer):
    """Helper functions in test files are not `test_*` — skip."""
    root = make_repo({"test_x.py": b"""
def helper():
    pass
"""})
    assert run_analyzer(AssertionFree(), root) == []


def test_fixture_dir_ignored(make_repo, run_analyzer):
    """test_-named files inside a fixtures/data dir are corpus, not tests."""
    root = make_repo({"tests/data/test_case.py": b"""
def test_empty():
    x = 1
"""})
    assert run_analyzer(AssertionFree(), root) == []
