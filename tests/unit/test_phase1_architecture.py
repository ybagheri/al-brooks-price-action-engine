"""Unit tests for Phase 1 foundational architecture."""

import json

import pytest

from albrooks import Analyzer, AnalyzerConfig, Bar, BarSeries
from albrooks.engine.state import AnalysisResult


def test_bar_validations() -> None:
    # Valid bar
    b = Bar(time=1000.0, open=100.0, high=105.0, low=95.0, close=102.0, volume=10.0, index=0)
    assert b.range == 10.0
    assert b.body == 2.0
    assert b.is_bull is True
    assert b.is_bear is False
    assert b.upper_wick == 3.0  # 105 - 102
    assert b.lower_wick == 5.0  # 100 - 95
    assert pytest.approx(b.close_location) == 0.7  # (102 - 95) / 10 = 0.7
    assert b.is_doji is False

    # Inverted High/Low
    with pytest.raises(ValueError):
        Bar(time=1000.0, open=100.0, high=90.0, low=95.0, close=92.0)

    # Open out of bounds
    with pytest.raises(ValueError):
        Bar(time=1000.0, open=110.0, high=105.0, low=95.0, close=100.0)

    # Close out of bounds
    with pytest.raises(ValueError):
        Bar(time=1000.0, open=100.0, high=105.0, low=95.0, close=85.0)


def test_bar_doji_detection() -> None:
    # 0.1 body on 1.0 range -> 10% <= 15% -> doji
    b = Bar(time=1.0, open=10.0, high=10.5, low=9.5, close=10.1)
    assert b.is_doji is True

    # 0.5 body on 1.0 range -> 50% > 15% -> not doji
    b2 = Bar(time=1.0, open=10.0, high=10.5, low=9.5, close=10.5)
    assert b2.is_doji is False


def test_bar_series_indexing_and_immutability() -> None:
    raw = [
        {"time": 1, "open": 10, "high": 12, "low": 9, "close": 11},
        {"time": 2, "open": 11, "high": 13, "low": 10, "close": 12},
    ]
    series = BarSeries(raw, symbol="TEST", timeframe="M5")
    assert len(series) == 2
    assert series.symbol == "TEST"
    assert series.timeframe == "M5"
    assert series[0].index == 0
    assert series[1].index == 1
    assert series[1].close == 12

    # Append returns a new series
    series2 = series.append({"time": 3, "open": 12, "high": 15, "low": 11, "close": 14})
    assert len(series) == 2
    assert len(series2) == 3
    assert series2[2].index == 2
    assert series2[2].close == 14


def test_analyzer_config_serialization() -> None:
    cfg = AnalyzerConfig(swing_k=5, atr_period=20)
    d = cfg.to_dict()
    assert d["swing_k"] == 5
    assert d["atr_period"] == 20
    restored = AnalyzerConfig.from_dict(d)
    assert restored.swing_k == 5
    assert restored.atr_period == 20


def test_analyzer_end_to_end_phase1() -> None:
    analyzer = Analyzer()
    bars = [
        {"time": 100, "open": 1.1000, "high": 1.1050, "low": 1.0980, "close": 1.1040},
        {"time": 200, "open": 1.1040, "high": 1.1080, "low": 1.1020, "close": 1.1070},
    ]
    res = analyzer.analyze(bars, symbol="EURUSD", timeframe="H1")
    assert isinstance(res, AnalysisResult)
    assert res.symbol == "EURUSD"
    assert res.timeframe == "H1"
    assert res.bars_processed == 2

    # Check JSON export
    payload = res.to_json()
    data = json.loads(payload)
    assert data["symbol"] == "EURUSD"
    assert data["bars_processed"] == 2
