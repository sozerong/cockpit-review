"""test.time.sleep v1."""
from cockpit.analyzers.test_time_sleep import TestTimeSleep


def test_time_sleep_inside_test_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
import time

def test_a():
    time.sleep(1)
    assert True
"""})
    findings = run_analyzer(TestTimeSleep(), root)
    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert findings[0].symbol == "test_a"
    assert findings[0].evidence["kind"] == "time.sleep"


def test_bare_sleep_when_imported_fires(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
from time import sleep, monotonic

def test_b():
    sleep(0.1)
"""})
    findings = run_analyzer(TestTimeSleep(), root)
    assert len(findings) == 1
    assert findings[0].evidence["kind"] == "sleep"


def test_bare_sleep_without_import_ignored(make_repo, run_analyzer):
    """`sleep` name might be shadowed / unrelated — don't fire without the import."""
    root = make_repo({"test_x.py": b"""
def sleep(n): return n

def test_c():
    sleep(0.1)
"""})
    assert run_analyzer(TestTimeSleep(), root) == []


def test_non_test_file_ignored(make_repo, run_analyzer):
    root = make_repo({"app.py": b"""
import time

def test_ish():
    time.sleep(1)
"""})
    assert run_analyzer(TestTimeSleep(), root) == []


def test_helper_function_in_test_file_ignored(make_repo, run_analyzer):
    """A non-test_ function inside a test file is a fixture/helper — skip it."""
    root = make_repo({"test_x.py": b"""
import time

def helper():
    time.sleep(2)

def test_a():
    assert True
"""})
    assert run_analyzer(TestTimeSleep(), root) == []


def test_nested_sleep_still_hits(make_repo, run_analyzer):
    root = make_repo({"test_x.py": b"""
import time

def test_a():
    if slow_env:
        time.sleep(5)
"""})
    assert len(run_analyzer(TestTimeSleep(), root)) == 1


def test_fixture_dir_ignored(make_repo, run_analyzer):
    """test_ files under fixtures/ or data/ are corpuses, not tests."""
    root = make_repo({"tests/fixtures/test_case.py": b"""
import time
def test_x():
    time.sleep(1)
"""})
    assert run_analyzer(TestTimeSleep(), root) == []
