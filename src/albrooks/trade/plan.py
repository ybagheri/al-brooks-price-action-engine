"""Platform-independent trade plans: the geometry of a *hypothetical* trade.

## What a plan is

A `TradePlan` is the arithmetic of one imagined position: an entry, a stop, a
target, and the distance between them. That is all. It is the layer the
architecture diagram puts between setup evaluation and the decision engine, and
it is deliberately the narrowest layer in the project.

## What a plan is not

It is **not a recommendation**, and this module makes that a field of the output
rather than a sentence in a docstring — `to_dict()` carries
`"is_recommendation": false`. A plan exists for a reader who already has a
reading of the market and wants the geometry checked; it does not select which
reading to act on, and it does not claim that the resulting trade has an edge.
Nothing in this project has been calibrated against outcomes
(`docs/architecture/CONCEPT_TAXONOMY.md` §5), so there is no expected value here
to report, and `reward_to_risk` is arithmetic rather than a forecast of anything.

It is also **not an order**. There is no order type, no lot size, no position
sizing, no slippage and no session filter anywhere in this file. Order types and
sizing belong to the execution layer (Phase 21), and sizing in particular
requires an account risk policy this project does not have and does not want to
invent. See `ROADMAP.md` → *Deliberately Not Built*.

## Every level carries a basis, and that is the load-bearing idea

This is Phase 13's `basis` field applied to prices. A stop at `101.20` means
something different depending on where it came from:

| `stop_basis` | What it claims |
|---|---|
| `PULLBACK_EXTREME` | the low the pullback was built on, plus a buffer |
| `BREAKOUT_REFERENCE` | the level that was broken, plus a buffer |
| `PATTERN_EXTREME` | the adverse extreme of a double top / bottom, plus a buffer |
| `SWING` | the most recent confirmed swing against the trade, plus a buffer |
| `ATR_FALLBACK` | **nothing structural at all** — one volatility multiple away |

The last row is the one that matters. When a setup carries no level of its own
the engine still produces a stop, because a plan without a stop is not a plan —
and that stop is a *fallback*, not a structural claim. Recording which it is
means a reader is never left assuming a volatility multiple was a swing low. A
fallback level also raises a warning, so it cannot pass unnoticed either.

## Issues are arithmetic; warnings are judgement-adjacent

`issues` holds only statements that are false about the numbers: a stop that is
not on the protective side of the entry, a target that is not ahead of it, zero
risk, no ATR, no direction. Those are facts, and a plan carrying one has
`is_valid == False`. The three that are decidable from entry, stop, target and
direction alone are added by `TradePlan.__post_init__` rather than by the
builder, so a plan cannot be assembled that omits them.
`warnings` holds everything this layer noticed but deliberately did not act on —
a wide stop, a `FAILED` breakout, a projected target that sat behind the entry.
**Gating on them is the decision engine's job** (`albrooks.decision`, Phase 15).
This layer reports geometry; it does not decide which geometry is worth taking,
and adding a `min_rr` gate here would be doing the decision engine's work without
the explanation machinery that makes its output auditable.


## One builder, a table of anatomies

The setup families record their geometry in incompatible places: a pullback
carries `stop_price` and `reference_price`, a measured move keeps its origin
nested under `origin.price`, a fading setup's *trade* direction is
`fade_direction` rather than `direction`, and a reversal carries no prices at
all. Writing five builders would duplicate the level-derivation algorithm five
times, which `CONTRIBUTING.md` rule 5 forbids.

Instead `SetupAnatomy` is a row of **data** saying where a family's fields live,
and `build_trade_plan()` is the single algorithm that reads it. Adding a family
is a table entry, exactly as Phase 12 made adding a detector a `register()`
call. Dotted paths are supported so a nested field such as
`projection.origin.price` is addressable without anybody flattening a payload for
this module's benefit.

## The closed-bar contract

`build_trade_plan()` reads bars `0..bar_index` and nothing after it: the entry
fallback is the close at `bar_index`, and a swing is only usable when its
`confirmed_bar_index` is at or before `bar_index`. `bar_index` is clamped rather
than rejected, matching every detector in the engine. The invariant is asserted
in `tests/unit/test_phase14_trade_plan.py`: the plan for a given bar is identical
whether or not later bars exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.base import FAMILY_BY_DETECTOR, family_for

# --------------------------------------------------------------------------
# Bases: why a price is the number it is
# --------------------------------------------------------------------------

#: A level the setup itself recorded, plus a volatility buffer.
STOP_BASIS_PULLBACK_EXTREME = "PULLBACK_EXTREME"
STOP_BASIS_BREAKOUT_REFERENCE = "BREAKOUT_REFERENCE"
STOP_BASIS_PATTERN_EXTREME = "PATTERN_EXTREME"
#: The most recent confirmed swing against the trade, plus a buffer.
STOP_BASIS_SWING = "SWING"
#: **No structural claim.** One volatility multiple from the entry.
STOP_BASIS_ATR = "ATR_FALLBACK"
STOP_BASIS_NONE = "NONE"

#: A measured-move projection's own target.
TARGET_BASIS_MEASURED_MOVE = "MEASURED_MOVE"
#: Where the projected move started, which is what a fade is aiming back at.
TARGET_BASIS_FADE_ORIGIN = "FADE_ORIGIN"
#: The most recent confirmed swing in the trade's direction.
TARGET_BASIS_SWING = "SWING"
#: **No structural claim.** One volatility multiple from the entry.
TARGET_BASIS_ATR = "ATR_FALLBACK"
TARGET_BASIS_NONE = "NONE"

#: The entry price a setup itself recorded (its reference, origin or level).
ENTRY_BASIS_SETUP = "SETUP_REFERENCE"
#: The close of the bar the plan is built on, because the setup named no price.
ENTRY_BASIS_LAST_CLOSE = "LAST_CLOSE"
ENTRY_BASIS_NONE = "NONE"

# --------------------------------------------------------------------------
# Issues: statements that are false about the arithmetic
# --------------------------------------------------------------------------

ISSUE_NO_DIRECTION = "NO_DIRECTION"
ISSUE_NO_ATR = "NO_ATR"
ISSUE_ENTRY_UNDEFINED = "ENTRY_UNDEFINED"
ISSUE_STOP_UNDEFINED = "STOP_UNDEFINED"
ISSUE_STOP_NOT_PROTECTIVE = "STOP_NOT_PROTECTIVE"
ISSUE_TARGET_UNDEFINED = "TARGET_UNDEFINED"
ISSUE_TARGET_NOT_AHEAD = "TARGET_NOT_AHEAD"
ISSUE_RISK_NOT_POSITIVE = "RISK_NOT_POSITIVE"

#: Every issue is blocking. The set exists so `is_valid` is defined by a list
#: rather than by a judgement made at the point of use: a caller that needs a
#: softer rule can read `issues` and choose.
BLOCKING_ISSUES: frozenset[str] = frozenset(
    {
        ISSUE_NO_DIRECTION,
        ISSUE_NO_ATR,
        ISSUE_ENTRY_UNDEFINED,
        ISSUE_STOP_UNDEFINED,
        ISSUE_STOP_NOT_PROTECTIVE,
        ISSUE_TARGET_UNDEFINED,
        ISSUE_TARGET_NOT_AHEAD,
        ISSUE_RISK_NOT_POSITIVE,
    }
)

# --------------------------------------------------------------------------
# Warnings: noticed, reported, deliberately not acted on
# --------------------------------------------------------------------------

#: A level that had to be invented from volatility, because the setup named none.
WARN_VOLATILITY_FALLBACK_STOP = "VOLATILITY_FALLBACK_STOP"
WARN_VOLATILITY_FALLBACK_TARGET = "VOLATILITY_FALLBACK_TARGET"
#: Risk exceeds `plan_max_stop_atr`. Reported, not vetoed — the decision engine
#: reads this, and gating is a trade decision rather than an arithmetic one.
WARN_STOP_WIDE = "STOP_WIDE"
#: A projected target sat behind the entry and was dropped for another level.
WARN_TARGET_DROPPED = "PROJECTED_TARGET_BEHIND_ENTRY"
#: The setup has reached a terminal negative state (a failed breakout, an
#: invalidated lifecycle). The geometry is still reported, because reporting it
#: and acting on it are different questions.
WARN_TERMINAL_SETUP = "TERMINAL_SETUP_STATE"
#: An evidence score was attached. It is a mean of factor weights, not a
#: probability, and the plan says so in its own output rather than trusting the
#: caller to remember.
WARN_EVIDENCE_NOT_A_PROBABILITY = "EVIDENCE_SCORE_IS_NOT_A_PROBABILITY"

#: Standing caveat for a family that cannot make a claim it would like to make.
#: Kept as data on the anatomy so a family's blind spot travels with its plans.
NOTE_DOUBLE_TARGET_NOT_MEASURED = (
    "DOUBLE_TARGET_NOT_MEASURED: a double top/bottom's own measured target needs "
    "the neckline-to-extreme height, which DoublePattern does not record. The "
    "target here is a swing or a volatility multiple, never a double target."
)
NOTE_REVERSAL_HAS_NO_LEVELS = (
    "REVERSAL_HAS_NO_LEVELS: a reversal is a checklist of satisfied legs, not a "
    "price structure. Every level here is derived, and the stop is not a swing "
    "the detector identified."
)
NOTE_PLAN_IS_NOT_A_RECOMMENDATION = (
    "Geometry, not advice. Whether this trade is worth taking is the decision "
    "layer's question, and nothing in this project has been validated against "
    "outcomes."
)


# --------------------------------------------------------------------------
# Payload reading
# --------------------------------------------------------------------------


def _dig(payload: Mapping[str, Any], path: str) -> Any:
    """Read a dotted path out of a payload, or None if any step is missing.

    Dotted paths exist so a nested field can be addressed without anybody having
    to flatten a payload for this module's benefit. Only mappings are traversed:
    a detector that returned something else where a mapping was expected yields
    None rather than raising inside somebody else's report.
    """
    node: Any = payload
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _as_float(raw: Any) -> float | None:
    """A finite, strictly positive float, or None.

    `0.0` is rejected on purpose. Every model in this engine uses `0.0` as the
    "not observed" default for a price — `PullbackSetup.reference_price`,
    `BreakoutResult.reference_price`, `DoublePattern.price1` — so accepting it
    would read a placeholder as a level. A price of zero is not a market either,
    which makes the same test correct on the merits.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value if value > 0.0 else None


