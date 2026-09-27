"""Fading Measured Move (FM): the lifecycle of a projection being faded.

The measured-move engine (Phase 10) answers *where* price is projected to go. This
module answers the separate question Brooks actually asks of a trader: **as price
approaches that target, is there reason to expect it to stop and reverse?**

```text
PROJECTED -> POTENTIAL -> DEVELOPING -> CONFIRMED -> COMPLETED
     |            |            |            |
     +------------+------------+------------+--> INVALIDATED
```

Transitions, taken from the reference specification:

| State | Entered when |
|---|---|
| `PROJECTED` | the projection forms; `created_bar` recorded |
| `POTENTIAL` | the bar's extreme comes within `fm_approach_atr` of the target |
| `DEVELOPING` | price *touches* the target **and** exhaustion is present |
| `CONFIRMED` | a reversal signal bar in the fade direction at the target |
| `COMPLETED` | one bar after `CONFIRMED`; terminal and informational |
| `INVALIDATED` | a close overshoots the target by `fm_over_atr`, or the projection expires |

**Touch is not a fade.** That is the whole discipline, and it is why `POTENTIAL` and
`DEVELOPING` are separate states: reaching the target is common and means nothing on
its own, while reaching it *with exhaustion* is the observation. `CONFIRMED` needs
more again — an actual signal bar.

**Fading discipline, stated plainly.** This fades the *target zone*, never the
trend, and it never produces a trade: there is no entry, no stop and no order. The
states are observations about how price behaved around a projection. Whether to act
is Phase 15.

## What this does not claim

- A `CONFIRMED` fade is **not** more likely to work than a `POTENTIAL` one. The
  ordering is a hypothesis for out-of-sample testing, not a measured property.
- No state is a probability, and no state is calibrated against outcomes.
- The lifecycle is **one transition per closed bar**, so a state can never skip
  ahead on a single bar and the sequence is always auditable bar by bar.
- `INVERSE` projections are included but are the weakest input; they are gated by
  `fm_enable_inverse` and the measured-move docs flag them for out-of-sample review.

## Dependency direction

This module **consumes** `MeasuredMoveProjection` and never the reverse, which is
why `measured_move_types.py` exists as a separate module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.exhaustion import detect_exhaustion
from albrooks.setups.measured_move import (
    MeasuredMoveProjection,
    MMFamily,
    detect_measured_moves,
)


class FMState(str, Enum):
    """Lifecycle position of a projection being faded."""

    PROJECTED = "PROJECTED"
    POTENTIAL = "POTENTIAL"
    DEVELOPING = "DEVELOPING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"

    @property
    def is_terminal(self) -> bool:
        return self in (FMState.COMPLETED, FMState.INVALIDATED)


#: States a projection can still leave. Anything else is frozen.
ACTIVE_STATES = (
    FMState.PROJECTED,
    FMState.POTENTIAL,
    FMState.DEVELOPING,
    FMState.CONFIRMED,
)



@dataclass(frozen=True, slots=True)
class FadingSetup:
    """One tracked projection and how far its fade lifecycle has progressed.

    Immutable, so a snapshot of the pipeline's state cannot be mutated by a later
    update; `to_state` produces the next value rather than editing in place.
    """

    id: int
    family: str
    #: Direction of the *projection*. `fade_direction` is its opposite, and is
    #: stored separately because conflating the two is the easiest way to fade a
    #: trend by mistake.
    direction: int
    target_price: float
    mm_range: float
    created_bar: int
    state: str = FMState.PROJECTED.value
    fade_direction: int = 0
    #: How close the bar's extreme came to the target, in ATR.
    touch_distance_atr: float = 0.0
    #: Measured conditions of the exhaustion structure at the touch, 0..5.
    exhaustion_breadth: int = 0
    #: Bar that carried the setup into its current state, -1 if never.
    state_bar: int = -1
    age: int = 0
    state_age: int = 0
    #: Why the setup reached its current state, in plain words.
    reason: str = ""
    #: The projection this was built from, for traceability.
    projection: MeasuredMoveProjection | None = None

    @property
    def is_active(self) -> bool:
        return self.state not in (
            FMState.COMPLETED.value,
            FMState.INVALIDATED.value,
        )

    @property
    def touched(self) -> bool:
        """Has price actually reached the target zone?

        `POTENTIAL` only means price *approached* the target. This is the stricter
        question of whether it arrived, and it is the precondition for `DEVELOPING`
        and `CONFIRMED`.
        """
        return self.state in (
            FMState.DEVELOPING.value,
            FMState.CONFIRMED.value,
            FMState.COMPLETED.value,
        )

    def to_state(self, **changes: Any) -> FadingSetup:
        """The next value of this setup, with `changes` applied.

        `dataclasses.replace` is not used because it re-invokes `__init__` for
        every field, which would force callers to resupply the nested projection
        on each of the many single-field updates a lifecycle performs.
        """
        base = {
            name: getattr(self, name) for name in self.__dataclass_fields__
        }
        return FadingSetup(**{**base, **changes})

    def to_dict(self) -> dict[str, Any]:
        # The nested projection is kept in full so the evidence behind the target
        # travels with the lifecycle state rather than having to be re-derived.
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    """Read a bar as `(open, high, low, close)`, accepting either key spelling."""
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def is_signal_bar(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    fade_direction: int,
    config: AnalyzerConfig | None = None,
) -> bool:
    """A reversal signal bar in the fade direction.

    Four independent requirements, all of which must hold:

    * the bar's body points the fade way,
    * the body is at least `fm_min_body` of the bar's range,
    * the close sits in the extreme `fm_close_pct` of the range,
    * the adverse wick is at most `fm_max_wick` of the range.

    The adverse-wick test is what separates a genuine reversal bar from one that
    merely closed lower while being sold into all the way to its low. Engulfing
    (`fm_require_engulf`) is off by default: it is the strictest of the five tests
    and would suppress most otherwise valid signals.
    """
    cfg = config or AnalyzerConfig()
    if idx < 1 or idx >= len(bars) or fade_direction not in (1, -1):
        return False

    o, h, low, c = _get_ohlc(bars[idx])
    p_open, _, _, p_close = _get_ohlc(bars[idx - 1])
    rg = h - low
    if rg <= 0:
        return False

    body = abs(c - o)
    d = 1 if c > o else (-1 if c < o else 0)
    if d != fade_direction:
        return False
    if body / rg < cfg.fm_min_body:
        return False

    adverse = (h - c) if fade_direction > 0 else (c - low)
    if adverse / rg > cfg.fm_max_wick:
        return False

    edge = ((c - low) if fade_direction > 0 else (h - c)) / rg
    if edge < 1.0 - cfg.fm_close_pct:
        return False

    if cfg.fm_require_engulf:
        p_body = abs(p_close - p_open)
        engulf = (
            (c > p_open and o < p_close)
            if fade_direction > 0
            else (c < p_open and o > p_close)
        )
        if not (engulf and body >= p_body):
            return False
    return True


def has_follow_through(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    signal_bar: int,
    fade_direction: int,
) -> bool:
    """Did the bar after `signal_bar` close beyond it, in the fade direction?

    This is the `fm_require_ft` option. Confirmation then lands exactly one closed
    bar *after* the signal, never on the signal bar itself — a fade confirmed by a
    bar that has not yet had a chance to fail is not confirmed.
    """
    if signal_bar < 0 or signal_bar + 1 >= len(bars):
        return False
    _, s_high, s_low, _ = _get_ohlc(bars[signal_bar])
    _, _, _, n_close = _get_ohlc(bars[signal_bar + 1])
    return n_close > s_high if fade_direction > 0 else n_close < s_low


def _advance(
    setup: FadingSetup,
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    cfg: AnalyzerConfig,
) -> FadingSetup:
    """Move one setup forward by at most one state, using bar `idx` only.

    Order matters and is not arbitrary:

    1. **Expiry** is checked first, so an old projection cannot be revived by a
       bar that happens to sit near its target.
    2. **Invalidation by overshoot** is checked next, for the same reason: a close
       that blew through the target is disqualifying regardless of what the rest
       of the bar did, and it must not be able to reach `CONFIRMED` first.
    3. Only then is the state's own advance considered.

    Because the invalidation tests are state-independent, they apply to every
    active state. A projection is invalid the moment price overshoots it, and
    waiting for a particular state to test for that would let a confirmed fade
    continue to be reported as active after the thesis was already broken.
    """
    state = FMState(setup.state)

    if setup.age > cfg.fm_max_bars_forward:
        return setup.to_state(
            state=FMState.INVALIDATED.value,
            reason=f"expired after {setup.age} bars",
        )

    o, h, low, c = _get_ohlc(bars[idx])
    # The bar's extreme *in the projection's direction* is what closes the
    # remaining distance to the target. Using the close instead would let a bar
    # with a long wick reach the target without price actually arriving.
    ext = h if setup.direction > 0 else low

    overshoot = (c - setup.target_price) if setup.direction > 0 else (
        setup.target_price - c
    )
    if overshoot > cfg.fm_over_atr * atr:
        return setup.to_state(
            state=FMState.INVALIDATED.value,
            reason=f"closed {overshoot:.6g} past the target",
        )

    tol = cfg.fm_tol_atr * atr
    approach = cfg.fm_approach_atr * atr
    fade = setup.fade_direction
    distance = (setup.target_price - ext) if setup.direction > 0 else (
        ext - setup.target_price
    )
    touch_distance = abs(distance) / atr if atr > 0 else 0.0

    def enter(new_state: FMState, reason: str, **extra: Any) -> FadingSetup:
        return setup.to_state(
            state=new_state.value,
            state_bar=idx,
            state_age=0,
            reason=reason,
            touch_distance_atr=touch_distance,
            **extra,
        )

    if state is FMState.PROJECTED:
        # "Approached", not "reached": the target may still be far away.
        if 0 <= distance <= approach:
            return enter(FMState.POTENTIAL, f"within {approach:.6g} of the target")
        return setup.to_state(touch_distance_atr=touch_distance)

    if state is FMState.POTENTIAL:
        if abs(distance) <= tol:
            # Touch alone is not enough. Exhaustion is the observation that makes a
            # touch meaningful, and requiring it is the entire fading discipline.
            structure = detect_exhaustion(
                bars, idx, last_closed, setup.direction, atr, config=cfg
            )
            if structure.breadth >= 1:
                return enter(
                    FMState.DEVELOPING,
                    f"touched the target with {structure.breadth} exhaustion "
                    f"condition(s)",
                    exhaustion_breadth=structure.breadth,
                )
            return setup.to_state(
                touch_distance_atr=touch_distance,
                reason="touched the target without exhaustion",
            )
        if distance > approach:
            # Drifted away: back to merely projected.
            return enter(FMState.PROJECTED, "moved away before touching")
        return setup.to_state(touch_distance_atr=touch_distance)

    if state is FMState.DEVELOPING:
        if abs(distance) <= tol and is_signal_bar(bars, idx, fade, cfg):
            if not cfg.fm_require_ft:
                return enter(FMState.CONFIRMED, "signal bar at the target")
            # With follow-through required, confirmation is deliberately deferred
            # to the next closed bar so a fade is never confirmed by a bar that
            # has not yet had the chance to fail.
        elif cfg.fm_require_ft and idx >= 1:
            # The delayed path: the signal was the previous closed bar and this
            # one has now closed beyond it.
            prev = idx - 1
            _, p_high, p_low, _ = _get_ohlc(bars[prev])
            p_ext = p_high if setup.direction > 0 else p_low
            if (
                abs(p_ext - setup.target_price) <= 2 * tol
                and is_signal_bar(bars, prev, fade, cfg)
                and has_follow_through(bars, prev, fade)
            ):
                return enter(
                    FMState.CONFIRMED,
                    f"signal bar {prev} confirmed by follow-through",
                )
        if abs(distance) > tol + approach:
            return enter(FMState.POTENTIAL, "left the target zone")
        return setup.to_state(touch_distance_atr=touch_distance)

    if state is FMState.CONFIRMED:
        # Terminal-informationally: the fade has played out. COMPLETED is not a
        # verdict on whether the fade was right, only that the lifecycle ended.
        return enter(FMState.COMPLETED, "one bar after confirmation")

    return setup.to_state(touch_distance_atr=touch_distance)


def create_setups(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int | None = None,
    atr: float = 0.0,
    swings: Sequence[Any] = (),
    legs: Sequence[Any] = (),
    config: AnalyzerConfig | None = None,
) -> list[FadingSetup]:
    """Seed fade setups from the projections live at `last_closed`.

    Every projection becomes a candidate, whatever its family. The lifecycle, not
    this function, decides which are still worth tracking: a projection whose
    target price already passed is invalidated on its first update.

    `INVERSE` projections are excluded unless `fm_enable_inverse` is set. They are
    the weakest input — a failed breakout projecting a reversal — and the
    measured-move documentation flags them for out-of-sample review before use.
    """
    cfg = config or AnalyzerConfig()
    n = len(bars)
    if n == 0 or atr <= 0:
        return []

    closed = n - 1 if last_closed is None else min(last_closed, n - 1)
    if closed < 0:
        return []

    projections = detect_measured_moves(
        bars,
        swings,
        atr=atr,
        last_closed=closed,
        legs=legs,
        recent_swings=cfg.fm_recent_swings,
        config=cfg,
    )

    setups: list[FadingSetup] = []
    for i, projection in enumerate(projections):
        if not projection.found or projection.direction == 0:
            continue
        if projection.family == MMFamily.INVERSE.value and not cfg.fm_enable_inverse:
            continue
        setups.append(
            FadingSetup(
                id=i + 1,
                family=projection.family,
                direction=projection.direction,
                # The fade runs against the projection. Storing both, rather than
                # overwriting one with the other, keeps "which way was price
                # projected" and "which way would we fade" separately answerable.
                fade_direction=-projection.direction,
                target_price=projection.target_price,
                mm_range=projection.mm_range,
                created_bar=closed,
                reason="projection formed",
                projection=projection,
            )
        )
    return setups[-cfg.fm_max_active :] if cfg.fm_max_active > 0 else setups


def update_setups(
    setups: Sequence[FadingSetup],
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> list[FadingSetup]:
    """Advance every active setup by at most one state, using bar `idx`.

    Terminal setups are returned unchanged rather than dropped, so a caller can
    still see how each projection ended. `idx` is clamped to `last_closed`, so
    passing a bar index beyond the analysed window cannot advance the lifecycle
    using data the caller said was not available.
    """
    cfg = config or AnalyzerConfig()
    n = len(bars)
    if n == 0 or atr <= 0 or not setups:
        return list(setups)

    closed = min(last_closed, n - 1)
    if idx < 0 or closed < 0:
        return list(setups)
    step = min(idx, closed)

    out: list[FadingSetup] = []
    for setup in setups:
        if not setup.is_active:
            out.append(setup)
            continue
        aged = setup.to_state(age=setup.age + 1, state_age=setup.state_age + 1)
        out.append(_advance(aged, bars, step, closed, atr, cfg))
    return out


def track_fading_measured_moves(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int | None = None,
    atr: float = 0.0,
    swings: Sequence[Any] = (),
    legs: Sequence[Any] = (),
    config: AnalyzerConfig | None = None,
) -> list[FadingSetup]:
    """Seed and advance in one call, reporting the state at `last_closed`.

    The setups are created at `last_closed` and then advanced through the bars that
    follow their projection, so the result reflects the whole sequence rather than
    only the final bar. A projection formed on the last bar is therefore still
    `PROJECTED`, which is correct: nothing has had a chance to develop yet.
    """
    cfg = config or AnalyzerConfig()
    setups = create_setups(
        bars,
        last_closed=last_closed,
        atr=atr,
        swings=swings,
        legs=legs,
        config=cfg,
    )
    if not setups:
        return []

    n = len(bars)
    closed = n - 1 if last_closed is None else min(last_closed, n - 1)
    for step in range(closed + 1):
        setups = update_setups(setups, bars, step, closed, atr, config=cfg)
    return setups

