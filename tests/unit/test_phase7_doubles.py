"""Unit tests for Phase 7 Double Tops and Double Bottoms Engine."""

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.double import (
    detect_micro_double_bottom,
    detect_micro_double_top,
    find_major_double_bottom,
    find_major_double_top,
)


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def test_major_double_top_in_tolerance() -> None:
    cfg = AnalyzerConfig(double_tol_atr=0.25)
    sw = [
        {"bar": 0, "price": 100.0, "dir": 1},
        {"bar": 2, "price": 94.0, "dir": -1},
        {"bar": 4, "price": 100.1, "dir": 1},
        {"bar": 6, "price": 93.0, "dir": -1},
        {"bar": 8, "price": 100.05, "dir": 1},
    ]
    d = find_major_double_top(sw, 2.0, cfg)
    assert d.found and d.direction == -1 and not d.is_micro
    assert (d.bar1, d.bar2) == (4, 8)  # most-recent pair wins


def test_major_double_top_rejected() -> None:
    cfg = AnalyzerConfig(double_tol_atr=0.25)
    # 1. Out of tolerance: |101 - 100| = 1.0 > 0.25 * 2 = 0.5
    sw1 = [
        {"bar": 0, "price": 100.0, "dir": 1},
        {"bar": 5, "price": 95.0, "dir": -1},
        {"bar": 10, "price": 101.0, "dir": 1},
    ]
    assert not find_major_double_top(sw1, 2.0, cfg).found

    # 2. Shallow trough: 100 - 99.8 = 0.2 < 0.5 * 2 = 1.0
    sw2 = [
        {"bar": 0, "price": 100.0, "dir": 1},
        {"bar": 5, "price": 99.8, "dir": -1},
        {"bar": 10, "price": 100.1, "dir": 1},
    ]
    assert not find_major_double_top(sw2, 2.0, cfg).found


def test_major_double_bottom() -> None:
    cfg = AnalyzerConfig(double_tol_atr=0.25)
    sw = [
        {"bar": 1, "price": 90.0, "dir": -1},
        {"bar": 6, "price": 95.0, "dir": 1},
        {"bar": 11, "price": 90.2, "dir": -1},
    ]
    d = find_major_double_bottom(sw, 2.0, cfg)
    assert d.found and d.direction == 1 and not d.is_micro
    assert (d.bar1, d.bar2) == (1, 11)


def test_micro_double_top_and_bottom() -> None:
    cfg = AnalyzerConfig(double_tol_atr=0.25)
    bars_top = [
        mk(98, 100.0, 97, 98),  # 0
        mk(98, 97.0, 96, 96.5),  # 1 trough dip
        mk(97, 100.1, 97, 99.5),  # 2 test of high
    ]
    d_top = detect_micro_double_top(bars_top, 2, 2, atr=2.0, config=cfg)
    assert d_top.found and d_top.is_micro and d_top.direction == -1
    assert (d_top.bar1, d_top.bar2) == (0, 2)

    bars_bot = [
        mk(102, 103, 90.0, 101),  # 0
        mk(101, 105, 101, 104),  # 1 rally peak
        mk(104, 104, 90.1, 91),  # 2 test of low
    ]
    d_bot = detect_micro_double_bottom(bars_bot, 2, 2, atr=2.0, config=cfg)
    assert d_bot.found and d_bot.is_micro and d_bot.direction == 1
    assert (d_bot.bar1, d_bot.bar2) == (0, 2)
