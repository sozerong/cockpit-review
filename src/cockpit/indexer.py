"""tree-sitter Python indexer. Parse → extract (symbols, source hash) → drop AST.
PLAN §9.5: never keep the AST around."""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .normalize import hash_bytes, normalize_bytes


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str            # "function" | "class" | "method"
    span: tuple[int, int]  # 1-indexed inclusive


@dataclass(frozen=True)
class FileIndex:
    path: str            # repo-relative POSIX
    content_hash: str
    lines: int
    symbols: tuple[Symbol, ...]


# Top-level defs + methods. Tightly scoped query — extend when analyzers need more.
_QUERY = """
(function_definition name: (identifier) @fn.name) @fn
(class_definition name: (identifier) @cls.name) @cls
"""


@lru_cache(maxsize=1)
def _lang_and_query() -> tuple[Any, Any]:
    import tree_sitter_python
    from tree_sitter import Language, Query
    lang = Language(tree_sitter_python.language())
    return lang, Query(lang, _QUERY)


@lru_cache(maxsize=1)
def _parser() -> Any:
    from tree_sitter import Parser
    lang, _ = _lang_and_query()
    return Parser(lang)


def _row_span(node: Any) -> tuple[int, int]:
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def index_file(rel_path: str, absolute: Path) -> FileIndex:
    raw = absolute.read_bytes()
    normalized = normalize_bytes(raw)
    tree = _parser().parse(normalized)
    _, query = _lang_and_query()
    from tree_sitter import QueryCursor
    matches = QueryCursor(query).matches(tree.root_node)
    symbols: list[Symbol] = []
    for _, caps in matches:
        if "fn" in caps:
            defn = caps["fn"][0]
            name = caps["fn.name"][0].text.decode("utf-8", "replace")
            # Method if enclosed in a class_definition
            kind = "function"
            p = defn.parent
            while p is not None:
                if p.type == "class_definition":
                    kind = "method"
                    break
                p = p.parent
            symbols.append(Symbol(name=name, kind=kind, span=_row_span(defn)))
        elif "cls" in caps:
            defn = caps["cls"][0]
            name = caps["cls.name"][0].text.decode("utf-8", "replace")
            symbols.append(Symbol(name=name, kind="class", span=_row_span(defn)))
    symbols.sort(key=lambda s: (s.span[0], s.name))
    return FileIndex(
        path=rel_path,
        content_hash=hash_bytes(raw),
        lines=normalized.count(b"\n") + (0 if normalized.endswith(b"\n") else 1),
        symbols=tuple(symbols),
    )


def demo() -> None:
    import tempfile
    src = b"""\
def top():
    pass

class C:
    def method(self):
        return 1
"""
    with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as tf:
        tf.write(src)
        p = Path(tf.name)
    try:
        idx = index_file("t.py", p)
        names = [(s.kind, s.name) for s in idx.symbols]
        assert ("function", "top") in names, names
        assert ("class", "C") in names, names
        assert ("method", "method") in names, names
        assert idx.lines == 6, idx.lines
        print("indexer ok", names)
    finally:
        p.unlink()


if __name__ == "__main__":
    demo()
