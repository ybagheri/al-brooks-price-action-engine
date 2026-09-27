"""State models and containers for comprehensive analysis results."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisResult:
    """Unified, serializable container representing the complete price-action analysis."""

    symbol: str
    timeframe: str
    bars_processed: int
    market_state: dict[str, Any] = field(default_factory=dict)
    swings: list[dict[str, Any]] = field(default_factory=list)
    legs: list[dict[str, Any]] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    measured_moves: list[dict[str, Any]] = field(default_factory=list)
    setups: list[dict[str, Any]] = field(default_factory=list)
    trade_plans: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    bar_features: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert analysis result to a clean, JSON-serializable Python dictionary."""
        return asdict(self)

    def to_json(self, indent: int | None = None) -> str:
        """Serialize analysis result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)
