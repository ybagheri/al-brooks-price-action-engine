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

## Trade plans and the decision

The setups the registry found are planned by `albrooks.trade.plan`, and the plans
are gated and ranked by `albrooks.decision.decide()`. Only setups the run found
are planned, so the plan layer adds no detection of its own and wiring it in cannot
introduce a new lookahead surface.

The decision is the last step and is allowed to answer `BUY` / `SELL` / `WAIT` /
`NO_TRADE`. It is a **ranking by declared criteria** (`RANKING_BASIS`), not a
validated edge: nothing in this project has been checked against outcomes, and
`Decision.to_dict()` says so with `is_probability: false`. `enable_decision=False`
makes it answer `NO_TRADE` / `DECISION_DISABLED` rather than infer anything.

## The closed-bar contract

`last_closed` is threaded into every stage, and the result records the value used
in `last_closed_bar`. Two properties follow, and both are asserted in the tests:

1. Analysis for a given `last_closed` is **identical** whether or not later bars
   exist. Appending future bars cannot change the output for an earlier index.
2. A `last_closed` past the available data is **clamped**, not rejected, matching
   every detector's own behaviour.

Both are `RPC-1` and `RPC-4` of `docs/algorithms/NON_REPAINT_CONTRACT.md`.
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
from albrooks.decision.engine import candidates_from_findings, decide
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult
from albrooks.price_action.bars import analyze_series, calculate_atr_series
from albrooks.setups.base import SetupContext, SetupFinding, family_for
from albrooks.setups.measured_move import detect_measured_moves
from albrooks.setups.registry import RegistryRun, SetupRegistry, build_default_registry