def _as_index(raw: Any) -> int:
    """A bar index, or `-1`.

    Negative values are kept rather than replaced, because the models use `-1`
    for "no bar" and `0` is a perfectly real index.
    """
    if raw is None or isinstance(raw, bool):
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


def _first_price(payload: Mapping[str, Any], keys: Sequence[str]) -> tuple[float, str] | None:
    """The first key in `keys` carrying a usable price, and the key itself.

    Ordered by specificity, so `("origin.price", "reference_price")` prefers the
    origin over the wider reference. The key that won is reported, because a
    reader checking a plan needs to know which of a setup's numbers the level came
    from.
    """
    for key in keys:
        value = _as_float(_dig(payload, key))
        if value is not None:
            return value, key
    return None


def _first_index(payload: Mapping[str, Any], keys: Sequence[str]) -> int:
    for key in keys:
        index = _as_index(_dig(payload, key))
        if index >= 0:
            return index
    return -1


# --------------------------------------------------------------------------
# Swings
# --------------------------------------------------------------------------


def _swing_fields(swing: Any) -> tuple[int, float, int]:
    """`(confirmed_index, price, direction)` for a `SwingPoint` or its dict.

    Both spellings of the index are read. `SwingPoint.to_dict()` emits
    `bar_index`, while several call sites pass dicts using the older `bar`, and a
    plan that silently skipped half the engine's swings would look like a market
    with no structure at all.
    """
    if isinstance(swing, SwingPoint):
        return swing.confirmed_bar_index, swing.price, swing.direction
    if isinstance(swing, Mapping):
        confirmed = _dig(swing, "confirmed_bar_index")
        if confirmed is None:
            confirmed = _dig(swing, "bar")
        if confirmed is None:
            confirmed = _dig(swing, "bar_index")
        return (
            _as_index(confirmed),
            _as_float(_dig(swing, "price")) or 0.0,
            _as_index(_dig(swing, "direction")),
        )
    return -1, 0.0, 0


