"""Engine configuration models and defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AnalyzerConfig:
    """Master configuration for the Al Brooks Price Action Analyzer.

    All parameters have default values grounded in systematic heuristics
    derived from Al Brooks concepts.
    """

    # Swing & Pivot parameters
    swing_k: int = 3
    min_leg_bars: int = 3
    max_leg_bars: int = 100
    min_leg_atr: float = 1.0

    # ATR calculation
    atr_period: int = 14

    # Bar-by-bar classifications
    doji_max_body: float = 0.15
    big_bar_atr: float = 2.0
    small_bar_atr: float = 0.5
    strong_close_pct: float = 0.70
    min_body_pct: float = 0.30
    overlap_ratio: float = 0.50
    barbwire_bars: int = 5
    barbwire_min_overlap: int = 3
    pressure_lookback: int = 10

    # Market State / Context
    state_lookback: int = 20
    state_overlap_bars: int = 10
    enable_market_state: bool = True

    # Pullback and H1/H2 / L1/L2
    min_pb_ratio: float = 0.15
    max_pb_ratio: float = 0.90
    max_pb_bars: int = 50
    double_tol_atr: float = 0.25

    # Breakout & Reversal
    failed_bo_bars: int = 5
    min_pushes: int = 3
    use_wedge: bool = True

    # Fading Measured Move (FM)
    fm_approach_atr: float = 1.0
    fm_tol_atr: float = 0.25
    fm_over_atr: float = 0.50
    fm_require_ft: bool = False
    fm_enable_inverse: bool = True

    # Decision Engine & Gating
    enable_decision: bool = True
    min_score: float = 40.0
    min_rr: float = 1.0
    max_late_atr: float = 0.50
    conflict_ppts: int = 10
    max_failed_attempts: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalyzerConfig:
        valid_keys = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_keys)
