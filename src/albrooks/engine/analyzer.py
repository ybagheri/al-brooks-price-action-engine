"""Main Analyzer coordinator interface."""

from __future__ import annotations

from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult


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
    ) -> AnalysisResult:
        """Run complete price action analysis on closed bars."""
        if not isinstance(bars, BarSeries):
            series = BarSeries(bars, symbol=symbol, timeframe=timeframe)
        else:
            series = bars

        # Pipeline steps will be connected here as each phase matures.
        return AnalysisResult(
            symbol=series.symbol,
            timeframe=series.timeframe,
            bars_processed=len(series),
            market_state={"state": "PENDING_PHASE4", "valid": False},
            swings=[],
            legs=[],
            patterns=[],
            measured_moves=[],
            setups=[],
            trade_plans=[],
            decision={"action": "NO_TRADE", "reason": "ENGINE_INITIALIZING"},
            warnings=[],
            bar_features=[],
        )
