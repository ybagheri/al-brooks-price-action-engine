"""Comparing two canonical vectors, and reporting every disagreement.

The comparator is deliberately dull: it walks two flat maps and produces a list of
`Difference` objects with a path and both values. There is no early exit and no
"first difference wins", because a parity report whose job is to tell someone
where two ports disagree is only useful if it says *everywhere* they disagree.
A reader who has to re-run the harness to find the second difference will not.

Three properties matter more than the mechanics:

- **A missing field is a difference, not a skip.** If the MQL5 side did not send
  `decision.reason`, the answer is a difference at `decision.reason`, not a
  comparison of the fields that happened to arrive. A harness that only compares
  what it receives will pass a side that implemented three fields.
- **The strictness is per leaf, and it is declared.** An index differing by one
  and a price differing in the fifteenth digit are different failures, so
  `EXACT_INT` is compared with `==` and `NUMBER` with the tolerance in
  `contract.py`. `deviation()` returns `None` for the exact classes precisely so
  "compared exactly" and "compared within tolerance" do not report the same way.
- **The worst deviation is reported, not just the verdict.** A case that passed
  with a margin of 1e-15 and a case that passed with 9e-10 are both `MATCH`, and
  the difference between them is the whole reason the tolerance exists.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from tests.parity.contract import (
    ABSOLUTE_FLOOR,
    CODE_OR_NULL,
    EXACT_BOOL,
    EXACT_CODE,
    EXACT_INT,
    NUMBER,
    RELATIVE_TOLERANCE,
    VectorError,
    deviation,
    flatten,
    within_tolerance,
)

#: Why two leaves disagree. Distinct codes because "the other side sent a
#: different number" and "the other side sent no number" call for different
#: responses from whoever has to fix the port.
MISMATCH = "MISMATCH"
MISSING_IN_CANDIDATE = "MISSING_IN_CANDIDATE"
MISSING_IN_REFERENCE = "MISSING_IN_REFERENCE"
NOT_A_NUMBER = "NOT_A_NUMBER"
TYPE_MISMATCH = "TYPE_MISMATCH"

#: The classes whose values must be a real number rather than `True`.
_NUMERIC = (EXACT_INT, NUMBER)


@dataclass(frozen=True, slots=True)
class Difference:
    """One disagreement, addressable by path."""

    path: str
    kind: str
    #: The reference side's value. Which side that is depends on the caller, and
    #: the runner always makes it the MQL5 vector, so "expected" here means
    #: "what the port under test was measured against".
    reference: Any
    candidate: Any
    #: Relative deviation for `NUMBER` leaves; `None` for the exact classes.
    observed: float | None = None
    tolerance: float | None = None

    def describe(self) -> str:
        """One line a human can act on, naming both values and the limit."""
        text = f"{self.path}: {self.kind} reference={self.reference!r} candidate={self.candidate!r}"
        if self.observed is not None and self.tolerance is not None:
            text += f" (relative deviation {self.observed:.3e} > {self.tolerance:.0e})"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "reference": self.reference,
            "candidate": self.candidate,
            "observed": self.observed,
            "tolerance": self.tolerance,
        }


@dataclass(frozen=True, slots=True)
class Comparison:
    """The result of comparing one pair of vectors."""

    differences: tuple[Difference, ...]
    #: Largest relative deviation across all `NUMBER` leaves, `None` when the
    #: vectors contain none. Present on a pass as well as a failure.
    max_deviation: float | None
    #: How many leaves were compared, so "compared 12 and they agreed" is
    #: distinguishable from "compared nothing".
    compared: int

    @property
    def agrees(self) -> bool:
        return not self.differences


def compare(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> Comparison:
    """Compare two canonical vectors field by field.

    `reference` is the side under test and `candidate` is what this repository
    produced; the runner passes them in that order. Both are the `vector` object
    of a sidecar, not the envelope.

    Raises `VectorError` if either vector has an undeclared leaf or a missing
    required one — a structural problem, which the caller turns into a case error
    rather than a mismatch. Note that a *count* difference between two lists is
    **not** a structural problem: it is a disagreement, and it is reported as one
    at the `*_count` leaf, along with the element the shorter side does not have.
    """
    ref = flatten(reference)
    cand = flatten(candidate)

    differences: list[Difference] = []
    worst: float | None = None

    # The union, so a path present on one side only becomes a difference naming
    # that path rather than being skipped. With everything else validated by
    # `flatten`, the only way to land here is a list of different lengths.
    for path in sorted(set(ref) | set(cand)):
        if path not in cand:
            differences.append(
                Difference(path, MISSING_IN_CANDIDATE, ref[path][1], None)
            )
            continue
        if path not in ref:
            differences.append(
                Difference(path, MISSING_IN_REFERENCE, None, cand[path][1])
            )
            continue

        ref_kind, ref_value = ref[path]
        cand_kind, cand_value = cand[path]
        if ref_kind != cand_kind:
            differences.append(
                Difference(path, TYPE_MISMATCH, ref_kind, cand_kind)
            )
            continue

        if _missing(ref_value) != _missing(cand_value):
            kind = MISSING_IN_CANDIDATE if _missing(cand_value) else MISSING_IN_REFERENCE
            differences.append(Difference(path, kind, ref_value, cand_value))
            continue

        if ref_kind in _NUMERIC and (_not_a_number(ref_value) or _not_a_number(cand_value)):
            differences.append(
                Difference(path, NOT_A_NUMBER, ref_value, cand_value)
            )
            continue

        if within_tolerance(ref_kind, ref_value, cand_value):
            observed = deviation(ref_kind, ref_value, cand_value)
            if observed is not None and (worst is None or observed > worst):
                worst = observed
            continue

        differences.append(
            Difference(
                path,
                MISMATCH,
                ref_value,
                cand_value,
                observed=deviation(ref_kind, ref_value, cand_value),
                tolerance=_tolerance_for(ref_kind, ref_value),
            )
        )

    return Comparison(tuple(differences), worst, len(ref))


def _tolerance_for(kind: str, value: Any = None) -> float | None:
    """The limit a leaf is measured against, or `None` when it has none.

    Value-dependent for `NUMBER`, and deliberately so: `within_tolerance` falls
    back to `ABSOLUTE_FLOOR` for a reference within `RELATIVE_TOLERANCE` of zero,
    and a report quoting the relative limit for a near-zero value would overstate
    the slack the comparison actually allowed.
    """
    if kind == NUMBER:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if abs(float(value)) <= RELATIVE_TOLERANCE:
                return ABSOLUTE_FLOOR
        return RELATIVE_TOLERANCE
    if kind in (EXACT_INT, EXACT_CODE, EXACT_BOOL, CODE_OR_NULL):
        return None
    raise VectorError(f"unknown comparison class {kind!r}")


def _missing(value: Any) -> bool:
    return value is None


def _not_a_number(value: Any) -> bool:
    """A leaf that is not a finite number, for a class that needs one.

    A `bool` counts as not-a-number here even though it is an `int`, because
    `isinstance(True, int)` is true in Python and a `true` where a bar index
    belongs is a type error worth naming rather than comparing.
    """
    if isinstance(value, bool):
        return True
    if not isinstance(value, (int, float)):
        return True
    return not math.isfinite(float(value))
