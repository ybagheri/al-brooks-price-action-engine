"""Price-action structures: factual observations about how a move is behaving.

This module is now a **facade** over focused `price_action` modules. The
detection logic itself moved out so that there is exactly one authoritative
implementation of each concept:

| Concept | Lives in |
|---|---|
| Climax / stall classification | `price_action.climaxes` |
| Push runs, strong-bar pressure | `price_action.pressure` |
| Wedge / contraction geometry | `price_action.wedges` |
| Composite exhaustion | `price_action.exhaustion` |
| Overlap, barbwire, inside runs | `price_action.overlap` |
| Micro gaps | `price_action.gaps` |

The names are re-exported here because `core.structures` is the historical
import location and existing callers depend on it. Nothing is reimplemented.

These are **facts and structural observations**, not signals. An exhaustion
reading is not a reversal, and a wedge is not a short.
"""

from __future__ import annotations

from albrooks.price_action.climaxes import BarCharacter, measure_bar
from albrooks.price_action.exhaustion import (
    ExhaustionStructure,
    detect_exhaustion,
    detect_overshoot,
)
from albrooks.price_action.gaps import GapInfo, detect_gap, detect_micro_gap
from albrooks.price_action.overlap import detect_barbwire, pair_overlap
from albrooks.price_action.pressure import (
    consecutive_run,
    count_pressure,
    push_count_back,
)
from albrooks.price_action.wedges import detect_wedge, is_shrinking, is_tightening

__all__ = [
    # Exhaustion
    "BarCharacter",
    "ExhaustionStructure",
    "detect_exhaustion",
    "detect_overshoot",
    "measure_bar",
    # Runs and pressure
    "consecutive_run",
    "count_pressure",
    "push_count_back",
    # Geometry
    "detect_gap",
    "detect_micro_gap",
    "GapInfo",
    "detect_wedge",
    "is_shrinking",
    "is_tightening",
    # Overlap
    "detect_barbwire",
    "pair_overlap",
]
