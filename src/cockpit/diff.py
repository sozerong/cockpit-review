"""cockpit diff — machine receipt of what changed between two scans.

Inspired by Archify's Architecture Delta: two envelopes go in
(base + head), a **typed** diff comes out. Deterministic, no LLM.
Used by CI to comment on PRs with "you added N warns, resolved M".

A finding is:
- **added**   if in head only (by id)
- **resolved** if in base only
- **moved**   if the same id appears in both but span/file changed
- **stable**  if unchanged (id and location the same) — not emitted

The receipt is a stable JSON shape so both humans and machines can act
on it. See RECEIPT_SCHEMA below for the contract.
"""
from __future__ import annotations
import json
from typing import Any


RECEIPT_SCHEMA = 1


def compute_diff(base_env: dict, head_env: dict) -> dict:
    """Machine receipt: {schema, base, head, summary, changes}.

    Both envelopes must be schema-1 envelopes (finding.to_json output).
    Findings are matched by id (blake2b of analyzer + version + symbol +
    evidence — stable across line shifts by design)."""
    base_by_id = {f["id"]: f for f in base_env["findings"]}
    head_by_id = {f["id"]: f for f in head_env["findings"]}

    added, resolved, moved = [], [], []

    for fid, hf in head_by_id.items():
        bf = base_by_id.get(fid)
        if bf is None:
            added.append(_row(hf))
        elif (bf["file"] != hf["file"]) or (tuple(bf["span"]) != tuple(hf["span"])):
            moved.append({
                **_row(hf),
                "from": {"file": bf["file"], "span": bf["span"]},
                "to":   {"file": hf["file"], "span": hf["span"]},
            })
    for fid, bf in base_by_id.items():
        if fid not in head_by_id:
            resolved.append(_row(bf))

    def _sev_counts(rows):
        c = {"block": 0, "warn": 0, "info": 0}
        for r in rows:
            c[r["severity"]] += 1
        return c

    return {
        "schema": RECEIPT_SCHEMA,
        "base": {"repo": base_env.get("repo"), "generated_at": base_env.get("generated_at")},
        "head": {"repo": head_env.get("repo"), "generated_at": head_env.get("generated_at")},
        "summary": {
            "added":    _sev_counts(added),
            "resolved": _sev_counts(resolved),
            "moved":    _sev_counts(moved),
            "stable":   len(base_by_id.keys() & head_by_id.keys()) - len(moved),
        },
        "changes": {
            "added":    added,
            "resolved": resolved,
            "moved":    moved,
        },
    }


def _row(f: dict) -> dict:
    """Compact row shared by all change categories."""
    return {
        "id":               f["id"],
        "analyzer_id":      f["analyzer_id"],
        "analyzer_version": f["analyzer_version"],
        "severity":         f["severity"],
        "file":             f["file"],
        "span":             f["span"],
        "symbol":           f.get("symbol"),
        "message":          f["message"],
    }


def format_markdown(receipt: dict, max_rows_per_kind: int = 10) -> str:
    """Human-readable markdown of a diff receipt (for PR comments)."""
    s = receipt["summary"]
    added = s["added"]["block"] + s["added"]["warn"]
    resolved = s["resolved"]["block"] + s["resolved"]["warn"]
    moved = s["moved"]["block"] + s["moved"]["warn"]

    if added == 0 and resolved == 0 and moved == 0:
        return "**cockpit** - no meaningful change vs baseline.\n"

    lines = ["**cockpit diff**", ""]
    lines.append(
        f"`+{added} added` · `-{resolved} resolved` · `~{moved} moved`  "
        f"(stable {s['stable']})"
    )
    lines.append("")

    for kind, sign in [("added", "+"), ("resolved", "-"), ("moved", "~")]:
        rows = receipt["changes"][kind]
        actionable = [r for r in rows if r["severity"] != "info"]
        if not actionable:
            continue
        lines.append(f"### {sign} {kind} ({len(actionable)})")
        for r in actionable[:max_rows_per_kind]:
            loc = f"`{r['file']}:{r['span'][0]}`"
            extra = ""
            if kind == "moved":
                b = r.get("from", {})
                extra = f" (was `{b.get('file')}:{b.get('span', [0])[0]}`)"
            lines.append(
                f"- **{r['severity']}** {loc} [{r['analyzer_id']}] "
                f"{r['message']}{extra}"
            )
        if len(actionable) > max_rows_per_kind:
            lines.append(f"_… and {len(actionable) - max_rows_per_kind} more_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def demo() -> None:
    base = {
        "schema": 1, "repo": "x", "generated_at": "t1",
        "findings": [
            {"id": "a", "analyzer_id": "dup.block", "analyzer_version": "5",
             "severity": "warn", "file": "src/a.py", "span": [10, 15],
             "symbol": None, "message": "dup", "evidence": {}},
            {"id": "b", "analyzer_id": "risk.error-masking", "analyzer_version": "2",
             "severity": "warn", "file": "src/b.py", "span": [40, 42],
             "symbol": None, "message": "bare except", "evidence": {}},
        ],
    }
    head = {
        "schema": 1, "repo": "x", "generated_at": "t2",
        "findings": [
            # 'a' resolved.
            # 'b' moved (line 40 -> 55).
            {"id": "b", "analyzer_id": "risk.error-masking", "analyzer_version": "2",
             "severity": "warn", "file": "src/b.py", "span": [55, 57],
             "symbol": None, "message": "bare except", "evidence": {}},
            # new 'c'.
            {"id": "c", "analyzer_id": "arg.mutable-default", "analyzer_version": "1",
             "severity": "warn", "file": "src/c.py", "span": [3, 3],
             "symbol": "x", "message": "x=[]", "evidence": {}},
        ],
    }
    receipt = compute_diff(base, head)
    assert receipt["summary"]["added"]["warn"] == 1
    assert receipt["summary"]["resolved"]["warn"] == 1
    assert receipt["summary"]["moved"]["warn"] == 1
    assert receipt["summary"]["stable"] == 0
    assert len(receipt["changes"]["moved"]) == 1
    md = format_markdown(receipt)
    assert "+1 added" in md and "-1 resolved" in md and "~1 moved" in md
    print("diff ok")


if __name__ == "__main__":
    demo()
