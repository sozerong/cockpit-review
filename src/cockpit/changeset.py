"""ChangeSet — the sole analyzer input (BRIEF §11).
Same shape from full scan, watch delta, or `git diff`."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import subprocess

from .normalize import normalize_path
from .scanner import FileListCache, scan

Kind = Literal["full", "diff", "watch"]

# Module-level file list cache — cheap to keep, saves ~150ms per warm
# scan on fastapi. Callers that need isolation build their own FileListCache.
_default_list_cache = FileListCache()


@dataclass(frozen=True)
class FileChange:
    path: str            # repo-relative POSIX
    absolute: Path
    status: Literal["added", "modified", "deleted", "present"]


@dataclass(frozen=True)
class ChangeSet:
    repo: Path
    kind: Kind
    base: str | None            # git ref or None
    head: str                   # "working" or ref
    files: tuple[FileChange, ...] = field(default_factory=tuple)


def full_scan(repo: Path, cache: FileListCache | None = None) -> ChangeSet:
    repo = repo.resolve()
    lc = cache if cache is not None else _default_list_cache
    files = tuple(
        FileChange(path=normalize_path(repo, p), absolute=p, status="present")
        for p in lc.scan(repo)
    )
    return ChangeSet(repo=repo, kind="full", base=None, head="working", files=files)


def from_git_diff(repo: Path, base: str = "HEAD", head: str = "working") -> ChangeSet:
    """Files changed between `base` and working tree (default). Deleted files
    are included so analyzers can drop stale state."""
    repo = repo.resolve()
    args = ["git", "-C", str(repo), "diff", "--name-status", "-z", base]
    if head != "working":
        args.append(head)
    out = subprocess.run(args, capture_output=True, check=True, timeout=10)
    tokens = [t for t in out.stdout.split(b"\x00") if t]
    changes: list[FileChange] = []
    i = 0
    while i < len(tokens):
        code = tokens[i].decode()[:1]
        # ponytail: skip R/C rename detection — treat as delete+add.
        # Upgrade path: parse tokens[i+2] when code in {"R","C"}.
        path = tokens[i + 1].decode("utf-8", "replace")
        status = {"A": "added", "M": "modified", "D": "deleted"}.get(code, "modified")
        changes.append(FileChange(
            path=path, absolute=repo / path, status=status,  # type: ignore[arg-type]
        ))
        i += 2
    changes.sort(key=lambda c: c.path)
    return ChangeSet(repo=repo, kind="diff", base=base, head=head, files=tuple(changes))


def demo() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("pass\n")
        cs = full_scan(root)
        assert cs.kind == "full" and len(cs.files) == 1
        assert cs.files[0].path == "a.py"
        print("changeset ok")


if __name__ == "__main__":
    demo()
