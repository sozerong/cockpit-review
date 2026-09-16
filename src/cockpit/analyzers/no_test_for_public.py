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
    Multiple matches possible (unit + integration + property tests).

    Kept for backwards compat & the demo(). Hot-path callers should use
    _build_test_index + _lookup for O(1) per src instead of O(N_paths)."""
    name = PurePosixPath(src_path).name
    if name == "__init__.py" or name.startswith("_"):
        return []
    expected = "test_" + name
    return sorted(p for p in all_paths
                  if PurePosixPath(p).name == expected and p != src_path)


def _build_test_index(all_paths: set[str]) -> dict[str, list[str]]:
    """Bucket paths by basename once, so per-src lookup is O(1) instead of
    O(N_paths). On fastapi this cuts the analyzer's per-scan cost from
    ~120ms (500 srcs × 1138 paths) to ~5ms."""
    idx: dict[str, list[str]] = {}
    for p in all_paths:
        name = PurePosixPath(p).name
        if name.startswith("test_"):
            idx.setdefault(name, []).append(p)
    for lst in idx.values():
        lst.sort()
    return idx


def _lookup_tests(src_path: str, test_index: dict[str, list[str]]) -> list[str]:
    name = PurePosixPath(src_path).name
    if name == "__init__.py" or name.startswith("_"):
        return []
    return [p for p in test_index.get("test_" + name, []) if p != src_path]


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

    def __init__(self) -> None:
        # Per-test-file normalized source blob, keyed by (path, generation).
        # See dup_block.py __init__: monotonic generations avoid the
        # id()-reuse hazard from CPython arena recycling.
        self._test_blob_cache: dict[str, tuple[int, str]] = {}
        # Per-src-file findings, keyed by (src_gen, tuple of test_gens).
        # Rebuild if the src file changed OR any of its corresponding test
        # files changed OR the corresponding-test set itself changed
        # (a new test file matched the src's expected name).
        self._src_cache: dict[str, tuple[int, tuple[int, ...], list[Finding]]] = {}

    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
        all_paths = set(indices.keys())
        test_index = _build_test_index(all_paths)
        cur_src_paths: set[str] = set()
        cur_test_paths: set[str] = set()
        out: list[Finding] = []

        for fc in cs.files:
            if fc.status == "deleted" or fc.path not in indices:
                continue
            if is_non_source_path(fc.path):
                continue
            cur_src_paths.add(fc.path)
            src_idx = indices[fc.path]

            test_paths = _lookup_tests(fc.path, test_index)
            if not test_paths:
                # No test file for this src at all — different problem
                # (missing test suite, not missing coverage). Don't spam.
                self._src_cache.pop(fc.path, None)
                continue

            # Cache key includes every corresponding test file's generation
            # so we know when to bust.
            test_gens = tuple(
                indices[p].generation for p in test_paths if p in indices
            )
            cache_key = (src_idx.generation, test_gens)
            cached = self._src_cache.get(fc.path)
            if cached is not None and (cached[0], cached[1]) == cache_key:
                out.extend(cached[2])
                cur_test_paths.update(test_paths)
                continue

            publics = _public_top_level(src_idx)
            if not publics:
                self._src_cache[fc.path] = (src_idx.generation, test_gens, [])
                continue

            test_blob = self._test_blob(cs, indices, test_paths)
            cur_test_paths.update(test_paths)
            findings: list[Finding] = []
            for name, line in publics:
                if not re.search(rf"\b{re.escape(name)}\b", test_blob):
                    findings.append(Finding(
                        analyzer_id=self.id, analyzer_version=self.version,
                        severity="info", file=fc.path,
                        span=(line, line), symbol=name,
                        message=f"public `{name}` never referenced in {test_paths[0]}",
                        evidence={"test_files": test_paths},
                    ))
            self._src_cache[fc.path] = (src_idx.generation, test_gens, findings)
            out.extend(findings)

        # Prune caches: files no longer present or no longer relevant fall out.
        for p in list(self._src_cache):
            if p not in cur_src_paths:
                del self._src_cache[p]
        for p in list(self._test_blob_cache):
            if p not in cur_test_paths and p not in indices:
                del self._test_blob_cache[p]
        return out

    def _test_blob(
        self, cs: ChangeSet, indices: dict[str, FileIndex], paths: list[str],
    ) -> str:
        """Concatenate normalized source of the corresponding test files.
        Per-file blob cached until its FileIndex identity changes."""
        by_rel = {fc.path: fc.absolute for fc in cs.files}
        parts: list[str] = []
        for p in paths:
            test_idx = indices.get(p)
            if test_idx is None:
                continue
            cached = self._test_blob_cache.get(p)
            if cached is not None and cached[0] == test_idx.generation:
                parts.append(cached[1])
                continue
            abs_p = by_rel.get(p)
            if abs_p is None:
                continue
            try:
                text = normalize_bytes(abs_p.read_bytes()).decode("utf-8", "replace") + "\n"
            except Exception:
                text = ""
            self._test_blob_cache[p] = (test_idx.generation, text)
            parts.append(text)
        return "".join(parts)


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
