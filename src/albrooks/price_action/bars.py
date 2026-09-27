"""Bar-by-bar price action feature calculation engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class BarFeatures:
    index: int
    valid: bool = False
    dir: int = 0
    range: float = 0.0
    body: float = 0.0
    body_ratio: float = 0.0
    close_pos: float = 0.5
    upper_tail: float = 0.0
    lower_tail: float = 0.0
    upper_ratio: float = 0.0
    lower_ratio: float = 0.0
    is_doji: bool = False
    is_big: bool = False
    is_small: bool = False
    is_strong_bull: bool = False
    is_strong_bear: bool = False
    is_inside: bool = False
    is_outside: bool = False
    overlap: float = 0.0
    gap_up: bool = False
    gap_down: bool = False
    consecutive: int = 0
    ii_count: int = 0
    pressure_bull: int = 0
    pressure_bear: int = 0
    barbwire: bool = False
    tightening: bool = False
    label: str = "NONE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_ohlc(b: Bar | dict[str, Any]) -> tuple[float, float, float, float]:
    if isinstance(b, Bar):
        return b.open, b.high, b.low, b.close
    open_v = float(b.get('o', b.get('open', 0.0)))
    high_v = float(b.get('h', b.get('high', 0.0)))
    low_v = float(b.get('l', b.get('low', 0.0)))
    close_v = float(b.get('c', b.get('close', 0.0)))
    return open_v, high_v, low_v, close_v


def _range(b: Bar | dict[str, Any]) -> float:
    _, high_v, low_v, _ = _get_ohlc(b)
    rg = high_v - low_v
    return rg if rg > 0.0 else 1e-9


def _body(b: Bar | dict[str, Any]) -> float:
    o, _, _, c = _get_ohlc(b)
    return abs(c - o)


def _dir(b: Bar | dict[str, Any]) -> int:
    o, _, _, c = _get_ohlc(b)
    if c > o:
        return 1
    if c < o:
        return -1
    return 0


def pair_overlap(a: Bar | dict[str, Any], b: Bar | dict[str, Any]) -> float:
    ao, ah, al, ac = _get_ohlc(a)
    bo, bh, bl, bc = _get_ohlc(b)
    ra, rb = ah - al, bh - bl
    m = min(ra, rb)
    if m <= 0.0:
        return 0.0
    top = min(max(ac, ao), max(bc, bo))
    bot = max(min(ac, ao), min(bc, bo))
    ov = top - bot
    return ov / m if ov > 0.0 else 0.0


def calculate_atr_series(bars: Sequence[Bar | dict[str, Any]], period: int = 14) -> list[float]:
    n = len(bars)
    if n == 0:
        return []
    atrs: list[float] = [0.0] * n
    trs: list[float] = [0.0] * n

    for i in range(n):
        _, bh, bl, _ = _get_ohlc(bars[i])
        if i == 0:
            trs[i] = bh - bl
        else:
            _, _, _, pc = _get_ohlc(bars[i - 1])
            trs[i] = max(bh - bl, abs(bh - pc), abs(bl - pc))

    if n < period:
        cum = 0.0
        for i in range(n):
            cum += trs[i]
            atrs[i] = cum / (i + 1)
        return atrs

    cum = sum(trs[:period])
    atrs[period - 1] = cum / period
    for i in range(period, n):
        atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period
    for i in range(period - 1):
        atrs[i] = atrs[period - 1]

    return atrs


def analyze_bar(
    bars: Sequence[Bar | dict[str, Any]],
    idx: int,
    last_closed: int,
    atr: float = 0.0,
    config: AnalyzerConfig | None = None,
) -> BarFeatures:
    cfg = config or AnalyzerConfig()
    if idx < 0 or idx > last_closed or idx >= len(bars):
        return BarFeatures(index=idx)

    b = bars[idx]
    o, h, low_v, c = _get_ohlc(b)
    rg = _range(b)
    bd = _body(b)
    br = bd / rg
    cp = (c - low_v) / rg
    d = _dir(b)
    up_t = h - max(c, o)
    lo_t = min(c, o) - low_v
    is_doji = br < cfg.doji_max_body

    is_big = False
    is_small = False
    if atr > 0:
        is_big = rg >= cfg.big_bar_atr * atr
        is_small = rg < cfg.small_bar_atr * atr

    is_strong_bull = d > 0 and cp >= cfg.strong_close_pct and br >= cfg.min_body_pct
    is_strong_bear = d < 0 and (1.0 - cp) >= cfg.strong_close_pct and br >= cfg.min_body_pct

    is_inside = False
    is_outside = False
    overlap = 0.0
    gap_up = False
    gap_down = False

    if idx - 1 >= 0:
        prev = bars[idx - 1]
        _, ph, pl, _ = _get_ohlc(prev)
        is_inside = h <= ph and low_v >= pl
        is_outside = (h >= ph and low_v <= pl) and (h > ph or low_v < pl)
        overlap = pair_overlap(b, prev)
        gap_up = low_v > ph
        gap_down = h < pl

    # Consecutive run
    consecutive = 0
    if not is_doji and d != 0:
        n = 0
        for i in range(idx, -1, -1):
            if i > last_closed:
                continue
            if _dir(bars[i]) != d:
                break
            n += 1
            if n >= 20:
                break
        consecutive = n if d > 0 else -n

    # Inside run count
    ii_count = 0
    if idx > 0:
        n = 0
        for i in range(idx, 0, -1):
            if i > last_closed:
                continue
            curr_b = bars[i]
            prev_b = bars[i - 1]
            _, ch, cl, _ = _get_ohlc(curr_b)
            _, prh, prl, _ = _get_ohlc(prev_b)
            if ch <= prh and cl >= prl:
                n += 1
            else:
                break
        ii_count = n

    # Cumulative pressure over lookback
    pb, pe = 0, 0
    lookback = max(1, cfg.pressure_lookback)
    for i in range(idx, max(-1, idx - lookback), -1):
        if i < 0 or i > last_closed:
            continue
        cur = bars[i]
        co, ch, cl, cc = _get_ohlc(cur)
        crg = _range(cur)
        cdir = _dir(cur)
        ccp = (cc - cl) / crg
        cbr = _body(cur) / crg
        if cdir > 0 and ccp >= cfg.strong_close_pct and cbr >= cfg.min_body_pct:
            pb += 1
        if cdir < 0 and (1.0 - ccp) >= cfg.strong_close_pct and cbr >= cfg.min_body_pct:
            pe += 1

    # Barbwire detection
    w_bars = max(3, cfg.barbwire_bars)
    ovn = 0
    any_doji = False
    for i in range(idx, max(-1, idx - w_bars), -1):
        if i <= 0 or i > last_closed:
            continue
        if pair_overlap(bars[i], bars[i - 1]) >= cfg.overlap_ratio:
            ovn += 1
        crg = _range(bars[i])
        cbd = _body(bars[i])
        if cbd / crg < cfg.doji_max_body:
            any_doji = True
    tail = idx - w_bars
    if 0 <= tail <= last_closed:
        trg = _range(bars[tail])
        tbd = _body(bars[tail])
        if tbd / trg < cfg.doji_max_body:
            any_doji = True
    barbwire = ovn >= cfg.barbwire_min_overlap and any_doji

    # Tightening / range compression
    tightening = False
    if idx - 4 >= 0:
        window_ranges = sorted(_range(bars[i]) for i in range(idx - 4, idx))
        med = (window_ranges[1] + window_ranges[2]) * 0.5
        tightening = (h - low_v) < med

    label = "BAR"
    if is_strong_bull:
        label = "STRONG_BULL"
    elif is_strong_bear:
        label = "STRONG_BEAR"
    elif ii_count >= 2:
        label = f"II{ii_count}"
    elif is_big:
        label = "BIG"
    elif is_doji:
        label = "DOJI"
    elif is_outside:
        label = "OUTSIDE"
    elif is_inside:
        label = "INSIDE"
    elif gap_up or gap_down:
        label = "GAP"

    return BarFeatures(
        index=idx,
        valid=True,
        dir=d,
        range=rg,
        body=bd,
        body_ratio=br,
        close_pos=cp,
        upper_tail=up_t,
        lower_tail=lo_t,
        upper_ratio=up_t / rg,
        lower_ratio=lo_t / rg,
        is_doji=is_doji,
        is_big=is_big,
        is_small=is_small,
        is_strong_bull=is_strong_bull,
        is_strong_bear=is_strong_bear,
        is_inside=is_inside,
        is_outside=is_outside,
        overlap=overlap,
        gap_up=gap_up,
        gap_down=gap_down,
        consecutive=consecutive,
        ii_count=ii_count,
        pressure_bull=pb,
        pressure_bear=pe,
        barbwire=barbwire,
        tightening=tightening,
        label=label,
    )


def analyze_series(
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    config: AnalyzerConfig | None = None,
) -> list[BarFeatures]:
    cfg = config or AnalyzerConfig()
    n = len(bars)
    if n == 0:
        return []
    atrs = calculate_atr_series(bars, period=cfg.atr_period)
    last_closed = n - 1
    return [
        analyze_bar(bars, i, last_closed=last_closed, atr=atrs[i], config=cfg)
        for i in range(n)
    ]
