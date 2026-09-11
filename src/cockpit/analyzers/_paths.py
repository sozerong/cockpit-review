"""Shared path classifier. Used by any analyzer that wants to downgrade
findings coming from test/example/doc directories to `info`."""

_NON_SOURCE_SEGMENTS = frozenset({
    "tests", "test", "testing",
    "examples", "example",
    "docs_src", "docs", "doc",
})


def is_non_source_path(path: str) -> bool:
    """True if the file is test / example / tutorial / docs (POSIX slashes).
    These directories legitimately duplicate scaffolding and silently swallow
    intentional exceptions, so warns get downgraded to info."""
    name = path.rsplit("/", 1)[-1]
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(seg in _NON_SOURCE_SEGMENTS for seg in path.split("/"))
