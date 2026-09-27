"""The setup registry: one place that knows which detectors exist.

## What this is for

`ARCHITECTURE.md` §9 states that new setups must be addable without modifying the
central analyzer, and that if a detector requires editing `engine/analyzer.py` the
architecture has been violated. This module is what makes that claim true rather
than aspirational: adding a detector is a `register()` call, and the analyzer runs
whatever is registered.

## What it deliberately does not do

It does not **rank** findings. There is no "best setup" and no score here. Ranking
requires comparing setups that are not comparable today — a measured-move target and
a reversal signal are different kinds of claim — and picking between them is the
decision engine's job (Phase 15). A registry that returned a "winner" would be
making a trade decision while claiming to be a lookup table.

Findings are returned in **registration order**, which is deterministic and
predictable, and is not a ranking.

## Failure is contained

A detector that raises is recorded as a `DetectorFailure` and the run continues. One
broken detector must not take down every other layer, and a caller needs to know it
happened rather than silently receiving fewer findings. `strict=True` re-raises for
callers who would rather fail loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from albrooks.setups.base import (
    SetupContext,
    SetupDetector,
    SetupFinding,
    adapt,
)


class RegistryError(Exception):
    """Base class for registry misuse."""


class DuplicateDetectorError(RegistryError):
    """A detector name was registered twice.

    Silently replacing an existing detector would make the run order depend on
    import order, so a duplicate is an error the caller has to resolve.
    """


class UnknownDetectorError(RegistryError):
    """A detector name was requested that is not registered."""


@dataclass(frozen=True, slots=True)
class DetectorFailure:
    """A detector that raised, recorded rather than propagated by default."""

    detector: str
    error: BaseException

    def to_dict(self) -> dict[str, Any]:
        return {"detector": self.detector, "error": repr(self.error)}


@dataclass(frozen=True, slots=True)
class RegistryRun:
    """The result of running every enabled detector over one context."""

    findings: list[SetupFinding] = field(default_factory=list)
    failures: list[DetectorFailure] = field(default_factory=list)
    #: Names that ran, in order, whether or not they found anything.
    executed: list[str] = field(default_factory=list)
    #: Names that were skipped, with the reason. A detector skipped for missing
    #: volatility is a different statement from one that ran and found nothing.
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failures

    def by_detector(self) -> dict[str, list[SetupFinding]]:
        out: dict[str, list[SetupFinding]] = {}
        for finding in self.findings:
            out.setdefault(finding.detector, []).append(finding)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "failures": [f.to_dict() for f in self.failures],
            "executed": list(self.executed),
            "skipped": dict(self.skipped),
        }


class SetupRegistry:
    """An ordered collection of named setup detectors.

    Ordering is registration order and is stable, so a run is reproducible without
    any detector being ranked against another.
    """

    def __init__(self, detectors: list[SetupDetector] | None = None) -> None:
        self._detectors: dict[str, SetupDetector] = {}
        for detector in detectors or []:
            self.register(detector)

    # -- registration ---------------------------------------------------

    def register(
        self,
        detector: SetupDetector,
        *,
        name: str | None = None,
        replace: bool = False,
    ) -> SetupDetector:
        """Add a detector. Returns it, so it can be registered inline.

        `replace=True` is the explicit way to override a name; without it a
        duplicate raises, because a silent replacement would make behaviour depend
        on import order.
        """
        key = name or getattr(detector, "name", "")
        if not key:
            raise RegistryError(
                f"detector {detector!r} has no name; pass name= or set .name"
            )
        if key in self._detectors and not replace:
            raise DuplicateDetectorError(
                f"detector {key!r} is already registered; pass replace=True to override"
            )
        self._detectors[key] = detector
        return detector

    def register_all(
        self, detectors: list[SetupDetector], *, replace: bool = False
    ) -> list[SetupDetector]:
        return [self.register(d, replace=replace) for d in detectors]

    def unregister(self, name: str) -> None:
        if name not in self._detectors:
            raise UnknownDetectorError(f"no detector named {name!r} is registered")
        del self._detectors[name]

    # -- inspection -----------------------------------------------------

    @property
    def names(self) -> list[str]:
        return list(self._detectors)

    def __contains__(self, name: object) -> bool:
        return name in self._detectors

    def __iter__(self) -> Iterator[SetupDetector]:
        return iter(list(self._detectors.values()))

    def __len__(self) -> int:
        return len(self._detectors)

    def get(self, name: str) -> SetupDetector:
        if name not in self._detectors:
            raise UnknownDetectorError(
                f"no detector named {name!r}; registered: {self.names}"
            )
        return self._detectors[name]

    def select(self, names: list[str] | None = None) -> list[SetupDetector]:
        """Detectors in registration order, optionally restricted to `names`.

        Restricted detectors keep *registration* order rather than the order the
        caller listed them in, so passing the same set always gives the same run
        order regardless of how it was written.
        """
        if names is None:
            return list(self._detectors.values())
        wanted = set(names)
        unknown = wanted - set(self._detectors)
        if unknown:
            raise UnknownDetectorError(
                f"not registered: {sorted(unknown)}; available: {self.names}"
            )
        return [d for k, d in self._detectors.items() if k in wanted]

    # -- execution ------------------------------------------------------

    def run(
        self,
        context: SetupContext,
        *,
        only: list[str] | None = None,
        strict: bool = False,
        skip_if_unusable: bool = True,
    ) -> RegistryRun:
        """Run the selected detectors over `context`.

        `strict=True` re-raises the first detector failure instead of recording it,
        for callers who would rather stop than receive a partial answer.
        """
        detectors = self.select(only)
        run = RegistryRun()

        if skip_if_unusable and not context.is_usable:
            # Recorded as skipped rather than silently omitted: "we could not
            # measure this" must not look like "we measured and found nothing".
            for detector in detectors:
                run.skipped[detector.name] = _unusable_reason(context)
            return run

        for detector in detectors:
            run.executed.append(detector.name)
            try:
                run.findings.extend(detector.detect(context))
            except Exception as error:  # noqa: BLE001 - containment is the point
                if strict:
                    raise
                run.failures.append(
                    DetectorFailure(detector=detector.name, error=error)
                )
        return run


def _unusable_reason(context: SetupContext) -> str:
    if not context.has_volatility:
        return "NO_ATR"
    if context.last_closed < 0:
        return "NO_CLOSED_BARS"
    return "UNUSABLE_CONTEXT"


#: Process-wide default, so a third-party package can register a detector on
#: import and have the analyzer pick it up without either side importing the
#: other. `build_default_registry()` is preferred in library code and tests,
#: because a shared mutable global makes test order matter.
DEFAULT_REGISTRY = SetupRegistry()


def build_default_registry() -> SetupRegistry:
    """A registry holding every setup detector this package ships.

    Each entry is an `adapt()` wrapper rather than a rewritten detector, which is
    the point: the detectors keep the signatures their own phases defined, and the
    registry learns to call them. Adding a Phase 12+ detector is one more line here,
    or none at all if a third party registers its own.
    """
    from albrooks.setups import breakout as breakout_module
    from albrooks.setups import double as double_module
    from albrooks.setups import fading_measured_move as fm_module
    from albrooks.setups import measured_move as mm_module
    from albrooks.setups import pullback as pullback_module
    from albrooks.setups import reversal as reversal_module

    def pullback(ctx: SetupContext) -> Any:
        return pullback_module.detect_h1_h2(
            ctx.bars, ctx.idx, ctx.last_closed, ctx.atr, config=ctx.config
        )

    def l_pullback(ctx: SetupContext) -> Any:
        return pullback_module.detect_l1_l2(
            ctx.bars, ctx.idx, ctx.last_closed, ctx.atr, config=ctx.config
        )

    def breakout(ctx: SetupContext) -> Any:
        return breakout_module.analyze_breakout(
            ctx.bars, ctx.idx, ctx.last_closed, ctx.atr,
            swings=ctx.swings, config=ctx.config,
        )

    def reversal(direction: int) -> Callable[[SetupContext], Any]:
        def run(ctx: SetupContext) -> Any:
            return reversal_module.analyze_reversal(
                ctx.bars, ctx.idx, ctx.last_closed, ctx.atr,
                swings=ctx.swings, reversal_direction=direction, config=ctx.config,
            )

        return run

    def micro_double_top(ctx: SetupContext) -> Any:
        return double_module.detect_micro_double_top(
            ctx.bars, ctx.idx, ctx.last_closed, ctx.atr, config=ctx.config
        )

    def micro_double_bottom(ctx: SetupContext) -> Any:
        return double_module.detect_micro_double_bottom(
            ctx.bars, ctx.idx, ctx.last_closed, ctx.atr, config=ctx.config
        )

    def major_double_top(ctx: SetupContext) -> Any:
        # Takes swings only — no bars — which is exactly why the protocol needs a
        # context object rather than a fixed parameter list.
        return double_module.find_major_double_top(
            ctx.swings, ctx.atr, config=ctx.config
        )

    def major_double_bottom(ctx: SetupContext) -> Any:
        return double_module.find_major_double_bottom(
            ctx.swings, ctx.atr, config=ctx.config
        )

    def measured_moves(ctx: SetupContext) -> Any:
        return mm_module.detect_measured_moves(
            ctx.bars, ctx.swings, atr=ctx.atr, last_closed=ctx.last_closed,
            legs=ctx.legs, config=ctx.config,
        )

    def fading_measured_moves(ctx: SetupContext) -> Any:
        return fm_module.create_setups(
            ctx.bars, last_closed=ctx.last_closed, atr=ctx.atr,
            swings=ctx.swings, legs=ctx.legs, config=ctx.config,
        )

    def _fading_present(value: Any, payload: dict[str, Any]) -> bool:
        """A fade setup is a finding whenever it exists, terminal or not.

        Stated explicitly rather than left to the default. The default
        (`payload.get("found", True)`) already gets this right, because
        `FadingSetup` has no `found` field to be read as `False` — so this hook
        is a statement of intent, not a fix. It is here so that a future change to
        the default, or a `found` field added to `FadingSetup` later, cannot
        quietly start dropping terminal fades from the output.
        """
        return True

    def _fading_direction(value: Any, payload: dict[str, Any]) -> int:
        # The fade runs *against* the projection, so the trade-facing direction is
        # the fade direction, not the projection's.
        return int(getattr(value, "fade_direction", 0) or 0)

    return SetupRegistry(
        [
            adapt("PULLBACK_H", pullback),
            adapt("PULLBACK_L", l_pullback),
            adapt("BREAKOUT", breakout),
            adapt("REVERSAL_BULL", reversal(1), kind="REVERSAL"),
            adapt("REVERSAL_BEAR", reversal(-1), kind="REVERSAL"),
            adapt("DOUBLE_TOP_MAJOR", major_double_top, kind="DOUBLE_TOP"),
            adapt("DOUBLE_BOTTOM_MAJOR", major_double_bottom, kind="DOUBLE_BOTTOM"),
            adapt("DOUBLE_TOP_MICRO", micro_double_top, kind="DOUBLE_TOP"),
            adapt("DOUBLE_BOTTOM_MICRO", micro_double_bottom, kind="DOUBLE_BOTTOM"),
            adapt("MEASURED_MOVE", measured_moves, kind="MEASURED_MOVE"),
            adapt(
                "FADING_MEASURED_MOVE",
                fading_measured_moves,
                kind="FADING_MEASURED_MOVE",
                present=_fading_present,
                direction=_fading_direction,
            ),
        ]
    )
