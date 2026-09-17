"""test.mocks-target v2 — SUT filter precision tests.

v2 rule: patched symbol S from SUT flagged ONLY when test name is
`test_<S>` or `test_<S>_...` (case-insensitive). This closes the v1
false-positive that flagged every collaborator-mock in dependency tests.
"""
from __future__ import annotations

import pytest

from cockpit.analyzers.mocks_target import MocksTarget, _sut_syms_in_test_name


def _run(make_repo, files: dict) -> list:
    from cockpit.changeset import full_scan
    from cockpit.indexer import index_file
    repo = make_repo(files)
    cs = full_scan(repo)
    indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
    return MocksTarget().analyze(cs, indices)


# ── SUT filter unit tests ─────────────────────────────────────────────

@pytest.mark.parametrize("test_name, syms, expected", [
    # Direct match: test_<sym>
    ("test_compute", {"compute", "helper"}, {"compute"}),
    # Prefix match: test_<sym>_...
    ("test_compute_handles_zero", {"compute", "helper"}, {"compute"}),
    # Case-insensitive: PascalCase SUT, snake_case test name
    ("test_widget_spin", {"Widget"}, {"Widget"}),
    ("test_widget", {"Widget"}, {"Widget"}),
    # No prefix hit: symbol appears mid-name but not at the start → not SUT
    ("test_orchestrator_uses_compute", {"compute"}, set()),
    # Substring but not word-boundary → not SUT
    ("test_computer_science", {"compute"}, set()),
    # Missing test_ prefix → nothing
    ("smoke_compute", {"compute"}, set()),
    # No target syms → empty
    ("test_compute", set(), set()),
])
def test_sut_filter(test_name, syms, expected):
    assert _sut_syms_in_test_name(test_name, syms) == expected


# ── End-to-end analyzer tests ─────────────────────────────────────────

def test_flags_direct_target_mock(make_repo):
    findings = _run(make_repo, {
        "foo.py": b"def compute(x): return x*2\n",
        "tests/test_foo.py": (
            b"from unittest.mock import patch\n"
            b"def test_compute_handles_zero():\n"
            b"    with patch('foo.compute', return_value=99):\n"
            b"        assert True\n"
        ),
    })
    assert len(findings) == 1
    f = findings[0]
    assert f.analyzer_id == "test.mocks-target"
    assert f.severity == "warn"
    assert f.symbol == "test_compute_handles_zero"
    assert "compute" in f.evidence["mocked_symbols"]


def test_flags_patch_object(make_repo):
    findings = _run(make_repo, {
        "foo.py": b"class Widget:\n    def spin(self): return 42\n",
        "tests/test_foo.py": (
            b"from unittest.mock import patch\n"
            b"import foo\n"
            b"def test_widget_spin():\n"
            b"    with patch.object(foo, 'Widget'):\n"
            b"        pass\n"
        ),
    })
    assert len(findings) == 1
    assert findings[0].evidence["mocked_symbols"] == ["Widget"]


def test_does_not_flag_dependency_mock(make_repo):
    """v2 precision fix: mocking a SUT symbol as a *dependency* of a
    different test is not a false claim of coverage."""
    findings = _run(make_repo, {
        "foo.py": b"def compute(x): return x*2\ndef orchestrator(): return compute(3)\n",
        "tests/test_foo.py": (
            b"from unittest.mock import patch\n"
            b"def test_orchestrator_uses_compute():\n"
            b"    with patch('foo.compute', return_value=10):\n"
            b"        assert True\n"
        ),
    })
    assert findings == []


def test_does_not_flag_unrelated_mock(make_repo):
    """Mocking a symbol that isn't in the SUT file at all → never flag."""
    findings = _run(make_repo, {
        "foo.py": b"def compute(x): return x\n",
        "tests/test_foo.py": (
            b"from unittest.mock import patch\n"
            b"def test_compute_ok():\n"
            b"    with patch('other.helper'):\n"
            b"        assert True\n"
        ),
    })
    assert findings == []


def test_ignores_test_files_without_sut(make_repo):
    """No `foo.py` next to `test_foo.py` → skip silently."""
    findings = _run(make_repo, {
        "tests/test_lonely.py": (
            b"from unittest.mock import patch\n"
            b"def test_lonely_something():\n"
            b"    with patch('anywhere.symbol'):\n"
            b"        assert True\n"
        ),
    })
    assert findings == []


def test_mocker_patch_also_caught(make_repo):
    """`mocker.patch(...)` (pytest-mock) uses the same call syntax."""
    findings = _run(make_repo, {
        "foo.py": b"def compute(x): return x\n",
        "tests/test_foo.py": (
            b"def test_compute_edge_case(mocker):\n"
            b"    mocker.patch('foo.compute', return_value=1)\n"
            b"    assert True\n"
        ),
    })
    assert len(findings) == 1
    assert findings[0].evidence["mocked_symbols"] == ["compute"]
