"""dup.block v5."""
from cockpit.analyzers.dup_block import DupBlock


_SHARED = (
    "    total = 0\n"
    "    for item in items:\n"
    "        if item.active:\n"
    "            total += item.value\n"
    "    return total\n"
)


def test_cross_file_duplicate_fires(make_repo, run_analyzer):
    root = make_repo({
        "a.py": f"def sum_a(items):\n{_SHARED}\n",
        "b.py": f"def sum_b(items):\n{_SHARED}\n",
    })
    findings = run_analyzer(DupBlock(), root)
    files = sorted(f.file for f in findings)
    assert files == ["a.py", "b.py"]
    assert findings[0].analyzer_id == "dup.block"


def test_import_stack_not_flagged(make_repo, run_analyzer):
    """Module-level import stacks are not inside function bodies — must not fire."""
    imports = "import os\nimport sys\nimport json\nimport time\nimport re\n"
    root = make_repo({
        "a.py": imports + "x = 1\n",
        "b.py": imports + "y = 2\n",
    })
    assert run_analyzer(DupBlock(), root) == []


def test_single_occurrence_clean(make_repo, run_analyzer):
    root = make_repo({"a.py": f"def sum_a(items):\n{_SHARED}\n"})
    assert run_analyzer(DupBlock(), root) == []


def test_tests_dir_dup_downgraded(make_repo, run_analyzer):
    """Dup in non-source paths → severity info."""
    root = make_repo({
        "tests/test_a.py": f"def helper_a():\n{_SHARED}\n",
        "tests/test_b.py": f"def helper_b():\n{_SHARED}\n",
    })
    findings = run_analyzer(DupBlock(), root)
    assert findings
    assert all(f.severity == "info" for f in findings)
