"""dup.block — 5+ line duplicate blocks *inside function bodies*.

Week 3 gate finding: class-level windowing was 26k findings across 9 repos,
almost all noise (import stacks, decorator stacks, __init__ field lists,
fastapi route stubs, pytest fixtures). Real logic duplication lives in
function bodies. Restricting the window source removes the noise class
without losing the signal class.

ponytail: exact-line window inside function bodies. Type-2/3/4 clones (renamed
identifiers, AST-normalized) wait for §BRIEF 5 M4. Class-level scanning stays
off until someone shows a real duplicate we're missing there."""
from __future__ import annotations
from collections import defaultdict
from functools import lru_cache
from typing import Any

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex
from ..normalize import normalize_bytes

_WINDOW = 5             # BRIEF §5 — matches GitClear definition
_MIN_NONBLANK = 3       # a 5-line window mostly blank isn't a duplicate
_ACTIONABLE_MAX = 5     # >5 copies = widespread pattern, collapse to one info
_STRING_RATIO = 0.6     # window with ≥60% bytes inside string literals = skip
                        # kills docstrings, JSON schema literals, CLI output blocks

_FN_QUERY = """
(function_definition body: (block) @body)
(string) @str
"""


from ._paths import is_non_source_path as _is_non_source_path
import hashlib


def _stable_hash(text: str) -> str:
    """Deterministic 8-hex-char digest. Python's built-in hash() is
    randomized per process (PYTHONHASHSEED), which breaks Finding.id stability
    across runs and defeats baselining."""
    return hashlib.blake2b(text.encode("utf-8"), digest_size=4).hexdigest()


@lru_cache(maxsize=1)
def _query() -> tuple[Any, Any]:
    import tree_sitter_python
    from tree_sitter import Language, Query
    lang = Language(tree_sitter_python.language())
    return lang, Query(lang, _FN_QUERY)


@lru_cache(maxsize=1)
def _parser() -> Any:
    from tree_sitter import Parser
    lang, _ = _query()
    return Parser(lang)


def _windows_in_bodies(src: bytes) -> list[tuple[int, str]]:
    """Yield (file_line_1indexed, joined_5_lines) for every 5-line window
    that falls inside a function body and is not string-dominant.

    Dedup by (start_line, text): nested function bodies overlap in source,
    so the same window would otherwise be emitted twice — that leaves the
    cluster's `matches` empty when both are the entire cluster (the v3 bug).

    String-dominant windows (docstrings, JSON schema literals, CLI output
    triple-quoted blocks) are dropped: if ≥60% of a window's bytes fall
    inside a `(string)` node, it isn't code duplication."""
    from tree_sitter import QueryCursor
    tree = _parser().parse(src)
    _, q = _query()

    # Line offset table: byte offset of the start of each 1-indexed line.
    line_starts = [0]
    for i, b in enumerate(src):
        if b == 0x0A:  # '\n'
            line_starts.append(i + 1)
    line_starts.append(len(src))  # sentinel

    bodies: list[Any] = []
    string_ranges: list[tuple[int, int]] = []
    for _, caps in QueryCursor(q).matches(tree.root_node):
        if "body" in caps:
            bodies.append(caps["body"][0])
        if "str" in caps:
            s = caps["str"][0]
            string_ranges.append((s.start_byte, s.end_byte))
    string_ranges.sort()

    def string_overlap(byte_start: int, byte_end: int) -> int:
        """Total bytes of [byte_start, byte_end) that fall inside any string
        node. Ranges are sorted; naive scan is fine for typical string counts."""
        total = 0
        for a, b in string_ranges:
            if b <= byte_start:
                continue
            if a >= byte_end:
                break
            total += min(b, byte_end) - max(a, byte_start)
        return total

    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, str]] = []
    for body in bodies:
        body_text = src[body.start_byte:body.end_byte].decode("utf-8", "replace")
        body_start_line = body.start_point[0] + 1
        lines = [ln.rstrip() for ln in body_text.split("\n")]
        for i in range(len(lines) - _WINDOW + 1):
            window = lines[i:i + _WINDOW]
            if sum(1 for ln in window if ln.strip()) < _MIN_NONBLANK:
                continue
            distinct = len({ln.strip() for ln in window if ln.strip()})
            if distinct < 3:
                continue
            joined = "\n".join(window)
            key = (body_start_line + i, joined)
            if key in seen:
                continue
            # String-dominance check via source byte ranges of the window.
            win_start_line = body_start_line + i  # 1-indexed source line
            win_end_line = win_start_line + _WINDOW  # exclusive
            byte_a = line_starts[win_start_line - 1]
            byte_b = line_starts[min(win_end_line - 1, len(line_starts) - 1)]
            if byte_b > byte_a:
                overlap = string_overlap(byte_a, byte_b)
                if overlap / (byte_b - byte_a) >= _STRING_RATIO:
                    continue
            seen.add(key)
            out.append(key)
    return out


