"""Diff receipt — machine contract between two scan envelopes."""
from cockpit.diff import compute_diff, format_markdown, RECEIPT_SCHEMA


def _f(id, sev="warn", file="a.py", span=(1, 2), analyzer="dup.block", version="5",
       msg="msg"):
    return {
        "id": id, "analyzer_id": analyzer, "analyzer_version": version,
        "severity": sev, "file": file, "span": list(span),
        "symbol": None, "message": msg, "evidence": {},
    }


def _env(*findings):
    return {"schema": 1, "repo": "x", "generated_at": "t", "findings": list(findings)}


def test_empty_diff_no_changes():
    receipt = compute_diff(_env(), _env())
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["summary"]["stable"] == 0
    assert receipt["changes"] == {"added": [], "resolved": [], "moved": []}


def test_added_finding():
    r = compute_diff(_env(), _env(_f("a")))
    assert len(r["changes"]["added"]) == 1
    assert r["summary"]["added"]["warn"] == 1


def test_resolved_finding():
    r = compute_diff(_env(_f("a")), _env())
    assert len(r["changes"]["resolved"]) == 1
    assert r["summary"]["resolved"]["warn"] == 1


def test_stable_finding_not_reported():
    r = compute_diff(_env(_f("a")), _env(_f("a")))
    assert r["changes"] == {"added": [], "resolved": [], "moved": []}
    assert r["summary"]["stable"] == 1


def test_moved_finding():
    r = compute_diff(_env(_f("a", span=(10, 12))), _env(_f("a", span=(30, 32))))
    assert len(r["changes"]["moved"]) == 1
    assert r["summary"]["moved"]["warn"] == 1
    assert r["summary"]["stable"] == 0  # moved doesn't count as stable
    mv = r["changes"]["moved"][0]
    assert mv["from"]["span"] == [10, 12]
    assert mv["to"]["span"] == [30, 32]


def test_severity_split_in_summary():
    r = compute_diff(
        _env(),
        _env(_f("a", sev="block"), _f("b", sev="warn"), _f("c", sev="info")),
    )
    assert r["summary"]["added"] == {"block": 1, "warn": 1, "info": 1}


def test_markdown_no_change_message():
    md = format_markdown(compute_diff(_env(), _env()))
    assert "no meaningful change" in md


def test_markdown_hides_info_only_findings():
    """info findings never surface in the PR comment — CI never fails on them."""
    r = compute_diff(_env(), _env(_f("a", sev="info")))
    md = format_markdown(r)
    assert "no meaningful change" in md  # info-only counts as no-change for PR


def test_markdown_shows_added_and_resolved():
    r = compute_diff(_env(_f("gone")), _env(_f("new")))
    md = format_markdown(r)
    assert "+1 added" in md
    assert "-1 resolved" in md
    assert "### + added" in md
    assert "### - resolved" in md


def test_markdown_truncates_long_lists():
    """Ensure a PR comment stays readable when hundreds of findings change."""
    heads = [_f(f"h{i}") for i in range(25)]
    md = format_markdown(compute_diff(_env(), _env(*heads)), max_rows_per_kind=5)
    assert "and 20 more" in md


def test_moved_shows_previous_location():
    r = compute_diff(_env(_f("a", span=(10, 12))), _env(_f("a", span=(30, 32))))
    md = format_markdown(r)
    assert "was `a.py:10`" in md
