"""The setup evidence model: one shape for five incompatible vocabularies.

## The problem

Every layer that reports a finding reports *why* it fired, in its own words:

| Source | Its own evidence |
|---|---|
| Market state | a list of `CODE: detail` strings, no weight |
| Measured move | `MeasuredMoveEvidence(code, weight, detail)`, weighted 0..1 |
| Reversal | satisfied / missing leg codes, plus a 0-100 count |
| Pullback | a lifecycle `state` (`CANDIDATE`..`INVALIDATED`) |
| Breakout | an `outcome` plus two booleans (`trap`, `second_leg_trap`) |

These are not variants of one thing. A weighted measurement, a satisfied-leg
list, and a state-machine position are three different kinds of claim, and the
five do not even agree on whether a weight exists. `Analyzer._evidence()` already
flattens them into one list, and that list is close to useless: four of the five
sources contribute entries with **no `weight` key at all**, so a consumer cannot
ask "how strong is this" without a `dict.get` that silently returns `None`.

## What a factor is, and the part that matters

`EvidenceFactor` normalises the *identity* of an observation: its source, its
stable code, a weight in 0..1, and a human-readable detail.

The load-bearing field is `basis`, which records **why that number exists**:

| Basis | Meaning | Example |
|---|---|---|
| `MEASURED` | computed from the data | `MM_SCALE`, range height in ATR |
| `LIFECYCLE` | a position in a state machine | pullback `CONFIRMED` |
| `ASSERTED` | present, with no magnitude | `RANGE_TIGHTENING_COMPRESSION` |

This distinction exists because a number without a basis is a lie waiting to
happen. `CONFIRMED` is not "0.75 confirmed" — it is one of four discrete
positions, and scoring it as though it sat on a 0..1 continuum would invent a
precision the state machine does not have. Equally, `ASSERTED` must not be
recorded as `0.0`, which would read as "measured, and came out zero" and would
silently drag an aggregate down.

A consumer that wants only measured evidence can therefore filter on `basis`
instead of guessing which numbers are load-bearing.

## Why presence is not a weight

`ASSERTED` factors are given `UNQUANTIFIED_WEIGHT`, and flagged. They are
*present*, which is information, but they carry no magnitude. A bundle reports
`quantified_share` so a caller can see how much of its evidence is actually
measured, rather than discovering that its "score" was mostly a list of
observations it could have predicted from a single flag.

## What this is not

No number here is a probability, a win rate, or a confidence interval. Nothing
in this project has been calibrated against outcomes, and
`docs/architecture/CONCEPT_TAXONOMY.md` §6 requires the word "evidence score"
rather than "confidence" for exactly this reason. A `strength` of 0.8 means "the
factors behind this reading were, on average, at 0.8 of their own scale" — not
"this happens 80% of the time".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator


class EvidenceBasis(str, Enum):
    """Why a factor's weight is the number it is.

    Recorded per factor so an aggregate is never a blend of measured magnitudes
    and bare assertions without the caller being able to tell.
    """

    #: Computed from the price data against a documented scale.
    MEASURED = "MEASURED"
    #: A discrete position in a state machine, not a point on a continuum.
    LIFECYCLE = "LIFECYCLE"
    #: Present, with no magnitude to report.
    ASSERTED = "ASSERTED"

    def to_dict(self) -> str:
        return self.value


#: Weight given to a factor that is present but unquantified.
#:
#: Not 0.0: a zero would claim the factor was measured and came out nil, and
#: would drag any average down as though it were a negative observation.
#: Not 1.0: that would rank a bare observation above a weak measurement.
#: A documented midpoint, flagged as `ASSERTED` so no consumer is misled.
UNQUANTIFIED_WEIGHT: float = 0.5


def clamp01(value: float) -> float:
    """Clamp to the closed unit interval, mapping NaN to 0.0.

    Mirrors the measured-move helper. A NaN would compare False against 0 and
    then poison an average while still passing a `> 0` check.
    """
    if value != value:  # NaN
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass(frozen=True, slots=True)
class EvidenceFactor:
    """One observation behind a finding, normalised to a uniform shape."""

    #: Which layer produced it: `MARKET_STATE`, `MEASURED_MOVE`, `REVERSAL`, ...
    source: str
    #: The layer's own stable code, passed through unchanged.
    code: str
    #: Relative contribution in 0..1. **Not** a probability.
    weight: float = UNQUANTIFIED_WEIGHT
    #: Why this number is the number it is.
    basis: EvidenceBasis = EvidenceBasis.ASSERTED
    #: Optional subtype, e.g. the measured-move family or a pullback's state.
    family: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "weight", clamp01(self.weight))

    @property
    def is_quantified(self) -> bool:
        """True when the weight is a measured magnitude, not an assertion."""
        return self.basis is EvidenceBasis.MEASURED

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "code": self.code,
            "weight": self.weight,
            "basis": self.basis.to_dict(),
            "family": self.family,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Every factor behind one subject, plus the caveats on reading them.

    `subject` names what the evidence is about (`"REVERSAL_BULL"`,
    `"MEASURED_MOVE:RANGE"`), so a consumer holding several bundles can tell
    them apart without depending on iteration order.
    """

    subject: str
    direction: int = 0
    factors: tuple[EvidenceFactor, ...] = ()
    #: Caveats about *reading* this evidence, distinct from the evidence itself.
    warnings: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.factors)

    def __iter__(self) -> Iterator[EvidenceFactor]:
        return iter(self.factors)

    def by_source(self) -> dict[str, list[EvidenceFactor]]:
        """Factors grouped by source, in first-seen order."""
        out: dict[str, list[EvidenceFactor]] = {}
        for factor in self.factors:
            out.setdefault(factor.source, []).append(factor)
        return out

    def codes(self) -> list[str]:
        return [f.code for f in self.factors]

    @property
    def quantified_share(self) -> float:
        """Share of factors that carry a measured magnitude.

        1.0 when every factor is `MEASURED`, 0.0 when none is. A bundle with no
        factors at all returns 0.0 rather than dividing by zero — an empty
        bundle has no measured evidence in it, which is the honest reading.
        """
        if not self.factors:
            return 0.0
        return sum(1 for f in self.factors if f.is_quantified) / len(self.factors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "direction": self.direction,
            "factors": [f.to_dict() for f in self.factors],
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------
# Adapters: one per source vocabulary
# --------------------------------------------------------------------------


def from_measured_move(projection: Any) -> list[EvidenceFactor]:
    """Normalise a `MeasuredMoveProjection`'s own evidence.

    The measured-move engine already weights its factors, so they arrive as
    `MEASURED` and are passed through unchanged. The projection's `confidence`
    is deliberately **not** re-used: it is the mean of these same weights, and
    recomputing it from the factors is what keeps the scalar reproducible from
    its own evidence rather than able to drift away from it.
    """
    out: list[EvidenceFactor] = []
    for item in getattr(projection, "evidence", ()) or ():
        out.append(
            EvidenceFactor(
                source="MEASURED_MOVE",
                code=item.code,
                weight=item.weight,
                basis=EvidenceBasis.MEASURED,
                family=str(getattr(projection, "family", "")),
                detail=item.detail,
            )
        )
    return out


def _parse_numeric_detail(detail: str) -> tuple[float, EvidenceBasis]:
    """Read a trailing number out of a detail string, if there is one.

    Only the *last* token is considered, and only if it parses as a float, so a
    detail like `"closed 0.8 beyond the edge"` is not read as the number 0.8.
    """
    if not detail:
        return UNQUANTIFIED_WEIGHT, EvidenceBasis.ASSERTED
    last = detail.split()[-1].rstrip(".,;:%")
    try:
        value = float(last)
    except ValueError:
        return UNQUANTIFIED_WEIGHT, EvidenceBasis.ASSERTED
    return clamp01(value), EvidenceBasis.MEASURED


def from_market_state(state: Any) -> list[EvidenceFactor]:
    """Normalise market-state evidence, which is `CODE: detail` with no weight.

    A trailing number in the detail is read as the magnitude when there is one
    (`STRONG_EMA_TREND_SLOPE: 1.00`), and the factor is then `MEASURED`. A code
    with no number (`RANGE_TIGHTENING_COMPRESSION`) is a bare observation and
    stays `ASSERTED`.

    The difference is worth keeping: a slope of 1.00 and the presence of
    compression are not the same kind of claim, and flattening both to a
    midpoint would discard the distinction the market-state engine drew.
    """
    out: list[EvidenceFactor] = []
    for line in getattr(state, "evidence", ()) or ():
        code, _, detail = str(line).partition(":")
        detail = detail.strip()
        weight, basis = _parse_numeric_detail(detail)
        out.append(
            EvidenceFactor(
                source="MARKET_STATE",
                code=code.strip(),
                weight=weight,
                basis=basis,
                detail=detail,
            )
        )
    return out


def from_reversal(quality: Any) -> list[EvidenceFactor]:
    """Normalise a `ReversalQuality`'s satisfied legs.

    Each leg becomes a factor at full weight: a leg is either satisfied or it is
    not, so `MEASURED` would be a lie and a graded weight would be meaningless.
    The `LIFECYCLE` basis is what says that, and the count is left to the
    aggregate rather than being encoded in the weights.

    `verdict` is carried as a factor too, because "MAJOR" is a real observation
    about the bundle even though it is a conclusion drawn from the legs.
    """
    out: list[EvidenceFactor] = []
    direction = int(getattr(quality, "direction", 0) or 0)
    for code in getattr(quality, "satisfied", ()) or ():
        out.append(
            EvidenceFactor(
                source="REVERSAL",
                code=str(code),
                weight=1.0,
                basis=EvidenceBasis.LIFECYCLE,
                detail="leg satisfied",
            )
        )
    verdict = str(getattr(quality, "verdict", "NONE"))
    if verdict != "NONE":
        out.append(
            EvidenceFactor(
                source="REVERSAL",
                code=f"VERDICT_{verdict}",
                weight=1.0,
                basis=EvidenceBasis.LIFECYCLE,
                detail=f"{verdict} reversal, direction {direction:+d}",
            )
        )
    return out


#: Lifecycle states, ordered weakest-first.
#:
#: A pullback's state is a position in a documented state machine, so the
#: ordering is taken from the state machine rather than invented. The
#: positions are given evenly spaced values so a bundle's aggregate is stable
#: and reproducible, NOT because the gaps between them are meaningful: a
#: `PROVISIONAL` pullback is not "twice as provisional" as a `CANDIDATE` one.
_PULLBACK_LIFECYCLE: dict[str, float] = {
    "CANDIDATE": 1 / 3,
    "PROVISIONAL": 2 / 3,
    "CONFIRMED": 1.0,
}


def from_pullback(payload: dict[str, Any]) -> list[EvidenceFactor]:
    """Normalise a pullback's lifecycle position.

    `INVALIDATED` is deliberately **excluded**. It is a negative observation, and
    folding it in as a low weight would make an invalidated setup look like a
    weak one rather than a dead one — the difference between "scored badly" and
    "not a candidate" is exactly the distinction a caller must not lose.

    The caller is expected to have filtered on `found`; this returns an empty
    list for an invalidated state rather than inventing a score for it.
    """
    state = str(payload.get("state", ""))
    weight = _PULLBACK_LIFECYCLE.get(state)
    if weight is None:
        return []
    return [
        EvidenceFactor(
            source="PULLBACK",
            code=state,
            weight=weight,
            basis=EvidenceBasis.LIFECYCLE,
            family=str(payload.get("family", "")),
            detail=str(payload.get("setup_type", "")),
        )
    ]


#: Breakout outcomes that represent a completed, still-valid observation.
#:
#: `FAILED` is excluded for the same reason `INVALIDATED` is: a failed breakout
#: is not a weak breakout, it is the opposite one.
_BREAKOUT_POSITIVE: dict[str, float] = {
    "FOLLOW": 1.0,
    "PENDING": 0.5,
}


def from_breakout(payload: dict[str, Any]) -> list[EvidenceFactor]:
    """Normalise a breakout's outcome and trap flags."""
    out: list[EvidenceFactor] = []
    outcome = str(payload.get("outcome", ""))
    weight = _BREAKOUT_POSITIVE.get(outcome)
    if weight is not None:
        out.append(
            EvidenceFactor(
                source="BREAKOUT",
                code=f"OUTCOME_{outcome}",
                weight=weight,
                basis=EvidenceBasis.LIFECYCLE,
                detail=f"breakout outcome {outcome}",
            )
        )
    # Both traps are adverse observations about a breakout. They are recorded as
    # factors rather than subtracted, so a bundle is never a number that had
    # things taken away from it — the aggregate is always a mean of what was
    # observed, and the codes say what was observed.
    for flag, code in (
        ("trap", "BREAKOUT_TRAP"),
        ("second_leg_trap", "SECOND_LEG_TRAP"),
    ):
        if payload.get(flag):
            out.append(
                EvidenceFactor(
                    source="BREAKOUT",
                    code=code,
                    weight=1.0,
                    basis=EvidenceBasis.ASSERTED,
                    detail="adverse flag against the breakout",
                )
            )
    return out


#: Every source this module knows how to normalise.
KNOWN_SOURCES: tuple[str, ...] = (
    "MARKET_STATE",
    "MEASURED_MOVE",
    "REVERSAL",
    "PULLBACK",
    "BREAKOUT",
)
