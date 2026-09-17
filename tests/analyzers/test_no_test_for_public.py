"""test.no-test-for-public-symbol v1."""
from cockpit.analyzers.no_test_for_public import NoTestForPublic


def test_untested_public_symbol_fires(make_repo, run_analyzer):
    root = make_repo({
        "widget.py": (
            "def tested_helper(): return 1\n\n"
            "def orphan_helper(): return 2\n\n"
            "class Widget:\n    def spin(self): return 3\n\n"
            "class OrphanWidget:\n    pass\n"
        ),
        "test_widget.py": (
            "from widget import tested_helper, Widget\n"
            "def test_things():\n"
            "    assert tested_helper() == 1\n"
            "    assert Widget().spin() == 3\n"
        ),
    })
    findings = run_analyzer(NoTestForPublic(), root)
    names = sorted(f.symbol for f in findings)
    assert names == ["OrphanWidget", "orphan_helper"]
    assert findings[0].analyzer_id == "test.no-test-for-public-symbol"
    assert findings[0].severity == "info"


def test_private_symbol_skipped(make_repo, run_analyzer):
    """Names starting with `_` are private → never flagged."""
    root = make_repo({
        "widget.py": "def _private(): pass\n",
        "test_widget.py": "def test_x(): assert True\n",
    })
    assert run_analyzer(NoTestForPublic(), root) == []


def test_matching_test_reference_is_clean(make_repo, run_analyzer):
    """Every public symbol referenced in the test file — no findings."""
    root = make_repo({
        "widget.py": "def helper(): return 1\n",
        "test_widget.py": "from widget import helper\ndef test_x(): assert helper() == 1\n",
    })
    assert run_analyzer(NoTestForPublic(), root) == []


def test_no_corresponding_test_file_skipped(make_repo, run_analyzer):
    """No test_<name>.py at all → different problem, don't flag."""
    root = make_repo({
        "widget.py": "def helper(): return 1\n",
    })
    assert run_analyzer(NoTestForPublic(), root) == []
