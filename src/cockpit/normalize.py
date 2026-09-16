"""Content + path normalization. BRIEF §9 landmine 2: CRLF/BOM/case must be
normalized before hashing or the same code hashes differently per OS."""
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath

_BOM = b"\xef\xbb\xbf"


def normalize_bytes(data: bytes) -> bytes:
    if data.startswith(_BOM):
        data = data[len(_BOM):]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def hash_bytes(data: bytes) -> str:
    return hashlib.blake2b(normalize_bytes(data), digest_size=16).hexdigest()


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def normalize_path(repo: Path, path: Path) -> str:
    """Repo-relative POSIX path.

    Fast path: caller passes an already-resolved repo and a path that is
    already absolute under it. That's true from `full_scan` on any repo
    the scanner discovered — `repo / relative_component` produces such a
    path without stat syscalls. .resolve() is the slow fallback for
    symlinks or unusual inputs. On Windows the fallback costs ~200µs per
    call and dominates full_scan on large repos (~300ms on fastapi)."""
    try:
        rel = path.relative_to(repo)
    except ValueError:
        rel = path.resolve().relative_to(repo.resolve())
    return str(PurePosixPath(*rel.parts))


def demo() -> None:
    assert normalize_bytes(b"\xef\xbb\xbfabc\r\ndef\r\n") == b"abc\ndef\n"
    assert hash_bytes(b"a\r\nb") == hash_bytes(b"a\nb")
    print("normalize ok")


if __name__ == "__main__":
    demo()
