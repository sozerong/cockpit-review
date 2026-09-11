"""`cockpit watch` — poll for changes, re-run check, emit NDJSON.

ponytail: mtime polling, no watchdog dep. Sidesteps the bind-mount/WSL2/APFS
landmine cluster (BRIEF §9). Upgrade path: watchdog when polling measurably
falls short — a repo where 500ms polling actually shows up in a profile."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from .analyzers import run_all
from .changeset import full_scan
from .finding import to_json
from .indexer import index_file

POLL_INTERVAL = 0.5     # seconds between filesystem scans
DEBOUNCE = 0.3          # quiet window after last change before we re-run

# Editor temp files that flap during a save.
_TEMP_SUFFIXES = (".swp", ".swo", "~", ".tmp")
_TEMP_PREFIXES = (".#",)


def _snapshot(repo: Path) -> dict[str, float]:
    """Path → mtime for every source file the scanner sees."""
    cs = full_scan(repo)
    out: dict[str, float] = {}
    for fc in cs.files:
        name = fc.absolute.name
        if name.startswith(_TEMP_PREFIXES) or name.endswith(_TEMP_SUFFIXES):
            continue
        try:
            out[fc.path] = fc.absolute.stat().st_mtime
        except OSError:
            pass
    return out


def _run_once(repo: Path) -> dict:
    cs = full_scan(repo)
    indices = {}
    for fc in cs.files:
        try:
            indices[fc.path] = index_file(fc.path, fc.absolute)
        except Exception:
            # PLAN §11: partial-save parse errors are noise, not findings.
            pass
    findings = run_all(cs, indices)
    return to_json(
        repo=str(repo.resolve()),
        scope={"kind": "full", "base": None, "head": "working"},
        findings=findings,
        files_scanned=len(indices),
    )


def cmd_watch(repo: Path, once: bool = False) -> int:
    prev = _snapshot(repo)
    # Emit an initial envelope so consumers have state on connect.
    _emit(_run_once(repo))
    if once:
        return 0

    last_change_at: float | None = None
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            cur = _snapshot(repo)
            if cur != prev:
                last_change_at = time.monotonic()
                prev = cur
            elif last_change_at is not None and \
                    time.monotonic() - last_change_at >= DEBOUNCE:
                # Filesystem has been quiet long enough — re-run.
                _emit(_run_once(repo))
                last_change_at = None
    except KeyboardInterrupt:
        return 0


def _emit(envelope: dict) -> None:
    """NDJSON: one JSON object per line, flushed immediately."""
    json.dump(envelope, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


def demo() -> None:
    """One-shot self-check: watch --once emits a valid envelope."""
    import io
    import tempfile
    from contextlib import redirect_stdout
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.py").write_text("def f():\n    pass\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_watch(root, once=True)
        env = json.loads(buf.getvalue().strip())
        assert env["schema"] == 1
        assert env["summary"]["files_scanned"] == 1
        print("watch ok")


if __name__ == "__main__":
    demo()