#: Setup family -> the evidence `source` label the flat evidence list uses.
#:
#: The Phase 13 evidence model knows five vocabularies; a sixth family exists only
#: to file a finding under, and it inherits the label the model already uses so the
#: two lists still agree.
_EVIDENCE_SOURCE: dict[str, str] = {
    "PULLBACK": "PULLBACK",
    "BREAKOUT": "BREAKOUT",
    "REVERSAL": "REVERSAL",
    "MEASURED_MOVE": "MEASURED_MOVE",
    "FADING_MEASURED_MOVE": "MEASURED_MOVE",
}

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

    def __init__(
        self,
        config: AnalyzerConfig | None = None,
        registry: SetupRegistry | None = None,
    ) -> None:
        self.config = config or AnalyzerConfig()
        #: The detectors this analyzer runs. Defaults to the eleven the package
        #: ships, built fresh per analyzer.
        #:
        #: `DEFAULT_REGISTRY` is deliberately **not** read here. It exists for the
        #: mutate-on-import pattern a third party might prefer, but a
        #: process-wide mutable global would make behaviour depend on import order
        #: and on test order, so a caller who wants extra detectors passes its own
        #: registry instead. That is the difference between an opt-in and an
        #: ambient dependency, and `registry.py` already argues for it.
        self.registry = registry or build_default_registry()

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
        # Detection goes through the registry, so the pipeline holds exactly one
        # detection path: the eleven detectors the registry ships, run over one
        # context. Calling them directly as well would mean two implementations of
        # "what did this setup detector find", and `CONTRIBUTING.md` rule 5
        # forbids that. The registry's own `executed` / `skipped` maps report what
        # ran, so nothing is lost by grouping findings rather than reporting a
        # not-found payload per family.
        #
        # The plan and decision layers read bars `0..closed` only, so they are
        # handed the analysed window rather than the full series. `BarSeries`
        # slicing keeps their own closed-bar contract intact without either layer
        # needing its own `last_closed`.
        window = series[: closed + 1]
        run = self.registry.run(
            SetupContext(
                bars=window,
                last_closed=closed,
                atr=atr,
                config=self.config,
                swings=swings,
                legs=legs,
                idx=closed,
            )
        )
        findings = list(run.findings)

        candidates = candidates_from_findings(
            findings,
            bars=window,
            last_closed=closed,
            atr=atr,
            market_state=state.to_dict(),
            config=self.config,
        )
        decision = decide(
            candidates,
            bars=window,
            last_closed=closed,
            atr=atr,
            config=self.config,
        )

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
            setups=self._setups(findings),
            trade_plans=[c.plan.to_dict() for c in candidates],
            decision=decision.to_dict(),
            warnings=self._warnings(n, closed, swings, state)
            + self._registry_warnings(run),
            bar_features=[f.to_dict() for f in features],
            trends=[trend.to_dict()],
            # `detect_channel` always returns a PriceChannel; the default is an
            # empty one whose `direction` is 0, so presence is tested on that
            # rather than on a truthiness check that a populated zero-width
            # channel would also pass.
            channels=[channel.to_dict()] if channel.direction != 0 else [],
            pullbacks=self._group(findings, "PULLBACK"),
            breakouts=self._group(findings, "BREAKOUT"),
            reversals=self._group(findings, "REVERSAL"),
            evidence=self._evidence(state, moves, findings),
            findings=[f.to_dict() for f in findings],
            detectors={
                "executed": list(run.executed),
                "skipped": dict(run.skipped),
                "failed": [f.to_dict() for f in run.failures],
            },
            layers=self._layers(),
        )

    # -- layer helpers ----------------------------------------------------

    @staticmethod
    def _registry_warnings(run: RegistryRun) -> list[str]:
        """Registry problems, promoted to result warnings.

        A detector that raised is contained by the registry, which means a run can
        quietly come back with fewer setups than it should. That must be visible at
        the top level, or "nothing found" and "something broke" look alike.
        """
        out = [f"DETECTOR_FAILED:{f.detector}" for f in run.failures]
        out.extend(f"DETECTOR_SKIPPED:{name}" for name in sorted(run.skipped))
        return out

    def _setups(self, findings: Sequence[SetupFinding]) -> list[dict[str, Any]]:
        """Every finding, in registration order, labelled by detector and family.

        Registration order is what `SETUP_ENGINE.md` §5 promises and it is **not**
        a ranking: the decision engine is the one place that compares setups.
        """
        return [self._entry(finding) for finding in findings]

    @staticmethod
    def _entry(finding: SetupFinding) -> dict[str, Any]:
        """One finding as the pipeline reports it, in every layer that reports it.

        Built by one function so `setups` and the per-family layers cannot describe
        the same run differently.

        The pipeline's family key is `setup_family` rather than `family` because a
        payload may already use that name for its own narrower classification — a
        `MEASURED_MOVE` finding's `family` is `RANGE` or `CHANNEL`, and
        overwriting it would throw away the projection family. Naming the two
        separately costs a few characters and keeps both readable.
        """
        return {
            **finding.payload,
            "detector": finding.detector,
            "kind": finding.kind,
            "setup_family": family_for(finding.detector, finding.kind),
            "direction": finding.direction,
        }

    def _group(
        self, findings: Sequence[SetupFinding], family: str
    ) -> list[dict[str, Any]]:
        """The subset of `setups` belonging to one setup family.

        Grouping is by the shared `FAMILY_BY_DETECTOR` mapping rather than by the
        registry's `kind`, because two of the eleven shipped detectors are
        registered with the default `kind` and would otherwise be unfileable.
        """
        return [
            entry
            for entry in (self._entry(f) for f in findings)
            if entry["setup_family"] == family
        ]

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
        findings: Sequence[SetupFinding],
    ) -> list[dict[str, Any]]:
        """Flatten the layers' own evidence into one list with stable codes.

        Sources keep their own vocabulary and are labelled by `source` rather than
        merged into a single score: a market-state reason and a measured-move
        factor measure different things, and summing them would imply a
        comparability that does not exist.

        The setup contributions come from the registry's findings rather than from
        detectors called here, so this list and `setups` cannot describe different
        runs. Every finding is already a *found* one — the registry filters
        not-found results — so there is no `found` check left to make.
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
        for finding in findings:
            out.append(
                {
                    "source": _EVIDENCE_SOURCE.get(
                        family_for(finding.detector, finding.kind), "SETUP"
                    ),
                    "code": self._setup_code(finding.payload),
                    "detail": "",
                    "detector": finding.detector,
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
            "trade_plans": True,
            "decision": True,
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