def _swing_reference(
    swings: Iterable[Any], direction: int, entry: float, bar_index: int
) -> float | None:
    """The most recent confirmed swing that could hold a level, else None.

    For a long that is the newest confirmed swing **low below the entry**; for a
    short, the newest confirmed swing **high above it**. Confirmation must be at
    or before `bar_index`, which is what keeps a right-side-confirmed fractal out
    of a plan dated before its own evidence existed.
    """
    found: float | None = None
    for swing in swings:
        confirmed, price, swing_direction = _swing_fields(swing)
        if confirmed < 0 or confirmed > bar_index or price <= 0.0:
            continue
        if direction > 0 and swing_direction < 0 and price < entry:
            found = price
        elif direction < 0 and swing_direction > 0 and price > entry:
            found = price
    return found


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradePlan:
    """Entry, stop, target, and the arithmetic between them.

    Every one of the three prices carries a `*_basis`, because a price without a
    stated origin is exactly the kind of number this project refuses to emit. The
    object is immutable and slotted like every other domain model here, and
    `to_dict()` is what a consumer reads.
    """

    #: What the plan is about, e.g. `PULLBACK_H`. Never an order identifier.
    subject: str
    #: `+1` long, `-1` short, `0` when the setup named no direction.
    direction: int = 0
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    entry_basis: str = ENTRY_BASIS_NONE
    stop_basis: str = STOP_BASIS_NONE
    target_basis: str = TARGET_BASIS_NONE
    #: The structural level each price was derived from; 0.0 when there was none.
    entry_reference: float = 0.0
    stop_reference: float = 0.0
    target_reference: float = 0.0
    #: Newest bar the plan may read. Every level above comes from `0..bar_index`
    #: only, which is what makes a plan dateable.
    bar_index: int = -1
    #: Bar the underlying setup fired on, -1 when the family records none.
    signal_bar: int = -1
    #: Plain-language statement of what would void the reading behind the plan.
    invalidation: str = ""
    #: Notes for whoever would act on this. Descriptive, never imperative.
    management: tuple[str, ...] = ()
    #: Statements that are false about the arithmetic. Non-empty => not valid.
    #: The builder supplies the contextual ones; `__post_init__` adds the three
    #: that the numbers themselves settle.
    issues: tuple[str, ...] = ()
    #: Statements that were noticed and deliberately not acted on.
    warnings: tuple[str, ...] = ()
    #: An evidence score passed in from Phase 13. **Never computed here** — a
    #: plan does not aggregate evidence — and not a probability when supplied.
    evidence_score: float | None = None

    def __post_init__(self) -> None:
        # Direction is normalised to its sign, matching `setups.base`, so a
        # detector reporting 1/-1 and one reporting 100/-100 give the same
        # geometry. Anything that is not a direction becomes 0, which
        # `NO_DIRECTION` reports.
        raw = self.direction
        direction = (raw > 0) - (raw < 0)
        object.__setattr__(self, "direction", direction)
        # The three *geometric* issues are read off the numbers here rather than
        # asserted by the builder, so a `TradePlan` assembled by hand — by a
        # caller, a future layer, or a test — cannot claim valid geometry it does
        # not have. `issues` supplied by the builder carries only the contextual
        # ones, which genuinely need the inputs to judge.
        object.__setattr__(
            self,
            "issues",
            tuple(dict.fromkeys((*self.issues, *self._geometric_issues(direction)))),
        )

    def _geometric_issues(self, direction: int) -> tuple[str, ...]:
        """Issues decidable from entry, stop, target and direction alone.

        A level of `0.0` means "undefined" and is skipped rather than compared:
        `STOP_UNDEFINED` is the builder's statement about it, and testing a
        missing stop for being on the wrong side of the entry would report the
        same thing twice.
        """
        out: list[str] = []
        if direction == 0:
            return ()
        away = 1.0 if direction > 0 else -1.0
        if self.entry > 0.0 and self.stop > 0.0:
            if (self.entry - self.stop) * away < 0.0:
                out.append(ISSUE_STOP_NOT_PROTECTIVE)
            if self.risk == 0.0:
                out.append(ISSUE_RISK_NOT_POSITIVE)
        if self.entry > 0.0 and self.target > 0.0 and (self.target - self.entry) * away <= 0.0:
            out.append(ISSUE_TARGET_NOT_AHEAD)
        return tuple(out)

    # -- geometry --------------------------------------------------------

    @property
    def is_long(self) -> bool:
        return self.direction > 0

    @property
    def is_short(self) -> bool:
        return self.direction < 0

    @property
    def risk(self) -> float:
        """Distance from entry to stop, per unit. Never negative.

        A stop on the wrong side of the entry yields a positive number here and
        `STOP_NOT_PROTECTIVE` in `issues`. The distance is reported as measured
        and the plan marked invalid, rather than corrected: substituting a
        different stop would hide what the setup actually said.
        """
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        """Distance from entry to target, per unit. Never negative."""
        return abs(self.target - self.entry)

    @property
    def reward_to_risk(self) -> float:
        """`reward / risk` — the ratio conventionally called R:R.

        `0.0` when `risk` is 0, because the ratio is undefined there and
        `inf` would travel into JSON as a non-standard literal. Such a plan
        carries `RISK_NOT_POSITIVE` and is not valid.
        """
        return self.reward / self.risk if self.risk > 0.0 else 0.0

    @property
    def risk_to_reward(self) -> float:
        """`risk / reward`. Named explicitly, and separately from the ratio
        above, so no caller has to guess which convention a bare number uses."""
        return self.risk / self.reward if self.reward > 0.0 else 0.0

    @property
    def is_valid(self) -> bool:
        """False when any issue is present.

        This is arithmetic, not approval. A valid plan is one whose entry, stop
        and target are on the correct sides of each other, and nothing more.
        """
        return not any(issue in BLOCKING_ISSUES for issue in self.issues)

    @property
    def has_structural_stop(self) -> bool:
        """Whether the stop is derived from something the market actually did.

        A caller filtering for plans worth reading should test this rather than
        `is_valid`: a valid plan on an `ATR_FALLBACK` stop is arithmetically
        sound and structurally empty.
        """
        return self.stop_basis not in (STOP_BASIS_ATR, STOP_BASIS_NONE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "direction": self.direction,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "entry_basis": self.entry_basis,
            "stop_basis": self.stop_basis,
            "target_basis": self.target_basis,
            "entry_reference": self.entry_reference,
            "stop_reference": self.stop_reference,
            "target_reference": self.target_reference,
            "bar_index": self.bar_index,
            "signal_bar": self.signal_bar,
            "risk": self.risk,
            "reward": self.reward,
            "reward_to_risk": self.reward_to_risk,
            "risk_to_reward": self.risk_to_reward,
            "is_valid": self.is_valid,
            "has_structural_stop": self.has_structural_stop,
            "invalidation": self.invalidation,
            "management": list(self.management),
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "evidence_score": self.evidence_score,
            "is_recommendation": False,
        }


