"""State models and containers for comprehensive analysis results."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

#: Marker for a layer that is not implemented yet, so a caller can tell
#: "not detected" apart from "never looked for". These are deliberately visible
#: in the output rather than hidden behind an empty list: an empty `pullbacks`
#: is a claim about the market, and an unimplemented layer must not make it.
NOT_IMPLEMENTED = "NOT_IMPLEMENTED_YET"


@dataclass(frozen=True)
class AnalysisResult:
    """Unified, serializable container representing the complete price-action analysis.

    Bar indexing is oldest-first throughout, matching the engine: index `0` is
    the oldest bar and `last_closed_bar` the newest analysed.
    """

    symbol: str
    timeframe: str
    bars_processed: int
    #: Newest bar the analysis is allowed to read. Every field below is derived
    #: from bars `0..last_closed_bar` only, which is what makes the output for a
    #: given index independent of whether later bars exist.
    last_closed_bar: int = -1
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

    # Layers named by the specification. Each holds `{"available": bool, ...}`;
    # `available=False` marks a layer that is not implemented, which is a
    # different statement from "nothing was found".
    trends: list[dict[str, Any]] = field(default_factory=list)
    channels: list[dict[str, Any]] = field(default_factory=list)
    pullbacks: list[dict[str, Any]] = field(default_factory=list)
    breakouts: list[dict[str, Any]] = field(default_factory=list)
    reversals: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    #: Every setup detector finding for this run, in the registry's registration
    #: order — which is deterministic and is **not** a ranking. `setups` is the
    #: same list with a `detector` label attached, so a caller that wants the
    #: normalised shape has one and a caller that wants the raw finding has the
    #: other. Doubles and fading measured moves appear here from Phase 16, which is
    #: when the pipeline started reading the registry rather than calling four
    #: detectors directly.
    findings: list[dict[str, Any]] = field(default_factory=list)
    #: What the registry did: `executed` names, `skipped` reasons, `failed`
    #: entries. This is what distinguishes "a detector ran and found nothing" from
    #: "a detector could not be measured" from "a detector raised", none of which
    #: the finding list can express.
    detectors: dict[str, Any] = field(default_factory=dict)
    #: Which pipeline layers actually ran, so a caller can tell an empty layer
    #: ("nothing found") from an absent one ("not implemented"). Set by the
    #: pipeline, never inferred from the emptiness of the other fields.
    layers: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert analysis result to a clean, JSON-serializable Python dictionary."""
        return asdict(self)

    def to_json(self, indent: int | None = None) -> str:
        """Serialize analysis result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @property
    def unimplemented_layers(self) -> list[str]:
        """Layers this result makes no claim about, for an honest self-report.

        Read from `layers`, not inferred from an empty list: "no channel was
        found" and "channel detection is not implemented" are different claims,
        and only the pipeline knows which one applies.
        """
        return [name for name, ran in self.layers.items() if not ran]
