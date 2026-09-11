"""Finding + JSON envelope. PLAN §3 (JSON contract) and §9.3 (stable id).

Any UI/CI consumer speaks this shape and only this shape."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

from . import SCHEMA_VERSION

Severity = Literal["block", "warn", "info"]


@dataclass(frozen=True)
class Finding:
    analyzer_id: str            # "dup.block"
    analyzer_version: str       # bumped when logic/threshold changes (§9.1)
    severity: Severity
    file: str                   # repo-relative POSIX
    span: tuple[int, int]       # 1-indexed inclusive line range
    symbol: str | None
    message: str
    evidence: dict              # required (§0 identity)

    @property
    def id(self) -> str:
        """Stable across line-number shifts (§9.3). Hash of what the
        finding is about, not where it currently sits."""
        payload = json.dumps({
            "a": self.analyzer_id,
            "v": self.analyzer_version,
            "s": self.symbol or self.file,
            "e": self.evidence,
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.blake2b(payload.encode(), digest_size=12).hexdigest()


def sort_key(f: Finding) -> tuple:
    """PLAN §9.4 determinism: file → start line → analyzer_id → finding_id."""
    return (f.file, f.span[0], f.analyzer_id, f.id)


def to_json(
    repo: str,
    scope: dict[str, Any],
    findings: list[Finding],
    files_scanned: int,
) -> dict[str, Any]:
    findings = sorted(findings, key=sort_key)
    summary = {"block": 0, "warn": 0, "info": 0, "files_scanned": files_scanned}
    for f in findings:
        summary[f.severity] += 1
    return {
        "schema": SCHEMA_VERSION,
        "repo": repo,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": scope,
        "summary": summary,
        "findings": [_finding_dict(f) for f in findings],
    }


def _finding_dict(f: Finding) -> dict[str, Any]:
    d = asdict(f)
    d["id"] = f.id
    d["span"] = list(f.span)
    return d


def demo() -> None:
    f1 = Finding("dup.block", "1", "warn", "a.py", (1, 5), "foo",
                 "dup", {"hash": "abc", "matches": []})
    f2 = Finding("dup.block", "1", "warn", "a.py", (1, 5), "foo",
                 "dup", {"hash": "abc", "matches": []})
    assert f1.id == f2.id, "id must be stable"
    f3 = Finding("dup.block", "2", "warn", "a.py", (1, 5), "foo",
                 "dup", {"hash": "abc", "matches": []})
    assert f1.id != f3.id, "version bump changes id"
    env = to_json("/tmp/r", {"kind": "full"}, [f1], files_scanned=1)
    assert env["schema"] == SCHEMA_VERSION
    assert env["summary"]["warn"] == 1
    print("finding ok id=", f1.id)


if __name__ == "__main__":
    demo()
