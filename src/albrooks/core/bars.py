"""Normalized OHLCV Bar and BarSeries abstractions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence


@dataclass(frozen=True, slots=True)
class Bar:
    """Immutable normalized OHLCV single bar representation.

    Oldest-first indexing is assumed throughout the engine (index 0 = oldest).
    """

    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    index: int = 0

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"Bar high ({self.high}) cannot be less than low ({self.low})")
        if self.open < self.low or self.open > self.high:
            raise ValueError(f"Bar open ({self.open}) outside [{self.low}, {self.high}]")
        if self.close < self.low or self.close > self.high:
            raise ValueError(f"Bar close ({self.close}) outside [{self.low}, {self.high}]")
        if self.volume < 0:
            raise ValueError(f"Bar volume ({self.volume}) cannot be negative")

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_bull(self) -> bool:
        return self.close > self.open

    @property
    def is_bear(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        r = self.range
        return (self.body <= 0.15 * r) if r > 1e-9 else True

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def close_location(self) -> float:
        r = self.range
        return (self.close - self.low) / r if r > 1e-9 else 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "index": self.index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bar:
        return cls(
            time=float(data.get("time", 0.0)),
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data.get("volume", 0.0)),
            index=int(data.get("index", 0)),
        )


@dataclass(frozen=True)
class BarSeries:
    """Immutable sequence of closed bars with metadata and forward indexing (0 = oldest)."""

    bars: tuple[Bar, ...]
    symbol: str = "GENERIC"
    timeframe: str = "UNKNOWN"

    def __init__(
        self,
        bars: Sequence[Bar | dict[str, Any]],
        symbol: str = "GENERIC",
        timeframe: str = "UNKNOWN",
    ) -> None:
        normalized: list[Bar] = []
        for i, b in enumerate(bars):
            if isinstance(b, Bar):
                if b.index != i:
                    b = Bar(
                        time=b.time,
                        open=b.open,
                        high=b.high,
                        low=b.low,
                        close=b.close,
                        volume=b.volume,
                        index=i,
                    )
                normalized.append(b)
            elif isinstance(b, dict):
                norm_dict = dict(b)
                norm_dict["index"] = i
                normalized.append(Bar.from_dict(norm_dict))
            else:
                raise TypeError(f"Expected Bar or dict, got {type(b)}")
        object.__setattr__(self, "bars", tuple(normalized))
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timeframe", timeframe)

    def __len__(self) -> int:
        return len(self.bars)

    def __getitem__(self, idx: int | slice) -> Any:
        return self.bars[idx]

    def __iter__(self) -> Iterator[Bar]:
        return iter(self.bars)

    @property
    def opens(self) -> tuple[float, ...]:
        return tuple(b.open for b in self.bars)

    @property
    def highs(self) -> tuple[float, ...]:
        return tuple(b.high for b in self.bars)

    @property
    def lows(self) -> tuple[float, ...]:
        return tuple(b.low for b in self.bars)

    @property
    def closes(self) -> tuple[float, ...]:
        return tuple(b.close for b in self.bars)

    @property
    def times(self) -> tuple[float, ...]:
        return tuple(b.time for b in self.bars)

    def append(self, bar: Bar | dict[str, Any]) -> BarSeries:
        new_bars = list(self.bars)
        new_idx = len(new_bars)
        if isinstance(bar, Bar):
            new_bar = Bar(
                time=bar.time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                index=new_idx,
            )
        else:
            d = dict(bar)
            d["index"] = new_idx
            new_bar = Bar.from_dict(d)
        new_bars.append(new_bar)
        return BarSeries(new_bars, symbol=self.symbol, timeframe=self.timeframe)

    def to_list(self) -> list[dict[str, Any]]:
        return [b.to_dict() for b in self.bars]
