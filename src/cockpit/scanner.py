"""Enumerate source files in a repo. `git ls-files` first (free .gitignore),
os.walk fallback for non-git trees. PLAN §10 first row."""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Iterable

# ponytail: hardcoded exclude + extension allowlist. Move to config when a
# real user asks for a non-Python target.
_EXCLUDE_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build",
                 "__pycache__", ".cockpit", ".tox", ".mypy_cache"}
_MAX_BYTES = 1_000_000  # BRIEF §10.7: 1MB per-file cap
_SOURCE_EXTS = {".py"}  # Week 1: Python only


def _git_ls(repo: Path) -> list[Path] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    parts = out.stdout.split(b"\x00")
    return [repo / p.decode("utf-8", "replace") for p in parts if p]


def _walk(repo: Path) -> Iterable[Path]:
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _EXCLUDE_DIRS for part in p.relative_to(repo).parts):
            continue
        yield p


def scan(repo: Path) -> list[Path]:
    """Return absolute paths of source files under `repo`."""
    repo = repo.resolve()
    candidates = _git_ls(repo)
    if candidates is None:
        candidates = list(_walk(repo))
    out = []
    for p in candidates:
        if p.suffix not in _SOURCE_EXTS:
            continue
        try:
            if p.stat().st_size > _MAX_BYTES:
                continue
        except OSError:
            continue
        out.append(p)
    out.sort()  # PLAN §9.4 determinism
    return out


def demo() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("x = 1\n")
        (root / "sub").mkdir()
        (root / "sub" / "b.py").write_text("y = 2\n")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "junk.py").write_text("z = 3\n")
        (root / "readme.md").write_text("no")
        found = scan(root)
        rels = sorted(p.relative_to(root).as_posix() for p in found)
        assert rels == ["a.py", "sub/b.py"], rels
        print("scanner ok", rels)


if __name__ == "__main__":
    demo()
