"""Legs, impulse moves, and two-legged pullback structural detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.swings import SwingPoint


@dataclass(frozen=True, slots=True)
class Leg:
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    direction: int  # +1 Bull Leg, -1 Bear Leg
    bars_count: int
    price_change: float
    confirmed_index: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TwoLegStructure:
    leg1: Leg
    pullback_leg: Leg
    leg2: Leg
    direction: int
    pullback_ratio: float
    symmetry_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_legs_from_swings(swings: Sequence[SwingPoint]) -> list[Leg]:
    if len(swings) < 2:
        return []

    legs: list[Leg] = []
    for i in range(len(swings) - 1):
        s0 = swings[i]
        s1 = swings[i + 1]
        # Valid leg connects alternate swings
        if s0.direction == s1.direction:
            continue
        direction = 1 if s1.price > s0.price else -1
        bars = s1.bar_index - s0.bar_index
        diff = abs(s1.price - s0.price)
        conf = max(s0.confirmed_bar_index, s1.confirmed_bar_index)
        legs.append(
            Leg(
                start_index=s0.bar_index,
                end_index=s1.bar_index,
                start_price=s0.price,
                end_price=s1.price,
                direction=direction,
                bars_count=bars,
                price_change=diff,
                confirmed_index=conf,
            )
        )
    return legs


def detect_two_leg_structures(legs: Sequence[Leg]) -> list[TwoLegStructure]:
    if len(legs) < 3:
        return []

    structures: list[TwoLegStructure] = []
    for i in range(len(legs) - 2):
        l1, pb, l2 = legs[i], legs[i + 1], legs[i + 2]
        # In a two-leg structure, leg1 and leg2 share direction, pb is counter-trend
        if l1.direction == l2.direction and pb.direction != l1.direction:
            pb_ratio = pb.price_change / l1.price_change if l1.price_change > 0 else 0.0
            symm = l2.price_change / l1.price_change if l1.price_change > 0 else 0.0
            structures.append(
                TwoLegStructure(
                    leg1=l1,
                    pullback_leg=pb,
                    leg2=l2,
                    direction=l1.direction,
                    pullback_ratio=pb_ratio,
                    symmetry_ratio=symm,
                )
            )
    return structures
