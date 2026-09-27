"""Gaps and micro-gaps between consecutive bars.

In this project "gap" means a **micro gap**: a bar that opens and trades wholly
beyond the prior bar's extreme, leaving unfilled price territory between them.
On continuous futures and FX these are small or absent; on index futures and
overnight sessions they are common.

Note the tension with the measured-move `GAP` family, which uses a much
stronger definition (a large bar closing in its extreme 25% that gaps away from
the prior extreme, with the gap size treated as the measured impulse). The two
are deliberately different and both are correct for their purpose: this module
detects *the event*, the MM family *projects a target from it*.

`OBJECTIVE`: these are inequalities on OHLC values.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    return (
        float(b.get("o", b.get("open", 0.0))),
        float(b.get("h", b.get("high", 0.0))),
        float(b.get("l", b.get("low", 0.0))),
        float(b.get("c", b.get("close", 0.0))),
    )


@dataclass(frozen=True, slots=True)
class GapInfo:
    """A detected micro gap at a given bar."""

    bar_index: int = -1
    direction: int = 0  # +1 gap up, -1 gap down, 0 none
    size: float = 0.0
    prior_extreme: float = 0.0
    gap_edge: float = 0.0

    @property
    def found(self) -> bool:
        return self.direction != 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_gap(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
) -> GapInfo:
    """Detect a micro gap between `bars[idx - 1]` and `bars[idx]`.

    Bull gap: the current bar's low sits above the prior bar's high.
    Bear gap: the current bar's high sits below the prior bar's low.

    `size` is the unfilled distance in price units. Requires `idx >= 1`; a gap
    can only be defined against a predecessor.
    """
    if idx < 1 or idx >= len(bars):
        return GapInfo(bar_index=idx)
    _, curr_h, curr_l, _ = _get_ohlc(bars[idx])
    _, prev_h, prev_l, _ = _get_ohlc(bars[idx - 1])

    if curr_l > prev_h:
        return GapInfo(
            bar_index=idx,
            direction=1,
            size=curr_l - prev_h,
            prior_extreme=prev_h,
            gap_edge=curr_l,
        )
    if curr_h < prev_l:
        return GapInfo(
            bar_index=idx,
            direction=-1,
            size=prev_l - curr_h,
            prior_extreme=prev_l,
            gap_edge=curr_h,
        )
    return GapInfo(bar_index=idx)


def detect_micro_gap(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    atr: float,
    min_size_atr: float = 0.0,
) -> GapInfo:
    """A micro gap, optionally gated so that only meaningful ones qualify.

    `min_size_atr` filters out the numerically-tiny gaps that appear on
    low-volatility instruments where a rounding difference looks like a gap.
    Pass `0.0` to accept any strictly positive gap.
    """
    info = detect_gap(bars, idx)
    if not info.found:
        return info
    # With no ATR reference there is nothing to normalise the gate against,
    # so the raw detection stands.
    if atr > 0 and info.size < min_size_atr * atr:
        return GapInfo(bar_index=idx)
    return info


def gap_run_length(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    idx: int,
    last_closed: int,
) -> int:
    """How many consecutive bars ending at `idx` share the same gap direction.

    A run of same-direction gaps is a "staircase" away from the prior range,
    which is a more meaningful structural observation than a single gap.
    """
    if idx < 1 or idx > last_closed or idx >= len(bars):
        return 0
    current = detect_gap(bars, idx)
    if not current.found:
        return 0
    n = 1
    i = idx - 1
    while i >= 1 and i <= last_closed and i < len(bars):
        prev_gap = detect_gap(bars, i)
        if not prev_gap.found or prev_gap.direction != current.direction:
            break
        n += 1
        i -= 1
    return n