# --------------------------------------------------------------------------
# Anatomy: where a family keeps its geometry
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SetupAnatomy:
    """Where one setup family's trade geometry lives inside its own payload.

    This is the reason there is one builder and not five. Every key is a dotted
    path, tried in order, and the first that carries a usable value wins.

    `stop_extreme_keys` is separate from `stop_keys` because a double top and a
    double bottom need the *adverse extreme* of two numbers rather than one of
    them: for a long the reference is the **minimum** across the keys, for a
    short the **maximum**. That is what a pattern's stop actually is; flattening
    it to a single field would have meant using `price1` on a long and `price2`
    on a short for reasons no reader could reconstruct.
    """

    family: str
    #: Checked in order. `fade_direction` leads for fades because a
    #: `FadingSetup`'s `direction` is the *projection's*, and taking a trade in
    #: the direction of the move one is fading is the easiest way to be wrong.
    direction_keys: tuple[str, ...] = ("direction",)
    entry_keys: tuple[str, ...] = ()
    stop_keys: tuple[str, ...] = ()
    stop_extreme_keys: tuple[str, ...] = ()
    stop_basis: str = STOP_BASIS_ATR
    target_keys: tuple[str, ...] = ()
    target_basis: str = TARGET_BASIS_ATR
    signal_keys: tuple[str, ...] = ("signal_bar",)
    #: Level whose breach would void the reading behind the plan, if the family
    #: records one in its payload.
    invalidation_keys: tuple[str, ...] = ()
    #: Standing caveats this family always carries, whatever the numbers came out
    #: as. A family's blind spot is a property of the family, not of one run.
    notes: tuple[str, ...] = ()


#: One row per setup family the engine detects. Adding a family is a row here
#: and not a new builder — the same one-change rule `ARCHITECTURE.md` §9 states
#: for setup detectors.
ANATOMY_BY_FAMILY: dict[str, SetupAnatomy] = {
    "PULLBACK": SetupAnatomy(
        family="PULLBACK",
        entry_keys=("reference_price",),
        stop_keys=("stop_price",),
        stop_basis=STOP_BASIS_PULLBACK_EXTREME,
        signal_keys=("signal_bar",),
        invalidation_keys=("extreme_price",),
    ),
    "BREAKOUT": SetupAnatomy(
        family="BREAKOUT",
        # No entry key on purpose: a breakout is entered *on the break*, and its
        # reference is a level price is leaving rather than one it trades at.
        # The entry falls back to the close and says so via LAST_CLOSE.
        stop_keys=("reference_price",),
        stop_basis=STOP_BASIS_BREAKOUT_REFERENCE,
        signal_keys=("breakout_bar",),
        invalidation_keys=("reference_price",),
    ),
    "MEASURED_MOVE": SetupAnatomy(
        family="MEASURED_MOVE",
        entry_keys=("origin.price", "reference_price"),
        target_keys=("target_price",),
        target_basis=TARGET_BASIS_MEASURED_MOVE,
        signal_keys=("origin.bar_index",),
        invalidation_keys=("origin.price",),
    ),
    "FADING_MEASURED_MOVE": SetupAnatomy(
        family="FADING_MEASURED_MOVE",
        direction_keys=("fade_direction", "direction"),
        # A fade aims back at where the projected move started, which is the one
        # level the projection itself supplies.
        target_keys=("projection.origin.price",),
        target_basis=TARGET_BASIS_FADE_ORIGIN,
        signal_keys=("state_bar", "created_bar"),
        invalidation_keys=("projection.origin.price",),
    ),
    "REVERSAL": SetupAnatomy(
        family="REVERSAL",
        signal_keys=("cross_bar",),
        notes=(NOTE_REVERSAL_HAS_NO_LEVELS,),
    ),
    "DOUBLE_TOP": SetupAnatomy(
        family="DOUBLE_TOP",
        stop_extreme_keys=("price1", "price2"),
        stop_basis=STOP_BASIS_PATTERN_EXTREME,
        signal_keys=("bar2",),
        invalidation_keys=("level",),
        notes=(NOTE_DOUBLE_TARGET_NOT_MEASURED,),
    ),
    "DOUBLE_BOTTOM": SetupAnatomy(
        family="DOUBLE_BOTTOM",
        stop_extreme_keys=("price1", "price2"),
        stop_basis=STOP_BASIS_PATTERN_EXTREME,
        signal_keys=("bar2",),
        invalidation_keys=("level",),
        notes=(NOTE_DOUBLE_TARGET_NOT_MEASURED,),
    ),
}

