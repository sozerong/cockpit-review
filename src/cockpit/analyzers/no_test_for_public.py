"""test.no-test-for-public-symbol — public symbol without a matching test.

BRIEF §5 test.authenticity 축. src의 public function/class 중, 대응 test 파일에서
이름이 언급조차 안 되는 것을 flag.

로직 (v1):
1. src 파일마다 top-level public symbol (leading `_` 없음) 수집
2. 대응 test 파일 찾기 (test_<basename>.py — shared-prefix + shortest-path)
3. test 파일 없으면 skip (미완 코드가 아니라 "테스트 없음" 상태 — 별개 문제)
4. test 파일 소스에 심볼 이름이 whole-word로 등장하지 않으면 flag on src symbol

severity: info (커버리지 힌트, 버그 아님).

이름 검색은 단순 정규식이라 import alias, 문자열 안 언급 등 오탐 있을 수 있음.
mocks-target v1이 SUT를 놓친 것보다는 훨씬 안전한 판정 (부재 확인은 존재 확인보다 쉽다).
"""
from __future__ import annotations
import re
from pathlib import PurePosixPath

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes
from ._paths import is_non_source_path


def _corresponding_test_paths(src_path: str, all_paths: set[str]) -> list[str]:
    """Find all `test_<basename>` files anywhere in the repo.
    Multiple matches possible (unit + integration + property tests)."""
    name = PurePosixPath(src_path).name
    if name == "__init__.py" or name.startswith("_"):
        return []
    expected = "test_" + name
    return sorted(p for p in all_paths
                  if PurePosixPath(p).name == expected and p != src_path)


def _public_top_level(idx: FileIndex) -> list[tuple[str, int]]:
    """Return [(name, span_start)] for top-level function/class with public name.
    FileIndex 심볼은 depth 정보 없지만, method(kind='method')는 제외돼서 top-level
    approximation으로 충분."""
    out = []
    for s in idx.symbols:
        if s.kind not in ("function", "class"):
            continue
        if s.name.startswith("_"):
            continue
        out.append((s.name, s.span[0]))
    return out


class NoTestForPublic:
    id = "test.no-test-for-public-symbol"
    version = "1"

    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
        all_paths = set(indices.keys())
        out: list[Finding] = []

        for fc in cs.files:
            if fc.status == "deleted" or fc.path not in indices:
                continue
            # Only scan src files — never flag test/doc/example symbols.
            if is_non_source_path(fc.path):
                continue
            idx = indices[fc.path]
            publics = _public_top_level(idx)
            if not publics:
                continue

            test_paths = _corresponding_test_paths(fc.path, all_paths)
            if not test_paths:
                # No test file for this src at all — different problem (missing
                # test suite, not missing coverage). Don't spam.
                continue

            # Concatenate the source text of every corresponding test file.
            test_blob = ""
            for tp in test_paths:
                try:
                    test_blob += normalize_bytes(
                        (fc.absolute.parent.parent /
                         # We only have absolute path for fc; use the change-set
                         # entry for the test file if available. Fallback: repo path.
                         "").read_bytes()
                    ).decode("utf-8", "replace")
                except Exception:
                    pass
            # Simpler: look up absolute path from cs.files
            test_blob = _load_tests(cs, test_paths)

            for name, line in publics:
                if not re.search(rf"\b{re.escape(name)}\b", test_blob):
                    out.append(Finding(
                        analyzer_id=self.id, analyzer_version=self.version,
                        severity="info", file=fc.path,
                        span=(line, line), symbol=name,
                        message=f"public `{name}` never referenced in {test_paths[0]}",
                        evidence={"test_files": test_paths},
                    ))
        return out


def _load_tests(cs: ChangeSet, paths: list[str]) -> str:
    by_rel = {fc.path: fc.absolute for fc in cs.files}
    blob = ""
    for p in paths:
        abs_p = by_rel.get(p)
        if abs_p is None:
            continue
        try:
            blob += normalize_bytes(abs_p.read_bytes()).decode("utf-8", "replace")
            blob += "\n"
        except Exception:
            pass
    return blob


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "widget.py").write_text(
            "def tested_helper(): return 1\n\n"
            "def orphan_helper(): return 2\n\n"
            "class Widget:\n    def spin(self): return 3\n\n"
            "class OrphanWidget:\n    pass\n\n"
            "def _private(): pass\n"
        )
        (root / "test_widget.py").write_text(
            "from widget import tested_helper, Widget\n"
            "def test_things():\n"
            "    assert tested_helper() == 1\n"
            "    assert Widget().spin() == 3\n"
        )
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = NoTestForPublic().analyze(cs, indices)
        names = sorted(f.symbol for f in findings)
        # tested_helper and Widget are referenced -> not flagged
        # _private is private -> skipped
        # orphan_helper and OrphanWidget -> flagged
        assert names == ["OrphanWidget", "orphan_helper"], names
        print("no-test-for-public ok", names)


if __name__ == "__main__":
    demo()
