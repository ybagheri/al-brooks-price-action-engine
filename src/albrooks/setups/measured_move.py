"""Measured Move (MM) Engine.

Implements systematic projection families inspired by Al Brooks price action:

1. Leg 1 = Leg 2 (AB = CD / Regular MM)
2. Range Height Projection (trading range breakout)
3. Channel Projection (shallow pullback channel continuation)
4. Gap Projection (measuring gap / trend impulse bar)
5. Inverse MM Projection (failed breakout of the swing leg extreme)

All projections are computed from closed bars only, so nothing repaints.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.core.legs import Leg
from albrooks.core.swings import SwingPoint
from albrooks.engine.configuration import AnalyzerConfig


class MMFamily(str, Enum):
    """Supported measured move projection families."""

    REGULAR = "REGULAR"  # Leg 1 = Leg 2
    RANGE = "RANGE"      # Range height projection
    CHANNEL = "CHANNEL"  # Shallow pullback channel
    GAP = "GAP"          # Measuring gap projection
    INVERSE = "INVERSE"  # Failed breakout inverse projection


@dataclass(frozen=True, slots=True)
class MeasuredMoveProjection:
    """A price-action based projected target for a future measured move."""

    found: bool = False
    family: str = "NONE"
    direction: int = 0  # +1 bullish projection, -1 bearish projection
    target_price: float = 0.0
    mm_range: float = 0.0
    origin_bar: int = -1
    anchor_bar: int = -1
    reference_price: float = 0.0
    pullback_depth: float = 0.0
    a0: dict[str, Any] | None = None
    a1: dict[str, Any] | None = None
    b0: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


def _swing_dict(s: SwingPoint | dict[str, Any]) -> dict[str, Any]:
    """Normalize a swing (or leg) representation to a plain dict."""
    if isinstance(s, SwingPoint):
        return {
            "bar": s.bar_index,
            "price": s.price,
            "dir": s.direction,
            "confirmed_bar": s.confirmed_bar_index,
        }
    return {
        "bar": int(s.get("bar", s.get("bar_index", 0))),
        "price": float(s.get("price", 0.0)),
        "dir": int(s.get("dir", s.get("direction", 0))),
        "confirmed_bar": int(s.get("confirmed_bar", s.get("confirmed_bar_index", 0))),
    }


def _leg_geometry(
    s0: dict[str, Any],
    s1: dict[str, Any],
    sb: dict[str, Any],
) -> tuple[int, float] | None:
    """Return (direction, mm_range) for a low-high-low / high-low-high triple."""
    if s0["dir"] == -1 and s1["dir"] == 1 and sb["dir"] == -1:
        return 1, s1["price"] - s0["price"]
    if s0["dir"] == 1 and s1["dir"] == -1 and sb["dir"] == 1:
        return -1, s0["price"] - s1["price"]
    return None


def _depth(
    direction: int,
    leg_extreme: float,
    pullback_price: float,
    mm_range: float,
) -> float:
    """Pullback depth as a fraction of the measured leg (0 = no pullback).

    `leg_extreme` is the terminal swing price of the measured leg (A1): the swing
    high for a bull leg and the swing low for a bear leg.
    """
    if direction > 0:
        return (leg_extreme - pullback_price) / mm_range
    return (pullback_price - leg_extreme) / mm_range


def project_leg_equality(
    a0: SwingPoint | dict[str, Any],
    a1: SwingPoint | dict[str, Any],
    b0: SwingPoint | dict[str, Any],
    atr: float,
    config: AnalyzerConfig | None = None,
) -> MeasuredMoveProjection | None:
    """Leg 1 = Leg 2 (AB = CD) projection.

    Bull geometry: A0 (swing low) -> A1 (swing high) -> B0 (pullback low).
    Target = B0.price + (A1.price - A0.price).
    Bear geometry is the exact mirror: Target = B0.price - (A0.price - A1.price).
    """
    cfg = config or AnalyzerConfig()
    s0, s1, sb = _swing_dict(a0), _swing_dict(a1), _swing_dict(b0)

    if atr <= 0:
        return None
    if not (s0["bar"] < s1["bar"] < sb["bar"]):
        return None

    geom = _leg_geometry(s0, s1, sb)
    if geom is None:
        return None
    direction, mm_range = geom
    if mm_range <= 0:
        return None

    leg_bars = s1["bar"] - s0["bar"]
    if not (cfg.min_leg_bars <= leg_bars <= cfg.max_leg_bars):
        return None
    if mm_range < cfg.min_leg_atr * atr:
        return None

    depth = _depth(direction, s1["price"], sb["price"], mm_range)
    if not (cfg.min_pb_ratio <= depth <= cfg.max_pb_ratio):
        return None

    pb_bars = sb["bar"] - s1["bar"]
    if pb_bars > cfg.max_pb_bars:
        return None

    target = sb["price"] + direction * mm_range
    return MeasuredMoveProjection(
        found=True,
        family=MMFamily.REGULAR.value,
        direction=direction,
        target_price=target,
        mm_range=mm_range,
        origin_bar=s0["bar"],
        anchor_bar=sb["bar"],
        reference_price=sb["price"],
        pullback_depth=depth,
        a0=s0,
        a1=s1,
        b0=sb,
    )


def project_channel(
    a0: SwingPoint | dict[str, Any],
    a1: SwingPoint | dict[str, Any],
    b0: SwingPoint | dict[str, Any],
    atr: float,
    config: AnalyzerConfig | None = None,
) -> MeasuredMoveProjection | None:
    """Channel projection: shallow-pullback continuation.

    Identical geometry to Leg 1 = Leg 2, but it only fires for pullbacks shallower
    than the regular minimum (``0.02 <= depth < min_pb_ratio``). That keeps the two
    families mutually exclusive by construction: a shallow channel is exactly the
    flag/flagpole case that a normal two-legged pullback would reject.
    """
    cfg = config or AnalyzerConfig()
    if not cfg.enable_channel_mm or atr <= 0:
        return None

    s0, s1, sb = _swing_dict(a0), _swing_dict(a1), _swing_dict(b0)
    if not (s0["bar"] < s1["bar"] < sb["bar"]):
        return None

    geom = _leg_geometry(s0, s1, sb)
    if geom is None:
        return None
    direction, mm_range = geom
    if mm_range <= 0 or mm_range < cfg.min_leg_atr * atr:
        return None

    leg_bars = s1["bar"] - s0["bar"]
    if not (cfg.min_leg_bars <= leg_bars <= cfg.max_leg_bars):
        return None

    depth = _depth(direction, s1["price"], sb["price"], mm_range)
    if not (0.02 <= depth < cfg.min_pb_ratio):
        return None

    pb_bars = sb["bar"] - s1["bar"]
    if pb_bars > cfg.max_pb_bars:
        return None

    target = sb["price"] + direction * mm_range
    return MeasuredMoveProjection(
        found=True,
        family=MMFamily.CHANNEL.value,
        direction=direction,
        target_price=target,
        mm_range=mm_range,
        origin_bar=s0["bar"],
        anchor_bar=sb["bar"],
        reference_price=sb["price"],
        pullback_depth=depth,
        a0=s0,
        a1=s1,
        b0=sb,
    )


def project_range(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    bo_idx: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> MeasuredMoveProjection | None:
    """Trading-range height breakout projection.

    The measured range is ``HH - LL`` over ``range_lookback`` closed bars ending
    one bar before the breakout bar. A bull breakout close above the range high
    projects ``close + height``; a bear breakout close below the range low
    projects ``close - height``.
    """
    cfg = config or AnalyzerConfig()
    if not cfg.enable_range_mm or atr <= 0:
        return None
    n_bars = len(bars)
    if bo_idx < 1 or bo_idx >= n_bars:
        return None

    lookback = cfg.range_lookback
    start_idx = bo_idx - lookback
    if lookback < 1 or start_idx < 0:
        return None

    window = bars[start_idx:bo_idx]
    hh = max(_get_ohlc(b)[1] for b in window)
    ll = min(_get_ohlc(b)[2] for b in window)
    height = hh - ll
    if height < cfg.min_leg_atr * atr:
        return None

    bo_c = _get_ohlc(bars[bo_idx])[3]
    if bo_c > hh:
        direction = 1
    elif bo_c < ll:
        direction = -1
    else:
        return None

    return MeasuredMoveProjection(
        found=True,
        family=MMFamily.RANGE.value,
        direction=direction,
        target_price=bo_c + direction * height,
        mm_range=height,
        origin_bar=start_idx,
        anchor_bar=bo_idx,
        reference_price=bo_c,
        a0={"bar": start_idx, "price": ll, "dir": -1, "confirmed_bar": -1},
        a1={"bar": bo_idx - 1, "price": hh, "dir": 1, "confirmed_bar": -1},
        b0={"bar": bo_idx, "price": bo_c, "dir": direction, "confirmed_bar": -1},
    )


def project_gap(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    gap_idx: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> MeasuredMoveProjection | None:
    """Measuring-gap (trend impulse bar) projection.

    Every strong trend bar in Brooks' framework is a breakout / gap up. The gap
    size itself is the measured impulse: when the bar gaps away from the prior
    extreme (``low > prev.high`` or ``high < prev.low``), closes in the extreme
    25% of its own range, and is at least ``min_gap_atr`` wide, the projection is
    ``close +/- gap_size``.
    """
    cfg = config or AnalyzerConfig()
    if not cfg.enable_gap_mm or atr <= 0:
        return None
    if gap_idx < 1 or gap_idx >= len(bars):
        return None

    _, curr_h, curr_l, curr_c = _get_ohlc(bars[gap_idx])
    _, prev_h, prev_l, _ = _get_ohlc(bars[gap_idx - 1])

    rg = curr_h - curr_l
    if rg <= 0 or rg < cfg.min_gap_atr * atr:
        return None

    bull_gap = curr_l > prev_h and (curr_c - curr_l) / rg >= 0.75
    bear_gap = curr_h < prev_l and (curr_h - curr_c) / rg >= 0.75
    if not bull_gap and not bear_gap:
        return None

    direction = 1 if bull_gap else -1
    gap_size = (curr_c - prev_h) if bull_gap else (prev_l - curr_c)
    if gap_size < 0.25 * atr:
        return None

    prior_extreme = prev_h if bull_gap else prev_l
    gap_extreme = curr_l if bull_gap else curr_h
    return MeasuredMoveProjection(
        found=True,
        family=MMFamily.GAP.value,
        direction=direction,
        target_price=curr_c + direction * gap_size,
        mm_range=gap_size,
        origin_bar=gap_idx - 1,
        anchor_bar=gap_idx,
        reference_price=curr_c,
        a0={"bar": gap_idx - 1, "price": prior_extreme, "dir": -direction, "confirmed_bar": -1},
        a1={"bar": gap_idx, "price": gap_extreme, "dir": direction, "confirmed_bar": -1},
        b0={"bar": gap_idx, "price": curr_c, "dir": direction, "confirmed_bar": -1},
    )


def _leg_fields(leg: Leg | dict[str, Any]) -> tuple[int, int, int, float, float, float]:
    """Extract (direction, a0_bar, a1_bar, a0_price, a1_price, mm_range) from a leg."""
    if isinstance(leg, Leg):
        return (
            leg.direction,
            leg.start_index,
            leg.end_index,
            leg.start_price,
            leg.end_price,
            leg.price_change,
        )
    a0 = leg.get("a0", {})
    a1 = leg.get("a1", {})
    a0_bar = int(leg.get("start_index", a0.get("bar", 0)))
    a1_bar = int(leg.get("end_index", a1.get("bar", 0)))
    a0_price = float(leg.get("start_price", a0.get("price", 0.0)))
    a1_price = float(leg.get("end_price", a1.get("price", 0.0)))
    mm_range = float(leg.get("price_change", leg.get("range", abs(a1_price - a0_price))))
    direction = int(leg.get("direction", leg.get("dir", 0)))
    if direction == 0:
        direction = 1 if a1_price > a0_price else -1
    return direction, a0_bar, a1_bar, a0_price, a1_price, mm_range


def project_inverse(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    leg: Leg | dict[str, Any],
    atr: float,
    last_closed: int | None = None,
    config: AnalyzerConfig | None = None,
) -> MeasuredMoveProjection | None:
    """Inverse projection: the leg extreme (A1) is broken, then reclaimed.

    A failed breakout of the leg terminal swing projects an opposite move of the
    same size as the leg. The anchor is deliberately the *far side* of the failure
    bar, which is the conservative choice:

    * Bull leg broken above A1 then reclaimed  -> bearish target
      ``low of the failure high bar - leg range``.
    * Bear leg broken below A1 then reclaimed  -> bullish target
      ``high of the failure low bar + leg range``.

    This is the weakest of the projection families and is meant to be reviewed on
    out-of-sample data before it is trusted.
    """
    cfg = config or AnalyzerConfig()
    if not cfg.enable_inverse_mm or atr <= 0:
        return None

    direction, a0_bar, a1_bar, a0_price, a1_price, mm_range = _leg_fields(leg)
    if direction not in (1, -1) or mm_range < cfg.min_leg_atr * atr:
        return None

    n_bars = len(bars)
    upper = n_bars - 1 if last_closed is None else min(last_closed, n_bars - 1)
    from_bar = a1_bar + 1
    to_bar = min(upper, a1_bar + cfg.failed_bo_bars)
    if from_bar > to_bar:
        return None

    ext = a1_price
    fail_bar = -1
    break_bar = -1

    if direction > 0:
        extreme_high = 0.0
        extreme_low = 0.0
        for s in range(from_bar, to_bar + 1):
            _, bh, bl, bc = _get_ohlc(bars[s])
            if bh > extreme_high:
                extreme_high, extreme_low = bh, bl
            if bc > ext:
                break_bar = s
                break
        if break_bar < 0 or extreme_high <= ext:
            return None
        for t in range(break_bar + 1, to_bar + 1):
            _, th, tl, tc = _get_ohlc(bars[t])
            if th > extreme_high:
                extreme_high, extreme_low = th, tl
            if tc < ext:
                fail_bar = t
                break
        if fail_bar < 0:
            return None
        target = extreme_low - mm_range
        if target >= extreme_low:
            return None
        return MeasuredMoveProjection(
            found=True,
            family=MMFamily.INVERSE.value,
            direction=-1,
            target_price=target,
            mm_range=mm_range,
            origin_bar=a0_bar,
            anchor_bar=fail_bar,
            reference_price=extreme_low,
            a0={"bar": a0_bar, "price": a0_price, "dir": -1, "confirmed_bar": -1},
            a1={"bar": a1_bar, "price": a1_price, "dir": 1, "confirmed_bar": -1},
            b0={"bar": fail_bar, "price": extreme_high, "dir": 1, "confirmed_bar": -1},
        )

    extreme_low = None
    low_bar = -1
    for s in range(from_bar, to_bar + 1):
        _, bh, bl, bc = _get_ohlc(bars[s])
        if extreme_low is None or bl < extreme_low:
            extreme_low, low_bar = bl, s
        if bc < ext:
            break_bar = s
            break
    if break_bar < 0 or extreme_low is None or low_bar < from_bar or not (extreme_low < ext):
        return None
    for t in range(break_bar + 1, to_bar + 1):
        _, _, tl, tc = _get_ohlc(bars[t])
        if tl < extreme_low:
            extreme_low, low_bar = tl, t
        if tc > ext:
            fail_bar = t
            break
    if fail_bar < 0:
        return None
    anchor_high = _get_ohlc(bars[low_bar])[1]
    return MeasuredMoveProjection(
        found=True,
        family=MMFamily.INVERSE.value,
        direction=1,
        target_price=anchor_high + mm_range,
        mm_range=mm_range,
        origin_bar=a0_bar,
        anchor_bar=fail_bar,
        reference_price=anchor_high,
        a0={"bar": a0_bar, "price": a0_price, "dir": 1, "confirmed_bar": -1},
        a1={"bar": a1_bar, "price": a1_price, "dir": -1, "confirmed_bar": -1},
        b0={"bar": fail_bar, "price": extreme_low, "dir": -1, "confirmed_bar": -1},
    )


def _confirmed_swings(
    swings: Sequence[SwingPoint | dict[str, Any]],
    last_closed: int,
) -> list[dict[str, Any]]:
    """Swings confirmed on or before `last_closed` (no-lookahead filter)."""
    out: list[dict[str, Any]] = []
    for s in swings:
        sd = _swing_dict(s)
        if sd["confirmed_bar"] >= 0 and sd["confirmed_bar"] > last_closed:
            continue
        if sd["bar"] > last_closed:
            continue
        out.append(sd)
    return out


def _dedup_key(p: MeasuredMoveProjection) -> tuple[str, int, int, float]:
    return (p.family, p.direction, p.anchor_bar, round(p.target_price, 9))


def detect_measured_moves(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    swings: Sequence[SwingPoint | dict[str, Any]] = (),
    atr: float = 0.0,
    last_closed: int | None = None,
    legs: Sequence[Leg | dict[str, Any]] = (),
    max_inverse_legs: int = 6,
    recent_swings: int = 8,
    config: AnalyzerConfig | None = None,
) -> list[MeasuredMoveProjection]:
    """Collect the measured move projections that are live at `last_closed`.

    Swing families (Leg 1 = Leg 2, Channel) are formed from consecutive swing
    triples, the Range and Gap families are evaluated on the newest closed bar,
    and the Inverse family is attempted on the most recent swing legs.

    Two windows keep the result bounded and relevant rather than historical:

    * `recent_swings` limits the swing-triple scan to the most recent confirmed
      swings, so a triple whose target was reached long ago is not re-reported
      every bar. Deciding whether a projection is still *live* is the job of the
      fade lifecycle (Phase 11), not of this engine.
    * `max_inverse_legs` limits the Inverse family to the most recent legs.

    Only swings confirmed on or before `last_closed` are used, so the output for a
    given bar index never changes when future bars arrive.
    """
    cfg = config or AnalyzerConfig()
    n_bars = len(bars)
    if n_bars == 0 or atr <= 0:
        return []

    closed = n_bars - 1 if last_closed is None else min(last_closed, n_bars - 1)
    if closed < 0:
        return []

    confirmed = _confirmed_swings(swings, closed)
    if recent_swings > 0:
        confirmed = confirmed[-recent_swings:]
    projections: list[MeasuredMoveProjection] = []

    for i in range(len(confirmed) - 2):
        a0, a1, b0 = confirmed[i], confirmed[i + 1], confirmed[i + 2]
        for fn in (project_leg_equality, project_channel):
            p = fn(a0, a1, b0, atr, config=cfg)
            if p is not None:
                projections.append(p)

    for fn in (project_range, project_gap):
        p = fn(bars, closed, atr, config=cfg)
        if p is not None:
            projections.append(p)

    if cfg.enable_inverse_mm:
        legs_to_check: list[Leg | dict[str, Any]] = list(legs)
        if not legs_to_check:
            for i in range(len(confirmed) - 1):
                legs_to_check.append(
                    {
                        "start_index": confirmed[i]["bar"],
                        "end_index": confirmed[i + 1]["bar"],
                        "start_price": confirmed[i]["price"],
                        "end_price": confirmed[i + 1]["price"],
                    }
                )
        for leg in legs_to_check[-max_inverse_legs:] if max_inverse_legs > 0 else []:
            p = project_inverse(bars, leg, atr, last_closed=closed, config=cfg)
            if p is not None:
                projections.append(p)

    seen: set[tuple[str, int, int, float]] = set()
    unique: list[MeasuredMoveProjection] = []
    for p in projections:
        key = _dedup_key(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique
