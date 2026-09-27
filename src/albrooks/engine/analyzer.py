"""Main Analyzer coordinator.

Wires the implemented layers into the documented public entry point. Every
detector already existed and was individually tested; what was missing was the
coordination, which is why `analyze()` used to return a hard-coded placeholder
and the documented API produced nothing.

## Order of operations

The order is not arbitrary. Each stage consumes the previous stage's output:

```text
bars -> ATR -> bar features -> swings -> legs -> market state
                                                  |
        +----------------------+--------------------+--------------------+
        v                      v                    v
   measured moves          pullbacks             breakouts
```

ATR comes first because almost every gate is expressed in ATR multiples, and a
detector given `atr=0` silently returns "nothing found" rather than an error. That
failure mode is invisible, so the pipeline refuses to run rather than reporting a
market with no volatility.

## The closed-bar contract

`last_closed` is threaded into every stage, and the result records the value used
in `last_closed_bar`. Two properties follow, and both are asserted in the tests:

1. Analysis for a given `last_closed` is **identical** whether or not later bars
   exist. Appending future bars cannot change the output for an earlier index.
2. A `last_closed` past the available data is **clamped**, not rejected, matching
   every detector's own behaviour.

## What this does not do

It reports structure, context, and setup candidates. It does not decide anything.
`decision` is always `NO_TRADE` with the reason `DECISION_ENGINE_NOT_IMPLEMENTED`,
because the decision engine is Phase 15 and an inferred BUY/SELL here would be a
claim this codebase has not earned.
"""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.context.market_state import analyze_market_state
from albrooks.context.trend import measure_trend
from albrooks.core.bars import Bar, BarSeries
from albrooks.core.channels import detect_channel
from albrooks.core.legs import build_legs_from_swings
from albrooks.core.pivots import find_pivots
from albrooks.core.swings import find_swings
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult
from albrooks.price_action.bars import analyze_series, calculate_atr_series
from albrooks.setups.breakout import analyze_breakout
from albrooks.setups.measured_move import detect_measured_moves
from albrooks.setups.pullback import detect_h1_h2, detect_l1_l2
from albrooks.setups.reversal import analyze_reversal

#: Reason codes for a run that produced no analysis, kept distinct from
#: "the analysis ran and found nothing".
REASON_NO_BARS = "NO_BARS"
REASON_NEGATIVE_LAST_CLOSED = "NEGATIVE_LAST_CLOSED"
REASON_ATR_UNAVAILABLE = "ATR_UNAVAILABLE"

#: Warnings that describe the *input* rather than the market.
WARN_SHORT_SERIES = "SHORT_SERIES_ATR_NOT_FULLY_SETTLED"
WARN_NO_SWINGS = "NO_CONFIRMED_SWINGS_IN_WINDOW"


