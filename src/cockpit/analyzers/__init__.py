"""Analyzer registry — plain list. Add a new analyzer = append here.
No factory, no plugin discovery until an external plugin actually exists."""
from __future__ import annotations
from typing import Protocol, runtime_checkable

from ..changeset import ChangeSet
from ..finding import Finding
from ..indexer import FileIndex

from .error_masking import ErrorMasking
from .dup_block import DupBlock
from .assertion_free import AssertionFree
from .always_true_assertion import AlwaysTrueAssertion
from .no_test_for_public import NoTestForPublic
from .reraise_vs_raise import ReraiseVsRaise
from .arg_mutable_default import ArgMutableDefault
from .test_time_sleep import TestTimeSleep
# mocks_target v2: SUT-name filter closes the v1 precision hole
# (test_<sym>_... must match the mocked symbol). Re-enabled 2026-09-17.
from .mocks_target import MocksTarget
from .ponytail_reinvented import PonytailReinvented


@runtime_checkable
class Analyzer(Protocol):
    id: str
    version: str
    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]: ...


# Analyzers whose findings depend on multiple files (a change in file A
# can produce/remove/mutate findings in file B). The incremental scanner
# always re-runs these on a full ChangeSet, not the changed-files subset.
# Single-file analyzers can safely incrementalize.
CROSS_FILE = frozenset({
    "dup.block",                       # windows match across files
    "test.no-test-for-public-symbol",  # symbol-in-src <-> test-file lookup
})


ANALYZERS: list[Analyzer] = [
    ErrorMasking(),
    DupBlock(),
    AssertionFree(),
    AlwaysTrueAssertion(),
    NoTestForPublic(),
    ReraiseVsRaise(),
    ArgMutableDefault(),
    TestTimeSleep(),
    MocksTarget(),
    PonytailReinvented(),
]


def run_all(cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
    out: list[Finding] = []
    for a in ANALYZERS:
        out.extend(a.analyze(cs, indices))
    return out
