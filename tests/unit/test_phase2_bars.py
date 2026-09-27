"""Unit tests for Phase 2 Bar-by-bar price action feature engine."""


from albrooks.core.bars import BarSeries
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.bars import (
    analyze_bar,
    analyze_series,
    calculate_atr_series,
    pair_overlap,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def test_strong_bull_and_bear_geometry() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(100, 100.5, 99.5, 100)] * 3
    bars.append(mk(100, 110, 99.5, 109.5))  # big bull, close near high
    f = analyze_bar(bars, 3, 3, atr=2.0, config=cfg)
    assert f.valid and f.dir == 1 and f.is_strong_bull
    assert f.label == "STRONG_BULL" and f.close_pos > 0.9

    bars.append(mk(109.5, 110, 99.0, 99.5))  # big bear, close near low
    g = analyze_bar(bars, 4, 4, atr=2.0, config=cfg)
    assert g.dir == -1 and g.is_strong_bear and g.label == "STRONG_BEAR"


def test_doji_is_pause_not_signal() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(6)]
    bars.append(mk(106, 106.4, 105.6, 106.02))  # tiny body -> doji
    f = analyze_bar(bars, 6, 6, atr=2.0, config=cfg)
    assert f.is_doji and f.label == "DOJI"
    assert f.consecutive == 0, "Doji must reset consecutive run count (Brooks pause)"
    assert not f.is_strong_bull and not f.is_strong_bear


def test_inside_outside_and_ii_count() -> None:
    cfg = AnalyzerConfig()
    bars = [
        mk(100, 110, 90, 105),
        mk(101, 108, 92, 104),
        mk(102, 106, 94, 103),
        mk(102.5, 105, 95, 103.5),
    ]
    f1 = analyze_bar(bars, 1, 3, atr=5.0, config=cfg)
    assert f1.is_inside and not f1.is_outside
    f3 = analyze_bar(bars, 3, 3, atr=5.0, config=cfg)
    assert f3.ii_count >= 2 and f3.label.startswith("II")

    out = [mk(100, 110, 90, 105), mk(100, 115, 85, 114)]  # outside + strong bull
    g = analyze_bar(out, 1, 1, atr=5.0, config=cfg)
    assert g.is_outside and g.is_strong_bull and g.label == "STRONG_BULL"


def test_overlap_and_barbwire() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(98, 103, 97, 101)] * 4 + [mk(99.5, 103, 97, 99.6)] + [mk(98, 103, 97, 101)]
    f = analyze_bar(bars, 5, 5, atr=5.0, config=cfg)
    assert f.barbwire, "Overlapping bodies + doji must trigger barbwire condition"
    assert pair_overlap(bars[0], bars[1]) >= cfg.overlap_ratio


def test_consecutive_runs_and_pressure() -> None:
    cfg = AnalyzerConfig()
    bars = [mk(100 + i * 2, 103 + i * 2, 99.5 + i * 2, 102.8 + i * 2) for i in range(8)]
    f = analyze_bar(bars, 7, 7, atr=2.0, config=cfg)
    assert f.consecutive == 8
    assert f.pressure_bull >= 7
    assert f.pressure_bear == 0


def test_series_analysis_and_atr() -> None:
    bars = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.5, "time": float(i)}
        for i in range(25)
    ]
    series = BarSeries(bars)
    atrs = calculate_atr_series(series, period=14)
    assert len(atrs) == 25
    assert atrs[-1] > 0.0

    features = analyze_series(series)
    assert len(features) == 25
    assert features[-1].valid is True
