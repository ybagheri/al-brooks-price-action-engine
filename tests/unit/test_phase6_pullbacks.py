"""Unit tests for Phase 6 H1/H2 and L1/L2 Pullback Entry Engines."""

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.h1_h2 import detect_h1_h2
from albrooks.setups.l1_l2 import detect_l1_l2
from albrooks.setups.pullback import determine_trend_direction


def mk(o: float, h: float, low_val: float, c: float) -> dict[str, float]:
    return {"o": o, "h": h, "l": low_val, "c": c}


def flat_top_uptrend(
    n: int = 50, h: float = 200.0, low_val: float = 190.0, c0: float = 193.0, slope: float = 0.1
) -> list[dict[str, float]]:
    return [mk(c0 + i * slope - 0.5, h, low_val, c0 + i * slope) for i in range(n)]


def flat_top_downtrend(
    n: int = 50, h: float = 210.0, low_val: float = 200.0, c0: float = 207.0, slope: float = 0.1
) -> list[dict[str, float]]:
    return [mk(c0 - i * slope + 0.5, h, low_val, c0 - i * slope) for i in range(n)]


def test_h1_h2_two_legs() -> None:
    cfg = AnalyzerConfig(max_pb_bars=12, min_pb_ratio=0.15)
    bars = flat_top_uptrend(50)
    bars += [
        mk(198, 200, 189, 196),  # 50 pullback dip
        mk(196, 202, 191, 201),  # 51 H1: 202 > 200
        mk(201, 200, 187, 192),  # 52 second leg: 187 < 189
        mk(192, 203, 190, 202),  # 53 H2: 203 > 200
        mk(202, 205, 200, 204),  # 54
        mk(204, 207, 202, 206),  # 55
    ]
    idx = 55
    assert determine_trend_direction(bars, idx, idx, 2.0) == 1
    s = detect_h1_h2(bars, idx, idx, 2.0, cfg)
    assert s.found and s.legs == 2
    assert s.setup_type == "H2"
    assert s.anchor_bar == 51
    assert s.signal_bar == 53
    assert s.reference_price == 203.0
    assert s.stop_price == 187.0


def test_h1_only_no_second_leg() -> None:
    cfg = AnalyzerConfig(max_pb_bars=12, min_pb_ratio=0.15)
    bars = flat_top_uptrend(50)
    bars += [
        mk(198, 200, 189, 196),  # 50 dip
        mk(196, 202, 191, 201),  # 51 H1
        mk(201, 200, 190, 198),  # 52 no lower low (190 !< 189)
        mk(198, 203, 191, 202),  # 53 higher but no second leg dip first
        mk(202, 205, 200, 204),
        mk(204, 207, 202, 206),
    ]
    s = detect_h1_h2(bars, 55, 55, 2.0, cfg)
    assert s.found and s.legs == 1
    assert s.setup_type == "H1"
    assert s.signal_bar == 51
    assert s.anchor_bar == 51


def test_l1_l2_bear_mirror() -> None:
    cfg = AnalyzerConfig(max_pb_bars=12, min_pb_ratio=0.15)
    bars = flat_top_downtrend(50)
    bars += [
        mk(202, 211, 200, 204),  # 50 rally peak
        mk(204, 209, 198, 199),  # 51 L1: 198 < 200
        mk(199, 213, 200, 208),  # 52 second leg rally: 213 > 211
        mk(208, 210, 197, 198),  # 53 L2: 197 < 200
        mk(198, 200, 195, 196),
        mk(196, 198, 193, 194),
    ]
    idx = 55
    assert determine_trend_direction(bars, idx, idx, 2.0) == -1
    s = detect_l1_l2(bars, idx, idx, 2.0, cfg)
    assert s.found and s.legs == 2
    assert s.setup_type == "L2"
    assert s.anchor_bar == 51
    assert s.signal_bar == 53
    assert s.reference_price == 197.0
    assert s.stop_price == 213.0
