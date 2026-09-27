"""Domain types for measured moves.

Separated from `measured_move.py` so the data model can be imported without
pulling in the projection algorithms, and so Phase 11 (fading) can depend on the
model without depending on how projections are computed. That direction of
dependency is required: FM consumes MeasuredMove, never the reverse.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MeasuredMoveLeg:
    """The leg a measured move measures from.

    For swing families this is the `A0 -> A1` impulse. For `RANGE` it is the
    range window; for `GAP` it is the gap itself. The `kind` field records which,
    because "reference leg" means different geometry in each case.
    """

    kind: str = "NONE"  # SWING, RANGE, GAP, INVERSE
    start_index: int = -1
    end_index: int = -1
    start_price: float = 0.0
    end_price: float = 0.0
    direction: int = 0
    size: float = 0.0
    confirmed_index: int = -1
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MeasuredMoveOrigin:
    """Where a measured move is measured from."""

    bar_index: int = -1
    price: float = 0.0
    kind: str = "NONE"  # SWING, RANGE_CLOSE, GAP_CLOSE, FAILURE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MeasuredMoveEvidence:
    """One contributing factor behind a projection's confidence.

    `weight` is a relative contribution in 0..1, **not** a probability. A
    projection with three factors of 0.3 each is not "90% likely".
    """

    code: str
    weight: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
