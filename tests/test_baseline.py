"""Baseline save / load round-trip."""
from cockpit import baseline as bl
from cockpit.analyzers.arg_mutable_default import ArgMutableDefault
from cockpit.changeset import full_scan
from cockpit.indexer import index_file


def _real_findings(tmp_path):
    (tmp_path / "t.py").write_bytes(b"def f(x=[]): pass\n")
    cs = full_scan(tmp_path)
    idx = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
    return ArgMutableDefault().analyze(cs, idx)


def test_load_missing_baseline_returns_none(tmp_path):
    assert bl.load(tmp_path) is None


def test_roundtrip(tmp_path):
    findings = _real_findings(tmp_path)
    assert len(findings) == 1
    p = bl.save(tmp_path, findings)
    assert p.exists()
    loaded = bl.load(tmp_path)
    assert loaded is not None
    assert findings[0].id in loaded


def test_save_replaces_existing(tmp_path):
    (tmp_path / ".cockpit").mkdir()
    (tmp_path / ".cockpit" / "baseline.json").write_text('{"schema": 1, "ids": ["old"]}')
    bl.save(tmp_path, [])
    loaded = bl.load(tmp_path)
    assert loaded == set()


def test_finding_id_is_stable_across_line_shifts(tmp_path):
    """The whole point of the derived id: adding whitespace above shouldn't
    invalidate the baseline entry."""
    (tmp_path / "t.py").write_bytes(b"def f(x=[]): pass\n")
    a = _real_findings(tmp_path)[0].id

    (tmp_path / "t.py").write_bytes(b"# a comment\n\ndef f(x=[]): pass\n")
    b = _real_findings(tmp_path)[0].id
    assert a == b