#: The anatomy used when nothing more specific is known: no keys, so every level
#: is derived and the plan reports that it was.
DEFAULT_ANATOMY = SetupAnatomy(family="UNKNOWN")

#: Registry detector name -> anatomy family. Kept beside the anatomy table so a
#: detector and the way it is planned are declared in the same place. The mapping
#: itself is owned by `setups.base`, because the pipeline and the decision layer
#: need the same answer and a second copy would be a second thing to keep in step.
DETECTOR_FAMILIES: dict[str, str] = FAMILY_BY_DETECTOR


def anatomy_for(family: str) -> SetupAnatomy:
    """The row for `family`, or `DEFAULT_ANATOMY`.

    An unknown family is not an error. A third-party detector that registered
    itself should still be plannable, and a plan built from `DEFAULT_ANATOMY`
    says `entry_basis=LAST_CLOSE` and `stop_basis=ATR_FALLBACK` rather than
    refusing to describe the trade at all.
    """
    return ANATOMY_BY_FAMILY.get(family, DEFAULT_ANATOMY)


# --------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------


def _derive_entry(
    payload: Mapping[str, Any], anatomy: SetupAnatomy, series: BarSeries, bar_index: int
) -> tuple[float, str, float, list[str]]:
    """Entry price, its basis, the level it came from, and any issues."""
    found = _first_price(payload, anatomy.entry_keys)
    if found is not None:
        return found[0], ENTRY_BASIS_SETUP, found[0], []
    if 0 <= bar_index < len(series):
        close = series[bar_index].close
        return close, ENTRY_BASIS_LAST_CLOSE, close, []
    return 0.0, ENTRY_BASIS_NONE, 0.0, [ISSUE_ENTRY_UNDEFINED]


def _derive_stop(
    payload: Mapping[str, Any],
    anatomy: SetupAnatomy,
    direction: int,
    entry: float,
    atr: float,
    bar_index: int,
    swings: Sequence[Any],
    config: AnalyzerConfig,
    warnings: list[str],
) -> tuple[float, str, float]:
    """Stop price, its basis, and the level it was derived from.

    Order: the setup's own level, then the pattern's adverse extreme, then the
    most recent confirmed swing, then a volatility *distance*. Each step down is
    a weaker claim about *why* that price is the stop, which is why the basis
    changes with it and why the last step warns.

    Whether the resulting stop is actually on the protective side is not decided
    here — it is read off the numbers by `TradePlan.__post_init__`, so a plan
    cannot be built that omits the answer.
    """
    buffer = config.plan_stop_buffer_atr * atr if atr > 0.0 else 0.0
    away = 1.0 if direction > 0 else -1.0

    found = _first_price(payload, anatomy.stop_keys)
    reference = found[0] if found is not None else 0.0
    basis = anatomy.stop_basis

    if reference <= 0.0 and anatomy.stop_extreme_keys:
        extremes = [
            value
            for value in (
                _as_float(_dig(payload, key)) for key in anatomy.stop_extreme_keys
            )
            if value is not None
        ]
        if extremes:
            # A long is stopped below the *lowest* extreme, a short above the
            # highest. Taking the first, or averaging, would put the stop inside
            # the pattern.
            reference = min(extremes) if direction > 0 else max(extremes)

    if reference <= 0.0:
        swing = _swing_reference(swings, direction, entry, bar_index)
        if swing is not None:
            reference, basis = swing, STOP_BASIS_SWING

    if reference <= 0.0:
        if atr <= 0.0:
            return 0.0, STOP_BASIS_NONE, 0.0
        # The fallback is a volatility *distance*, not a volatility *buffer*.
        # Applying the buffer to the entry instead would make a 0.25 ATR stop,
        # which is the opposite of what `plan_fallback_stop_atr` means.
        warnings.append(WARN_VOLATILITY_FALLBACK_STOP)
        return entry - away * config.plan_fallback_stop_atr * atr, STOP_BASIS_ATR, 0.0

    return reference - away * buffer, basis, reference


