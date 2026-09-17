"""test.always-true-assertion v1."""
from cockpit.analyzers.always_true_assertion import AlwaysTrueAssertion


def test_assert_true_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_trivial_bool():
    assert True
"""})
    findings = run_analyzer(AlwaysTrueAssertion(), root)
    assert len(findings) == 1
    assert findings[0].analyzer_id == "test.always-true-assertion"
    assert findings[0].severity == "info"
    assert findings[0].evidence["kind"] == "constant-true"


def test_self_comparison_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_self_cmp():
    x = 5
    assert x == x
"""})
    findings = run_analyzer(AlwaysTrueAssertion(), root)
    assert len(findings) == 1
    assert findings[0].evidence["kind"] == "self-comparison"


def test_isinstance_object_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_isinstance_object():
    assert isinstance("s", object)
"""})
    findings = run_analyzer(AlwaysTrueAssertion(), root)
    assert len(findings) == 1
    assert findings[0].evidence["kind"] == "isinstance-object"


def test_unittest_assertTrue_true_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
class T:
    def test_assert_true(self):
        self.assertTrue(True)
"""})
    findings = run_analyzer(AlwaysTrueAssertion(), root)
    assert len(findings) == 1
    assert findings[0].symbol == "test_assert_true"


def test_real_assertion_is_clean(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
def test_real_assertion():
    x = 1 + 1
    assert x == 2
"""})
    assert run_analyzer(AlwaysTrueAssertion(), root) == []


def test_non_test_file_ignored(make_repo, run_analyzer):
    root = make_repo({"app.py": b"""
def test_trivial_bool():
    assert True
"""})
    assert run_analyzer(AlwaysTrueAssertion(), root) == []
