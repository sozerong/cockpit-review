"""test.mocks-target — 테스트가 검증 대상 자체를 mock했는가.

BRIEF §5 test.authenticity의 핵심 판정. §13.3 "가장 구현 어렵고 이 파일럿의
병목". §13.5 중단 기준: 관계 판정 정밀도 <0.7이면 지표에서 제외.

로직 (v1):
1. test 파일 → target 파일 매핑 (naming convention)
   `<dir>/test_foo.py`  → same-dir `foo.py` / `../foo.py` / `../src/foo.py` 등
2. target 파일의 top-level 심볼 (함수/클래스) 수집
3. test 파일에서 `patch("path.to.X")`, `mocker.patch("...")`, `patch.object(mod, "X")`
   호출 감지
4. patch target의 마지막 세그먼트가 target 심볼에 속하면 → warn
   ("test가 검증 대상 X를 mock하고 있음")

v1 한계 (문서화):
- import alias(`from mymodule import target as alias; patch("mod.alias")`) 미처리
- 동적 patch (`patch(target_var)`) 미처리
- src/ 레이아웃과 flat 레이아웃 외 발견 못 하는 target 있음
- 다중 test 파일이 한 target 매핑 시 첫 매치만
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes


_QUERY = """
(function_definition name: (identifier) @name) @fn
(call) @call
"""

# Patch calls we recognize: bare identifier ends in "patch" or "patch.object".
# Covers `patch("...")`, `mocker.patch("...")`, `unittest.mock.patch(...)`,
# `mock.patch.object(mod, "sym")`.
_PATCH_CALLABLE_SUFFIXES = ("patch", "patch.object")


@lru_cache(maxsize=1)
def _query() -> tuple[Any, Any]:
    import tree_sitter_python
    from tree_sitter import Language, Query
    lang = Language(tree_sitter_python.language())
    return lang, Query(lang, _QUERY)


@lru_cache(maxsize=1)
def _parser() -> Any:
    from tree_sitter import Parser
    lang, _ = _query()
    return Parser(lang)


def _is_test_file(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith("test_") and name.endswith(".py")


def _resolve_target(test_path: str, all_paths: set[str]) -> str | None:
    """test_foo.py -> the source file `foo.py` most likely to be its target.

    Real repos use varied layouts (`src/pkg/foo.py`, `pkg/foo.py`, flat
    `foo.py`), so we scan every non-test path whose basename matches and
    pick the one sharing the longest directory prefix with the test file.
    Ties broken by shortest total path (prefers the module over a fixture)."""
    p = PurePosixPath(test_path)
    if not p.name.startswith("test_"):
        return None
    target_name = p.name[len("test_"):]
    test_parts = p.parent.parts

    matches: list[tuple[int, int, str]] = []  # (-shared_prefix, path_len, path)
    for cand in all_paths:
        cp = PurePosixPath(cand)
        if cp.name != target_name:
            continue
        if cand == test_path:
            continue
        if cp.name.startswith("test_"):
            continue  # never map a test file to another test file
        # Shared leading directory count
        shared = 0
        for a, b in zip(test_parts, cp.parent.parts):
            if a == b:
                shared += 1
            else:
                break
        matches.append((-shared, len(cand), cand))

    if not matches:
        return None
    matches.sort()
    return matches[0][2]


def _top_level_symbols(indices: dict[str, FileIndex], path: str) -> set[str]:
    """Top-level function/class names in the target file.
    Simplification: FileIndex doesn't track depth, so we approximate by
    treating any function whose kind is 'function' (not 'method') as top-level,
    plus all classes. Good enough for the naming-based lookup below."""
    idx = indices.get(path)
    if idx is None:
        return set()
    out = set()
    for s in idx.symbols:
        if s.kind in ("function", "class"):
            out.add(s.name)
    return out


def _call_function_text(call: Any) -> str:
    fn = call.child_by_field_name("function")
    return fn.text.decode("utf-8", "replace") if fn is not None else ""


def _first_string_arg(call: Any) -> str | None:
    """Return the literal text of the first string argument, unquoted."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    for c in args.children:
        if c.type == "string":
            text = c.text.decode("utf-8", "replace")
            # strip surrounding quote characters, handle prefixes r/b/u/f
            i = 0
            while i < len(text) and text[i] in "rRbBuUfF":
                i += 1
            if i < len(text) and text[i] in ("'", '"'):
                q = text[i]
                # find matching close; handle triple quotes conservatively
                if text[i:i + 3] == q * 3:
                    return text[i + 3:-3]
                return text[i + 1:-1]
            return text
    return None


