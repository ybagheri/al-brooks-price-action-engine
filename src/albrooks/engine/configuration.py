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

    # Measured Move (MM)
    enable_range_mm: bool = True
    range_lookback: int = 50
    enable_channel_mm: bool = True
    enable_gap_mm: bool = True
    min_gap_atr: float = 1.0
    enable_inverse_mm: bool = True

    # Fading Measured Move (FM)
    fm_approach_atr: float = 1.0
    fm_tol_atr: float = 0.25
    fm_over_atr: float = 0.50
    fm_require_ft: bool = False
    fm_enable_inverse: bool = True
    #: Bars a projection may be tracked before it expires as INVALIDATED.
    fm_max_bars_forward: int = 100
    #: Signal-bar body must be at least this share of the bar's range.
    fm_min_body: float = 0.30
    #: Signal-bar close must sit in the extreme share of its range.
    fm_close_pct: float = 0.50
    #: Adverse wick may not exceed this share of the signal bar's range.
    fm_max_wick: float = 0.60
    #: Require the signal bar to engulf the prior bar's body.
    fm_require_engulf: bool = False
    #: Most projections tracked at once; older ones are dropped.
    fm_max_active: int = 20
    #: Projections are seeded from the most recent confirmed swing triples.
    fm_recent_swings: int = 8

    # Evidence scoring
    #: Lower bound of the `STRONG` evidence band. Coarse on purpose; see
    #: `docs/algorithms/EVIDENCE_MODEL.md` §5.
    evidence_strong_band: float = 0.70
    #: Lower bound of the `MODERATE` band, below which evidence is `WEAK`.
    evidence_moderate_band: float = 0.40

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
