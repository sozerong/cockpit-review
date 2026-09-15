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
# mocks_target: disabled — BRIEF §13.5 precision <0.7 stop criterion tripped
# (v1 pilot: 0-5% on 20 findings; needs SUT-detection v2, deferred).
# from .mocks_target import MocksTarget


@runtime_checkable
class Analyzer(Protocol):
    id: str
    version: str
    def analyze(self, cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]: ...


ANALYZERS: list[Analyzer] = [
    ErrorMasking(),
    DupBlock(),
    AssertionFree(),
    AlwaysTrueAssertion(),
    NoTestForPublic(),
    ReraiseVsRaise(),
]


def run_all(cs: ChangeSet, indices: dict[str, FileIndex]) -> list[Finding]:
    out: list[Finding] = []
    for a in ANALYZERS:
        out.extend(a.analyze(cs, indices))
    return out
