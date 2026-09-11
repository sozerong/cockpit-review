"""Baseline — snapshot current findings so CI only fails on NEW ones.

PLAN §9.3: "기존 레포에 처음 돌리면 findings가 수천 개다. 현재 상태를 승인된
것으로 스냅샷하고 신규만 보여주지 못하면 아무도 CI에 안 넣는다."

Storage: `<repo>/.cockpit/baseline.json` — a JSON object with schema version
and a list of stable finding ids. Not the finding bodies — the id already
encodes analyzer + version + symbol + evidence (finding.py §9.3), so a
regeneration under the same analyzer version produces the same id."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable

from . import SCHEMA_VERSION
from .finding import Finding


_BASELINE_REL = ".cockpit/baseline.json"


def path(repo: Path) -> Path:
    return repo / _BASELINE_REL


def save(repo: Path, findings: Iterable[Finding]) -> Path:
    """Write a baseline for the repo. Overwrites any existing file."""
    ids = sorted({f.id for f in findings})
    p = path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(
        {"schema": SCHEMA_VERSION, "ids": ids},
        indent=2, ensure_ascii=False,
    ) + "\n", encoding="utf-8")
    return p


def load(repo: Path) -> set[str] | None:
    """Return the set of baselined ids, or None if no baseline exists."""
    p = path(repo)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return set(data.get("ids", []))


def demo() -> None:
    import tempfile
    from .finding import Finding
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f1 = Finding("dup.block", "5", "warn", "a.py", (1, 5), None,
                     "dup", {"window_hash": "abc", "matches": []})
        f2 = Finding("risk.error-masking", "2", "warn", "b.py", (10, 11), None,
                     "except", {"kind": "broad-except", "snippet": "except:"})
        assert load(root) is None
        save(root, [f1, f2])
        ids = load(root)
        assert ids == {f1.id, f2.id}, ids
        print("baseline ok")


if __name__ == "__main__":
    demo()
