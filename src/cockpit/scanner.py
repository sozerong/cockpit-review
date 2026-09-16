"""Enumerate source files in a repo. `git ls-files` first (free .gitignore),
os.walk fallback for non-git trees. PLAN §10 first row.

Stateful cache: FileListCache caches the file list per repo. Invalidation
sentinel = `.git/index` mtime + `.git/HEAD` mtime for git repos, or None
(always rescan) for non-git repos. Watchers use this to skip the ~150ms
FS walk when the tracked set hasn't changed."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass, field
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
        # Skip symlinks BEFORE is_file() (which follows them). A repo
        # can otherwise contain `evil.py -> /home/user/.aws/credentials`
        # that gets ingested and leaks into the served evidence snippet.
        if p.is_symlink():
            continue
        if not p.is_file():
            continue
        if any(part in _EXCLUDE_DIRS for part in p.relative_to(repo).parts):
            continue
        yield p


def scan(repo: Path) -> list[Path]:
    """Return absolute paths of source files under `repo`. Uncached one-shot.

    Prefer FileListCache().scan(repo) for repeated calls."""
    return _scan_uncached(repo.resolve())


def _scan_uncached(repo: Path) -> list[Path]:
    candidates = _git_ls(repo)
    if candidates is None:
        candidates = list(_walk(repo))
    out = []
    for p in candidates:
        if p.suffix not in _SOURCE_EXTS:
            continue
        # Symlinks in the git-tracked set can still point outside the
        # repo (`evil.py -> /etc/passwd`); reading them would leak
        # credentials via the served evidence snippet. Skip.
        try:
            if p.is_symlink():
                continue
            if p.stat().st_size > _MAX_BYTES:
                continue
        except OSError:
            continue
        out.append(p)
    out.sort()  # PLAN §9.4 determinism
    return out


def _git_sentinels(repo: Path) -> tuple[tuple[str, float], ...] | None:
    """(path, mtime) pairs for the sentinels that invalidate the scan cache.

    Sentinel choice: `.git/index` (staged file set), `.git/HEAD` (branch swap).
    Both change when the tracked set of files can plausibly change under a
    common workflow: staging a new file, switching branches. Editing an
    already-tracked file does not touch either, which is exactly what we
    want — the file list is unchanged, we save the walk. None = not a git
    repo (no cache)."""
    gi = repo / ".git" / "index"
    if not gi.exists():
        return None
    sentinels: list[tuple[str, float]] = []
    for rel in ("index", "HEAD"):
        p = repo / ".git" / rel
        try:
            sentinels.append((rel, p.stat().st_mtime))
        except OSError:
            pass
    return tuple(sentinels)


@dataclass
class FileListCache:
    """Cache scan() output per repo, invalidated by git sentinels.

    Miss cost: one _scan_uncached() call (~150ms on fastapi).
    Hit cost: one .git/index stat + one .git/HEAD stat (~5µs each).
    Non-git repos always miss — no free invalidation signal available."""
    _cache: dict[Path, tuple[tuple[tuple[str, float], ...], list[Path]]] = field(default_factory=dict)

    def scan(self, repo: Path) -> list[Path]:
        repo = repo.resolve()
        sentinels = _git_sentinels(repo)
        if sentinels is not None:
            cached = self._cache.get(repo)
            if cached is not None and cached[0] == sentinels:
                return cached[1]
        result = _scan_uncached(repo)
        if sentinels is not None:
            self._cache[repo] = (sentinels, result)
        return result

    def reset(self, repo: Path | None = None) -> None:
        if repo is None:
            self._cache.clear()
        else:
            self._cache.pop(repo.resolve(), None)


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