def _derive_target(
    payload: Mapping[str, Any],
    anatomy: SetupAnatomy,
    direction: int,
    entry: float,
    atr: float,
    bar_index: int,
    swings: Sequence[Any],
    config: AnalyzerConfig,
    warnings: list[str],
) -> tuple[float, str, float]:
    """Target price, its basis, and the level it was derived from.

    Order: the setup's own projected level, then the most recent confirmed swing
    in the trade's direction, then a volatility multiple.

    A projected target *behind* the entry is dropped rather than used with a
    negative reward: it means the projection and the entry describe different
    things, which is a fact worth reporting rather than something to paper over
    by taking an absolute value.
    """
    ahead = 1.0 if direction > 0 else -1.0

    found = _first_price(payload, anatomy.target_keys)
    if found is not None and (found[0] - entry) * ahead > 0.0:
        return found[0], anatomy.target_basis, found[0]
    if found is not None:
        warnings.append(WARN_TARGET_DROPPED)

    # Negating the direction turns the stop-oriented swing search into the
    # target-oriented one: for a long, the newest confirmed swing *high* above
    # the entry.
    swing = _swing_reference(swings, -direction, entry, bar_index)
    if swing is not None:
        return swing, TARGET_BASIS_SWING, swing

    if atr <= 0.0:
        return 0.0, TARGET_BASIS_NONE, 0.0

    warnings.append(WARN_VOLATILITY_FALLBACK_TARGET)
    target = entry + ahead * config.plan_fallback_target_atr * atr
    return target, TARGET_BASIS_ATR, 0.0


def _invalidation_text(
    payload: Mapping[str, Any], anatomy: SetupAnatomy, stop_basis: str
) -> str:
    """What would void the reading behind this plan, in one sentence."""
    found = _first_price(payload, anatomy.invalidation_keys)
    if found is None or stop_basis in (STOP_BASIS_ATR, STOP_BASIS_NONE):
        return (
            "No structural level is available, so only the volatility stop "
            "defines this plan. There is no price at which the reading behind it "
            "is demonstrably void."
        )
    return (
        f"A close beyond {found[0]:g} ({found[1]}) is the level this plan was "
        f"built around; breaching it voids the structure behind the trade."
    )


def _management_notes(
    entry: float,
    entry_basis: str,
    stop: float,
    stop_basis: str,
    target: float,
    target_basis: str,
    risk: float,
    reward: float,
    ratio: float,
) -> tuple[str, ...]:
    """Descriptive notes about the levels. None of them is advice."""
    notes = [
        f"Entry {entry:g} ({entry_basis}), stop {stop:g} ({stop_basis}), "
        f"target {target:g} ({target_basis}).",
        f"Risk {risk:g} per unit against reward {reward:g}, reward:risk "
        f"{ratio:.2f}. That is arithmetic: not a probability, not an expected "
        f"value, and not a forecast.",
        NOTE_PLAN_IS_NOT_A_RECOMMENDATION,
    ]
    if stop_basis in (STOP_BASIS_ATR, STOP_BASIS_NONE):
        notes.append(
            "The stop is a volatility multiple, not a level the market produced. "
            "No swing or structure was available to place it behind."
        )
    return tuple(notes)


# --------------------------------------------------------------------------
# The builder
# --------------------------------------------------------------------------


