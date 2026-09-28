"""The setup detector protocol, and the adapter that lets existing detectors join.

## The problem this solves

Every detector in this engine was written against the shape its own phase needed,
so their signatures genuinely differ:

| Detector | Signature | Returns |
|---|---|---|
| `detect_h1_h2` | `(bars, idx, last_closed, atr, config)` | one `PullbackSetup` |
| `analyze_breakout` | `(bars, idx, last_closed, atr, swings, config)` | one `BreakoutResult` |
| `find_major_double_top` | `(swings, atr, config)` — **no bars at all** | one `DoublePattern` |
| `detect_measured_moves` | `(bars, swings, atr, last_closed, legs, config)` | a **list** |
| `create_setups` | `(bars, last_closed, atr, swings, legs, config)` | a **list** |

`find_major_double_top` reads only swings, not bars, and two detectors return lists
while four return a single object. A registry that has to know all of that is not a
protocol, it is a switch statement.

`SetupContext` is the common denominator: everything a detector might need, present
and named, with no detector having to be rewritten. `SetupDetector` is the uniform
`detect(context) -> list[SetupFinding]` shape. `adapt()` bridges the two, so a
detector can keep its own signature and still be registered.

## What a finding is

`SetupFinding` is deliberately thin: a name, a direction, and the payload dict of
whatever the detector returned. It is **not** a normalised score and it does not
rank anything — comparing setups is Phase 15's job, and a ranking produced here
would be a claim this engine has not earned. `SetupFinding` exists so a caller can
ask "what fired, in which direction" without knowing which detector fired it.

## Presence is decided here, not by the payload

`SetupFinding.found` comes from the adapter's `presence` function, not from reading a
`found` attribute. `FadingSetup` has no `found` field at all (it has `is_active`,
and a terminal setup is still a finding) and `DoublePattern` uses `found` for
something narrower, so neither model's existing public API was changed to fit the
registry. The default rule — `payload.get("found", True)` — already reads a
payload that never mentions `found` as present, which is why `FadingSetup` needs
no override; the hook exists for the narrower `found` case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from albrooks.core.bars import Bar, BarSeries
from albrooks.engine.configuration import AnalyzerConfig


@dataclass(frozen=True, slots=True)
class SetupContext:
    """Everything a setup detector may need, in one place.

    Passing a single context rather than a long parameter list is what lets a
    detector declare only what it uses, and lets the pipeline add an input later
    without changing every signature.
    """

    bars: Sequence[Bar | dict[str, Any]] | BarSeries
    last_closed: int
    atr: float = 0.0
    config: AnalyzerConfig = field(default_factory=AnalyzerConfig)
    swings: Sequence[Any] = ()
    legs: Sequence[Any] = ()
    #: Index the detectors should evaluate. Usually equal to `last_closed`, but
    #: separate because some detectors reason about a bar other than the newest.
    idx: int = -1

    def __post_init__(self) -> None:
        if self.idx < 0:
            object.__setattr__(self, "idx", self.last_closed)

    @property
    def last_bar(self) -> Bar | dict[str, Any] | None:
        """The newest analysed bar, or None if the window is empty."""
        if not 0 <= self.last_closed < len(self.bars):
            return None
        return self.bars[self.last_closed]

    @property
    def has_volatility(self) -> bool:
        return self.atr > 0

    @property
    def is_usable(self) -> bool:
        """Enough data for an ATR-relative detector to say anything at all.

        Checked by the registry before running anything, because every detector
        here gates on ATR multiples and would otherwise report a confident "nothing
        found" on a series with no volatility — a claim about a market that was
        never measured.
        """
        return self.has_volatility and self.last_closed >= 0


@dataclass(frozen=True, slots=True)
class SetupFinding:
    """One thing a detector reported, normalised just enough to be uniform."""

    #: Registered detector name.
    detector: str
    #: Stable subtype within the detector, e.g. the measured-move family.
    kind: str = "DEFAULT"
    direction: int = 0
    found: bool = True
    #: The detector's own payload, unmodified.
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_long(self) -> bool:
        return self.direction > 0

    @property
    def is_short(self) -> bool:
        return self.direction < 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "kind": self.kind,
            "direction": self.direction,
            "found": self.found,
            "payload": self.payload,
        }


# --------------------------------------------------------------------------
# Adapting an existing detector
# --------------------------------------------------------------------------

#: Pulls a plain dict out of a detector's return value, whatever shape it is.
Payload = Callable[[Any], dict[str, Any]]


def _as_payload(value: Any) -> dict[str, Any]:
    """A detector's return value as a plain dict.

    The five detector models all carry `to_dict()`, so that is preferred; anything
    else that is already a mapping is used as-is, and a bare value falls back to
    `{"value": ...}` rather than raising. A detector returning something
    unexpected should not take down the whole registry run.
    """
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return result
    if isinstance(value, dict):
        return value
    return {"value": value}


def _default_direction(value: Any, payload: dict[str, Any]) -> int:
    """The detector's direction, from the payload or the object itself.

    `direction` is read from the payload first because a few models keep it only
    in their typed form, then from the attribute, and finally from the bare int a
    detector may return directly.
    """
    raw = payload.get("direction", getattr(value, "direction", value))
    try:
        direction = int(raw)
    except (TypeError, ValueError):
        return 0
    # Any non-zero magnitude means the same thing here; normalise the sign so a
    # detector reporting 1/-1 and one reporting 100/-100 agree.
    return (direction > 0) - (direction < 0)


def adapt(
    name: str,
    call: Callable[..., Any],
    *,
    kind: str = "DEFAULT",
    direction: Callable[[Any, dict[str, Any]], int] | None = None,
    present: Callable[[Any, dict[str, Any]], bool] | None = None,
    expand: Callable[[Any], list[Any]] | None = None,
    **kwargs: Any,
) -> SetupDetector:
    """Wrap a detector of any existing shape as a `SetupDetector`.

    `call` is invoked with `context` plus whatever extra keyword arguments it
    needs. It may return a single object, a list, or a list per direction, and this
    function normalises all three.

    The three hooks exist because "is this a finding, and in which direction?"
    cannot be inferred uniformly:

    * `expand` turns a list return into its elements; by default a list return is
      already the set of findings.
    * `present` decides whether a result counts. The default is
      `payload.get("found", True)`: a payload that says `found=False` is not a
      finding, and a payload that never mentions `found` — `FadingSetup` has no
      such field — is one. Overriding is only needed for a model that uses
      `found` to mean something narrower than "this fired".
    * `direction` reads the direction, defaulting to the `direction` field the five
      models already share.

    Extra `kwargs` are passed through untouched, which is how a detector's
    `reversal_direction` or `level` argument is supplied.
    """
    get_direction = direction or _default_direction

    def is_present(value: Any, payload: dict[str, Any]) -> bool:
        if present is not None:
            return bool(present(value, payload))
        return bool(payload.get("found", True))

    class _Adapted:
        """A `SetupDetector` view over a function of any other signature."""

        __slots__ = ("_call", "_expand", "_is_present", "_kwargs", "_kind", "name")

        def __init__(self) -> None:
            self.name = name
            self._kind = kind
            self._call = call
            self._kwargs = kwargs
            self._expand = expand
            self._is_present = is_present

        def detect(self, context: SetupContext) -> list[SetupFinding]:
            results = self._call(context, **self._kwargs)
            items = self._expand(results) if self._expand else results
            if not isinstance(items, list):
                items = [items]
            findings: list[SetupFinding] = []
            for item in items:
                if item is None:
                    continue
                payload = _as_payload(item)
                if not self._is_present(item, payload):
                    continue
                findings.append(
                    SetupFinding(
                        detector=self.name,
                        kind=self._kind,
                        direction=get_direction(item, payload),
                        found=True,
                        payload=payload,
                    )
                )
            return findings

        def __repr__(self) -> str:
            target = getattr(self._call, "__name__", repr(self._call))
            return f"<adapted detector {self.name} -> {target}>"

    return _Adapted()



#: Registry detector name -> the setup **family** it belongs to.
#:
#: The registry's own `kind` is a detector-level label, and two of the shipped
#: detectors are registered with the default `kind`, so `kind` alone cannot answer
#: "which family is this?". One table answers it for every consumer — the trade
#: layer's anatomy lookup, the pipeline's per-family grouping, and the decision
#: layer's evidence adapters — because a second copy of this mapping is a second
#: place for the eleven detector names to drift out of step.
FAMILY_BY_DETECTOR: dict[str, str] = {
    "PULLBACK_H": "PULLBACK",
    "PULLBACK_L": "PULLBACK",
    "BREAKOUT": "BREAKOUT",
    "REVERSAL_BULL": "REVERSAL",
    "REVERSAL_BEAR": "REVERSAL",
    "DOUBLE_TOP_MAJOR": "DOUBLE_TOP",
    "DOUBLE_BOTTOM_MAJOR": "DOUBLE_BOTTOM",
    "DOUBLE_TOP_MICRO": "DOUBLE_TOP",
    "DOUBLE_BOTTOM_MICRO": "DOUBLE_BOTTOM",
    "MEASURED_MOVE": "MEASURED_MOVE",
    "FADING_MEASURED_MOVE": "FADING_MEASURED_MOVE",
}


def family_for(detector: str, kind: str = "") -> str:
    """The family a finding belongs to.

    Falls back to the finding's own `kind`, which is the right answer for a
    third-party detector that named its family there — and `UNKNOWN` rather than a
    guess when it named neither, so a caller can see the gap instead of receiving
    a family invented from a detector name.
    """
    return FAMILY_BY_DETECTOR.get(detector) or kind or "UNKNOWN"


@runtime_checkable
class SetupDetector(Protocol):
    """What the registry requires of a detector.

    Deliberately one method. Anything a registry needs to *decide* — enablement,
    ordering, priority — belongs in the registration record, not in extra protocol
    methods that every implementation would then have to supply and most would
    answer with a constant.
    """

    name: str

    def detect(self, context: SetupContext) -> list[SetupFinding]:
        """Run against closed bars and return what fired, possibly nothing."""
        ...