class Analyzer:
    """Core coordinator for Al Brooks Price Action Analysis.

    Provides a clean, uniform public entry point:
        analyzer = Analyzer()
        result = analyzer.analyze(bars, symbol="EURUSD", timeframe="H1")
    """

    def __init__(self, config: AnalyzerConfig | None = None) -> None:
        self.config = config or AnalyzerConfig()

    def analyze(
        self,
        bars: Sequence[Bar | dict[str, Any]] | BarSeries,
        symbol: str = "GENERIC",
        timeframe: str = "UNKNOWN",
        last_closed: int | None = None,
    ) -> AnalysisResult:
        """Run complete price action analysis on closed bars.

        `last_closed` restricts analysis to bars `0..last_closed` inclusive. It
        defaults to the newest bar and is clamped to the available range, so
        passing a value past the end asks for the whole series rather than raising.
        """
        series = (
            bars
            if isinstance(bars, BarSeries)
            else BarSeries(bars, symbol=symbol, timeframe=timeframe)
        )
        n = len(series)
        if n == 0:
            return self._empty(series, REASON_NO_BARS)

        closed = n - 1 if last_closed is None else min(last_closed, n - 1)
        if closed < 0:
            return self._empty(series, REASON_NEGATIVE_LAST_CLOSED, last_closed=closed)

        atrs = calculate_atr_series(series, period=self.config.atr_period)
        atr = atrs[closed] if closed < len(atrs) else 0.0
        if atr <= 0:
            # Every ATR-relative gate would now reject everything, and the result
            # would read as "no structure" when it means "no volatility reference".
            return self._empty(series, REASON_ATR_UNAVAILABLE, last_closed=closed)

        # `analyze_series` always runs to the end of the series it is given, with no
        # `last_closed` of its own. Passing the full series would therefore compute
        # features for bars *after* the analysis point and hand the caller future
        # prices inside the result. Slicing to the analysed window keeps the
        # feature list exactly `0..closed`.
        features = analyze_series(series[: closed + 1], self.config)
        swings = find_swings(series, last_closed_idx=closed, k=self.config.swing_k)
        legs = build_legs_from_swings(swings)
        state = analyze_market_state(series, closed, closed, atr, config=self.config)
        trend = measure_trend(series, closed, closed, atr, config=self.config)
        pivots = find_pivots(series, last_closed=closed, k=self.config.swing_k, atr=atr)
        channel = detect_channel(
            series, closed, k=self.config.swing_k, atr=atr, config=self.config
        )
        moves = detect_measured_moves(
            series, swings, atr=atr, last_closed=closed, legs=legs, config=self.config
        )
        pullbacks = self._pullbacks(series, closed, atr)
        breakouts = self._breakouts(series, closed, atr, swings)
        reversals = self._reversals(series, closed, atr, swings)

        return AnalysisResult(
            symbol=series.symbol,
            timeframe=series.timeframe,
            bars_processed=n,
            last_closed_bar=closed,
            market_state=state.to_dict(),
            swings=[s.to_dict() for s in swings],
            legs=[leg.to_dict() for leg in legs],
            patterns=[p.to_dict() for p in pivots],
            measured_moves=[m.to_dict() for m in moves],
            setups=[
                s for s in (*pullbacks, *breakouts, *reversals) if s.get("found")
            ],
            trade_plans=[],
            decision={
                "action": "NO_TRADE",
                "reason": "DECISION_ENGINE_NOT_IMPLEMENTED",
                "note": (
                    "Structure, context and setup candidates only. Phase 15 owns "
                    "the decision; nothing here infers a trade."
                ),
            },
            warnings=self._warnings(n, closed, swings, state),
            bar_features=[f.to_dict() for f in features],
            trends=[trend.to_dict()],
            # `detect_channel` always returns a PriceChannel; the default is an
            # empty one whose `direction` is 0, so presence is tested on that
            # rather than on a truthiness check that a populated zero-width
            # channel would also pass.
            channels=[channel.to_dict()] if channel.direction != 0 else [],
            pullbacks=pullbacks,
            breakouts=breakouts,
            reversals=reversals,
            evidence=self._evidence(state, moves, pullbacks, breakouts, reversals),
            layers=self._layers(),
        )

    # -- layer helpers ----------------------------------------------------

    def _pullbacks(
        self, series: BarSeries, closed: int, atr: float
    ) -> list[dict[str, Any]]:
        """Both pullback directions at the newest closed bar.

        H1/H2 and L1/L2 are reported together rather than "best" first: a caller
        comparing them needs both, and ranking them here would be a decision this
        layer does not own.
        """
        out = []
        for detector, family in (
            (detect_h1_h2, "H_PULLBACK"),
            (detect_l1_l2, "L_PULLBACK"),
        ):
            payload = detector(
                series, closed, closed, atr, config=self.config
            ).to_dict()
            payload["family"] = family
            out.append(payload)
        return out

    def _breakouts(
        self, series: BarSeries, closed: int, atr: float, swings: Sequence[Any]
    ) -> list[dict[str, Any]]:
        payload = analyze_breakout(
            series, closed, closed, atr, swings=swings, config=self.config
        ).to_dict()
        payload["family"] = "BREAKOUT"
        return [payload]

    def _reversals(
        self, series: BarSeries, closed: int, atr: float, swings: Sequence[Any]
    ) -> list[dict[str, Any]]:
        """Both reversal directions, for the same reason as the pullbacks."""
        out = []
        for direction in (1, -1):
            payload = analyze_reversal(
                series,
                closed,
                closed,
                atr,
                swings=swings,
                reversal_direction=direction,
                config=self.config,
            ).to_dict()
            payload["family"] = "REVERSAL"
            out.append(payload)
        return out

    def _warnings(
        self, n: int, closed: int, swings: Sequence[Any], state: Any
    ) -> list[str]:
        """Warnings about the *input*, kept separate from the market's own warnings.

        A detector that reports nothing because the series is too short and one
        that reports nothing because the market is flat must not look alike to a
        caller reading the output.
        """
        warnings = list(state.warnings)
        if n < self.config.atr_period:
            warnings.append(WARN_SHORT_SERIES)
        if not swings and closed >= 4 * self.config.swing_k:
            # Enough history for swings to exist, so their absence is a statement
            # about the market rather than a side effect of too little data.
            warnings.append(WARN_NO_SWINGS)
        return warnings

    def _evidence(
        self,
        state: Any,
        moves: Sequence[Any],
        pullbacks: Sequence[dict[str, Any]],
        breakouts: Sequence[dict[str, Any]],
        reversals: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Flatten the layers' own evidence into one list with stable codes.

        Sources keep their own vocabulary and are labelled by `source` rather than
        merged into a single score: a market-state reason and a measured-move
        factor measure different things, and summing them would imply a
        comparability that does not exist.
        """
        out: list[dict[str, Any]] = []
        for line in state.evidence:
            code, _, detail = line.partition(":")
            out.append(
                {"source": "MARKET_STATE", "code": code, "detail": detail.strip()}
            )
        for move in moves:
            for item in move.evidence:
                out.append(
                    {
                        "source": "MEASURED_MOVE",
                        "code": item.code,
                        "detail": item.detail,
                        "weight": item.weight,
                        "family": move.family,
                    }
                )
        for group, source in (
            (pullbacks, "PULLBACK"),
            (breakouts, "BREAKOUT"),
            (reversals, "REVERSAL"),
        ):
            for entry in group:
                if not entry.get("found"):
                    continue
                out.append(
                    {
                        "source": source,
                        "code": self._setup_code(entry),
                        "detail": "",
                    }
                )
        return out

    @staticmethod
    def _setup_code(entry: dict[str, Any]) -> str:
        """The most specific stable code a setup entry offers.

        Each detector names its own outcome differently, so the fields are tried in
        order of specificity rather than assumed to be uniform. The `DETECTED`
        fallback is a last resort: it records that something fired without claiming
        which thing it was.
        """
        for field_name in ("setup_type", "state", "outcome", "verdict"):
            value = entry.get(field_name)
            if value and value != "NONE":
                return str(value)
        return "DETECTED"

    def _layers(self) -> dict[str, bool]:
        """Which layers this run actually performed.

        Reported so `unimplemented_layers` is a fact rather than an inference from
        an empty list.
        """
        return {
            "bar_features": True,
            "swings": True,
            "legs": True,
            "pivots": True,
            "market_state": True,
            "trends": True,
            "channels": True,
            "measured_moves": True,
            "pullbacks": True,
            "breakouts": True,
            "reversals": True,
            "trade_plans": False,
            "decision": False,
        }

    def _empty(
        self, series: BarSeries, reason: str, last_closed: int = -1
    ) -> AnalysisResult:
        """A result that explains itself instead of pretending to have found nothing.

        Empty lists for "no bars" or "no volatility" would be a claim about the
        market. A short or volatility-free series is a fact about the input, so it
        is reported as the reason, and every layer is marked as not run.
        """
        return AnalysisResult(
            symbol=series.symbol,
            timeframe=series.timeframe,
            bars_processed=len(series),
            last_closed_bar=last_closed,
            market_state={"valid": False, "mode": "UNKNOWN", "reason": reason},
            decision={
                "action": "NO_TRADE",
                "reason": reason,
                "note": "No analysis was run; see market_state.reason.",
            },
            warnings=[reason],
            layers={name: False for name in self._layers()},
        )