def _direction_of(payload: Mapping[str, Any], keys: Sequence[str]) -> int:
    """The first key carrying a direction, normalised to `+1` / `-1` / `0`.

    Read as a number rather than through `_as_index`, because that helper returns
    `-1` for a missing field — and `-1` is a direction. A payload with no
    `direction` at all would otherwise produce a *short* plan, which is the kind
    of bug that only shows up as a plausible-looking number.
    """
    for key in keys:
        raw = _dig(payload, key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value != value or value == 0.0:
            continue
        return (value > 0) - (value < 0)
    return 0


def _is_terminal(payload: Mapping[str, Any]) -> bool:
    """Has the setup reached a state that ended it?

    Only the two terminal negatives the engine actually models are read, and the
    point is to *report* them. A failed breakout's geometry is still coherent
    arithmetic; whether a failed breakout deserves a plan is the decision
    engine's question, and answering it here would be answering it without the
    explanation machinery that makes such an answer auditable.
    """
    return str(_dig(payload, "state")) in ("INVALIDATED", "FAILED") or str(
        _dig(payload, "outcome")
    ) in ("FAILED", "INVALIDATED")


def build_trade_plan(
    subject: str,
    payload: Mapping[str, Any],
    *,
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    bar_index: int,
    atr: float,
    anatomy: SetupAnatomy | None = None,
    swings: Sequence[Any] = (),
    config: AnalyzerConfig | None = None,
    evidence_score: float | None = None,
) -> TradePlan:
    """Build one plan from one setup payload.

    `bar_index` is the newest bar the plan may read. It is clamped to the series
    and a negative value becomes an issue rather than an exception, because every
    other entry point in this engine behaves that way and a plan that raised
    would take down whatever was building it.

    The result is **not vetted for merit**. A plan with 0.4 reward:risk and a
    plan with 4.0 are the same object with different numbers; choosing between
    them is `albrooks.decision`'s work, and the warnings here say so.
    """
    cfg = config or AnalyzerConfig()
    anat = anatomy or DEFAULT_ANATOMY
    series = bars if isinstance(bars, BarSeries) else BarSeries(bars)

    issues: list[str] = []
    warnings: list[str] = list(anat.notes)

    direction = _direction_of(payload, anat.direction_keys)
    if direction == 0:
        issues.append(ISSUE_NO_DIRECTION)
    if atr <= 0.0:
        # Every level this module can invent is a volatility multiple, so with no
        # ATR there is nothing to build from. Saying so beats emitting a plan of
        # zeros, which reads as "the levels are at zero".
        issues.append(ISSUE_NO_ATR)

    closed = min(bar_index, len(series) - 1) if len(series) else -1
    entry, entry_basis, entry_reference, entry_issues = _derive_entry(
        payload, anat, series, closed
    )
    issues.extend(entry_issues)

    if entry_basis == ENTRY_BASIS_NONE or direction == 0:
        # Without an entry or a direction there is no "protective side" to reason
        # about, so no level is invented. `NO_DIRECTION` and `*_UNDEFINED` say
        # why, rather than a plan whose stop happens to sit on the wrong side of
        # a trade that does not exist.
        stop, stop_basis, stop_reference = 0.0, STOP_BASIS_NONE, 0.0
        target, target_basis, target_reference = 0.0, TARGET_BASIS_NONE, 0.0
    else:
        stop, stop_basis, stop_reference = _derive_stop(
            payload, anat, direction, entry, atr, closed, swings, cfg, warnings
        )
        target, target_basis, target_reference = _derive_target(
            payload, anat, direction, entry, atr, closed, swings, cfg, warnings
        )

    if stop_basis == STOP_BASIS_NONE:
        issues.append(ISSUE_STOP_UNDEFINED)
    if target_basis == TARGET_BASIS_NONE:
        issues.append(ISSUE_TARGET_UNDEFINED)

    risk = abs(entry - stop)
    reward = abs(target - entry)
    if atr > 0.0 and stop_basis != STOP_BASIS_NONE and risk > cfg.plan_max_stop_atr * atr:
        warnings.append(WARN_STOP_WIDE)

    if _is_terminal(payload):
        warnings.append(WARN_TERMINAL_SETUP)
    if evidence_score is not None:
        warnings.append(WARN_EVIDENCE_NOT_A_PROBABILITY)

    return TradePlan(
        subject=subject,
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        entry_basis=entry_basis,
        stop_basis=stop_basis,
        target_basis=target_basis,
        entry_reference=entry_reference,
        stop_reference=stop_reference,
        target_reference=target_reference,
        bar_index=closed,
        signal_bar=_first_index(payload, anat.signal_keys),
        invalidation=_invalidation_text(payload, anat, stop_basis),
        management=_management_notes(
            entry,
            entry_basis,
            stop,
            stop_basis,
            target,
            target_basis,
            risk,
            reward,
            reward / risk if risk > 0.0 else 0.0,
        ),
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_score=evidence_score,
    )


def plans_from_findings(
    findings: Sequence[Any],
    *,
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    bar_index: int,
    atr: float,
    config: AnalyzerConfig | None = None,
    detector_families: Mapping[str, str] | None = None,
) -> list[TradePlan]:
    """One plan per `SetupFinding`, in the order the findings arrived.

    That order is the registry's registration order, which the registry documents
    as deterministic and explicitly **not** a ranking. It is preserved here
    rather than sorted by reward:risk, for the same reason
    `evaluation.compare()` refuses to be a recommendation.
    """
    families = dict(DETECTOR_FAMILIES if detector_families is None else detector_families)
    out: list[TradePlan] = []
    for finding in findings:
        detector = str(getattr(finding, "detector", "") or "UNKNOWN")
        payload = getattr(finding, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        # A caller's own mapping wins; otherwise the shared one, and failing that
        # the finding's `kind`, which a third-party detector has already named
        # after its family. Guessing from the detector name would be a second
        # naming scheme.
        kind = str(getattr(finding, "kind", "") or "")
        family = families.get(detector) or family_for(detector, kind)
        out.append(
            build_trade_plan(
                detector,
                payload,
                bars=bars,
                bar_index=bar_index,
                atr=atr,
                anatomy=anatomy_for(family),
                config=config,
            )
        )
    return out