class DupBlock:
    id = "dup.block"
    # v2: function-body only; v3: collapse widespread; v4: nested-fn dedupe,
    # string-dominant dropped, tests/ → info; v5: path filter expanded to
    # testing/, examples/, docs_src/, docs/.
    version = "5"

    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
        buckets: dict[int, list[tuple[str, int, str]]] = defaultdict(list)
        for fc in cs.files:
            if fc.status == "deleted" or fc.path not in indices:
                continue
            src = normalize_bytes(fc.absolute.read_bytes())
            for start, win in _windows_in_bodies(src):
                buckets[hash(win)].append((fc.path, start, win))

        raw: list[Finding] = []
        for group in buckets.values():
            if len(group) < 2:
                continue
            # Guard against hash collisions.
            by_text: dict[str, list[tuple[str, int]]] = defaultdict(list)
            for path, start, win in group:
                by_text[win].append((path, start))
            for win, locs in by_text.items():
                if len(locs) < 2:
                    continue
                locs.sort()
                # Widespread clusters (>5 copies): collapse to a single info
                # anchored at the first location — reviewer sees the pattern
                # once, not N times. Small clusters stay actionable warns.
                if len(locs) > _ACTIONABLE_MAX:
                    path, start = locs[0]
                    raw.append(Finding(
                        analyzer_id=self.id, analyzer_version=self.version,
                        severity="info", file=path,
                        span=(start, start + _WINDOW - 1), symbol=None,
                        message=f"{_WINDOW}+ line block duplicated in "
                                f"{len(locs)} places (widespread)",
                        evidence={
                            "window_hash": _stable_hash(win),
                            "total_matches": len(locs),
                            "matches": [{"file": p, "span": [s, s + _WINDOW - 1]}
                                        for p, s in locs[1:_ACTIONABLE_MAX + 1]],
                        },
                    ))
                    continue
                for path, start in locs:
                    others = [{"file": p, "span": [s, s + _WINDOW - 1]}
                              for p, s in locs if (p, s) != (path, start)]
                    # Non-source path (tests/examples/docs) downgrade — these
                    # directories legitimately duplicate scaffolding.
                    sev = "info" if _is_non_source_path(path) else "warn"
                    raw.append(Finding(
                        analyzer_id=self.id, analyzer_version=self.version,
                        severity=sev, file=path,
                        span=(start, start + _WINDOW - 1),
                        symbol=None,
                        message=f"{_WINDOW}+ line block duplicated in {len(locs)} places",
                        evidence={
                            "window_hash": _stable_hash(win),
                            "matches": others,
                        },
                    ))
        # Per-file overlap collapse — one finding per contiguous duplicate run.
        raw.sort(key=lambda f: (f.file, f.span[0]))
        out: list[Finding] = []
        last_end: dict[str, int] = {}
        for f in raw:
            if f.span[0] <= last_end.get(f.file, 0):
                continue
            out.append(f)
            last_end[f.file] = f.span[1]
        return out


def demo() -> None:
    import tempfile
    from pathlib import Path
    from ..changeset import full_scan
    from ..indexer import index_file

    shared_logic = (
        "    total = 0\n"
        "    for item in items:\n"
        "        if item.active:\n"
        "            total += item.value\n"
        "    return total\n"
    )
    a = f"def sum_a(items):\n{shared_logic}\n"
    b = f"def sum_b(items):\n{shared_logic}\n"
    # Module-level import stack — should NOT be flagged
    imports = "import os\nimport sys\nimport json\nimport time\nimport re\n"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text(imports + a)
        (root / "b.py").write_text(imports + b)
        (root / "c.py").write_text(imports + "x = 1\n")  # imports only, no fn dup
        cs = full_scan(root)
        indices = {fc.path: index_file(fc.path, fc.absolute) for fc in cs.files}
        findings = DupBlock().analyze(cs, indices)
        files = sorted(f.file for f in findings)
        assert files == ["a.py", "b.py"], files
        # c.py must NOT be flagged — its only "duplication" is the import stack
        assert "c.py" not in files
        print("dup-block v2 ok", files)


if __name__ == "__main__":
    demo()
