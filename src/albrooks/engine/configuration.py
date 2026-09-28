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

    # Trade Plan
    #: Buffer placed beyond a structural level, so a stop sits clear of the
    #: extreme it is derived from rather than exactly on it.
    plan_stop_buffer_atr: float = 0.25
    #: Stop distance used when the setup carries no structural level at all.
    plan_fallback_stop_atr: float = 1.0
    #: Target distance used when no structural or projected level lies ahead.
    plan_fallback_target_atr: float = 2.0
    #: A risk wider than this many ATR raises `STOP_WIDE` on the plan. A warning
    #: rather than a veto: whether a wide stop is acceptable is a trade decision,
    #: and gating is the decision engine's job, not the plan layer's.
    plan_max_stop_atr: float = 3.0

    # Multi-Timeframe
    #: HTF proxy `strength` at or above which the higher timeframe is treated as
    #: carrying a directional bias. Below it the HTF is a range, a transition or a
    #: weak read, and a lower-timeframe signal against it is not a conflict. A
    #: chosen value: `MarketState.strength` is a share of proxy score, not a
    #: probability of continuation.
    htf_min_strength: float = 0.60
    #: Veto a lower-timeframe decision that runs against a strong HTF bias.
    #: `True` by default because a structural conflict is the one thing a
    #: higher timeframe is *for*; `False` reports the conflict without gating on
    #: it, for a caller that treats the HTF as context rather than as a filter.
    htf_opposition_veto: bool = True
    #: Run the HTF analysis even when the higher series is too short to classify.
    #: A short HTF is a fact about the input, reported as
    #: `HTF_NOT_CLASSIFIED` with bias `0` — never as "no bias", which would be a
    #: claim the data cannot support.
    htf_report_unclassified: bool = True

    # Decision Engine & Gating
    #: Master switch for the decision layer. `False` makes it answer
    #: `NO_TRADE` / `DECISION_DISABLED`; it never makes it infer a trade.
    enable_decision: bool = True
    #: Minimum evidence score (0..1, the same scale `EvidenceScore.value` uses)
    #: for a candidate to survive. The declared default was `40.0`, on a 0-100
    #: scale the Phase 13 evidence model never had — on a 0..1 score it rejects
    #: every candidate, including a perfect one. Corrected in Phase 15, when the
    #: key was first read.
    min_score: float = 0.40
    #: Minimum reward:risk for a candidate to survive. Pairs with
    #: `TradePlan.reward_to_risk`.
    min_rr: float = 1.0
    #: How far, in ATR, price may have moved from the level a plan was built on
    #: before the plan counts as late. The plan is stale past this, not wrong.
    max_late_atr: float = 0.50
    #: Minimum gap in evidence points between the strongest bull and the
    #: strongest bear candidate for either side to count as dominant rather than
    #: contested. Below it the decision is `WAIT` / `EVIDENCE_CONFLICT`.
    conflict_ppts: float = 10.0
    #: How many adverse observations may stand against a candidate before it is
    #: vetoed. The count is deliberately narrow; see
    #: `docs/algorithms/DECISION_ENGINE.md` §5.
    max_failed_attempts: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalyzerConfig:
        valid_keys = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_keys)