def _patched_symbol(call: Any) -> str | None:
    """Return the mocked identifier's short name, or None if not a patch call.
    - patch("a.b.C") / mocker.patch("a.b.C") -> "C"
    - patch.object(mod, "C") -> "C"

    In both forms the mocked NAME is the first *string* literal argument
    (patch.object's 1st positional arg is the module identifier, not a string)."""
    fn = _call_function_text(call)
    if not fn:
        return None
    is_obj = fn.endswith("patch.object")
    is_plain = not is_obj and (fn == "patch" or fn.endswith(".patch"))
    if not (is_plain or is_obj):
        return None
    raw = _first_string_arg(call)
    if not raw:
        return None
    return raw.rsplit(".", 1)[-1]


class MocksTarget:
    id = "test.mocks-target"
    version = "1"

    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
        from tree_sitter import QueryCursor
        _, q = _query()
        all_paths = set(indices.keys())
        out: list[Finding] = []

        for fc in cs.files:
            if fc.status == "deleted" or fc.path not in indices:
                continue
            if not _is_test_file(fc.path):
                continue
            target_path = _resolve_target(fc.path, all_paths)
            if target_path is None:
                continue
            target_syms = _top_level_symbols(indices, target_path)
            if not target_syms:
                continue

            src = normalize_bytes(fc.absolute.read_bytes())
            tree = _parser().parse(src)
            # Walk each test_ function; collect patch calls whose target
            # matches a top-level symbol of the mapped target file.
            for _, caps in QueryCursor(q).matches(tree.root_node):
                if "fn" not in caps:
                    continue
                fn_node = caps["fn"][0]
                name = caps["name"][0].text.decode("utf-8", "replace")
                if not name.startswith("test_"):
                    continue
                hits = _mocked_targets(fn_node, target_syms)
                if not hits:
                    continue
                out.append(Finding(
                    analyzer_id=self.id, analyzer_version=self.version,
                    severity="warn",
                    file=fc.path,
                    span=(fn_node.start_point[0] + 1, fn_node.end_point[0] + 1),
                    symbol=name,
                    message=f"test `{name}` mocks its own target ({', '.join(sorted(hits))})",
                    evidence={
                        "target_file": target_path,
                        "mocked_symbols": sorted(hits),
                    },
                ))
        return out


def _mocked_targets(fn_node: Any, target_syms: set[str]) -> set[str]:
    """Scan the function subtree for patch(...) calls; return the set of
    patched short-names that also exist as top-level symbols in the target."""
    hits: set[str] = set()
    stack = [fn_node]
    while stack:
        n = stack.pop()
        if n.type == "call":
            sym = _patched_symbol(n)
            if sym and sym in target_syms:
                hits.add(sym)
        stack.extend(n.children)
    return hits


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "foo.py").write_text(
            "def compute(x):\n    return x * 2\n\n"
            "class Widget:\n    def spin(self):\n        return 42\n"
        )
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text(
            "from unittest.mock import patch\n"
            "import pytest\n"
            "\n"
            "def test_bad_mocks_target():\n"
            "    with patch('foo.compute', return_value=99):\n"
            "        assert True\n"
            "\n"
            "def test_bad_patch_object():\n"
            "    import foo\n"
            "    with patch.object(foo, 'Widget'):\n"
            "        pass\n"
            "\n"
            "def test_ok_mocks_dependency():\n"
            "    with patch('other.helper'):\n"
            "        assert True\n"
        )
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = MocksTarget().analyze(cs, indices)
        names = sorted(f.symbol for f in findings)
        assert names == ["test_bad_mocks_target", "test_bad_patch_object"], names
        mocked = sorted(sym for f in findings for sym in f.evidence["mocked_symbols"])
        assert mocked == ["Widget", "compute"], mocked
        print("mocks-target ok", names)


if __name__ == "__main__":
    demo()
