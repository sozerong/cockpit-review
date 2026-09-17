"""risk.error-masking v2."""
from cockpit.analyzers.error_masking import ErrorMasking


def test_bare_except_pass_is_warn(make_repo, run_analyzer):
    root = make_repo({"a.py": b"""
def a():
    try:
        risky()
    except:
        pass
"""})
    findings = run_analyzer(ErrorMasking(), root)
    assert len(findings) == 1
    assert findings[0].analyzer_id == "risk.error-masking"
    assert findings[0].severity == "warn"
    assert findings[0].evidence["kind"] == "bare-except"


def test_broad_exception_pass_is_warn(make_repo, run_analyzer):
    root = make_repo({"a.py": b"""
def a():
    try:
        risky()
    except Exception:
        pass
"""})
    findings = run_analyzer(ErrorMasking(), root)
    assert len(findings) == 1
    assert findings[0].severity == "warn"
    assert findings[0].evidence["kind"] == "broad-except"


def test_specific_exception_pass_is_info(make_repo, run_analyzer):
    root = make_repo({"a.py": b"""
def a():
    try:
        risky()
    except ValueError:
        pass
"""})
    findings = run_analyzer(ErrorMasking(), root)
    assert len(findings) == 1
    assert findings[0].severity == "info"
    assert findings[0].evidence["kind"] == "specific-except"


def test_except_with_body_is_clean(make_repo, run_analyzer):
    root = make_repo({"a.py": b"""
def a():
    try:
        risky()
    except Exception as e:
        log(e)
"""})
    assert run_analyzer(ErrorMasking(), root) == []


def test_tuple_with_broad_flags_broad(make_repo, run_analyzer):
    root = make_repo({"a.py": b"""
def a():
    try:
        risky()
    except (Exception, OSError):
        pass
"""})
    findings = run_analyzer(ErrorMasking(), root)
    assert len(findings) == 1
    assert findings[0].evidence["kind"] == "broad-except"
    assert findings[0].severity == "warn"


def test_tests_dir_downgraded_to_info(make_repo, run_analyzer):
    """Non-source paths get sev=info even for broad-except."""
    root = make_repo({"tests/test_x.py": b"""
def h():
    try:
        risky()
    except Exception:
        pass
"""})
    findings = run_analyzer(ErrorMasking(), root)
    assert len(findings) == 1
    assert findings[0].severity == "info"
