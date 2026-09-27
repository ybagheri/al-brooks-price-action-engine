"""Tests for the setup detector protocol and registry (Phase 12).

Every detector up to Phase 11 was written against the shape its own phase needed,
and `ARCHITECTURE.md` §9 makes a claim about all of them at once:

> New setups must be addable without modifying the central analyzer. If adding a
> detector requires editing `engine/analyzer.py`, the architecture has been
> violated.

A registry that only worked for one detector would not make that claim true. These
tests therefore pin the properties the claim depends on, rather than the behaviour
of any one detector:

1. **A detector of any existing shape can be registered.** Five detectors have five
   different signatures, one takes no bars at all, and two return lists while four
   return a single object. All of them run through the same `detect(context)`.
2. **"Nothing found" and "never ran" stay different statements.** Every detector
   here gates on ATR multiples, so a context with no volatility would otherwise
   return a confident, entirely fabricated "nothing found" for all eleven.
3. **A broken detector is contained.** One raising detector must not take down the
   ten beside it, and a caller must be able to find out that it happened.
4. **Order is deterministic, and is not a ranking.** Findings come back in
   registration order, because this phase refuses to compare setups — that is
   Phase 15's job, and a registry that returned a "best setup" would be making a
   trade decision while claiming to be a lookup table.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from albrooks.core.bars import BarSeries
from albrooks.core.legs import build_legs_from_swings
from albrooks.core.swings import find_swings
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.bars import calculate_atr_series
from albrooks.setups.base import (
    SetupContext,
    SetupDetector,
    SetupFinding,
    adapt,
)
from albrooks.setups.registry import (
    DEFAULT_REGISTRY,
    DuplicateDetectorError,
    RegistryError,
    SetupRegistry,
    UnknownDetectorError,
    build_default_registry,
)

#: Every detector `build_default_registry()` is expected to ship. Pinned as a
#: literal rather than derived from the registry, so a detector that is silently
#: dropped from the default set fails here instead of just reducing a count.
EXPECTED_DETECTORS = [
    "PULLBACK_H",
    "PULLBACK_L",
    "BREAKOUT",
    "REVERSAL_BULL",
    "REVERSAL_BEAR",
    "DOUBLE_TOP_MAJOR",
    "DOUBLE_BOTTOM_MAJOR",
    "DOUBLE_TOP_MICRO",
    "DOUBLE_BOTTOM_MICRO",
    "MEASURED_MOVE",
    "FADING_MEASURED_MOVE",
]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def zigzag(n: int = 60) -> list[dict[str, float]]:
    """A deterministic alternating series, so any failure reproduces exactly."""
    out: list[dict[str, float]] = []
    price = 100.0
    for i in range(n):
        o = price
        c = price + (1.5 if i % 2 == 0 else -1.5)
        out.append({"o": o, "h": max(o, c) + 0.8, "l": min(o, c) - 0.8, "c": c})
        price = c
    return out


def rally(n: int = 60) -> list[dict[str, float]]:
    """A rally, a pullback, then a rally again.

    The `zigzag` fixture is too regular: it produces only micro-double findings,
    so a closed-bar test built on it would compare two short lists and pass
    whether or not a detector peeked at the future. This one actually forms a
    measurable leg and pullback, so the measured-move and fading-measured-move
    detectors both fire and a leak changes the answer.
    """
    out: list[dict[str, float]] = []
    price = 100.0
    for i in range(n):
        if i < n * 0.33:
            o, h, low, c = price, price + 1.0, price - 1.0, price + 0.8
        elif i < n * 0.5:
            o, h, low, c = price, price + 1.0, price - 1.0, price - 0.4
        else:
            o, h, low, c = price, price + 1.2, price - 0.6, price + 1.0
        price = c
        out.append({"o": o, "h": h, "l": low, "c": c})
    return out


def make_context(
    bars: list[dict[str, float]] | None = None, *, atr: float | None = None
) -> SetupContext:
    """A context built the way the pipeline would build one, for real detectors."""
    rows = bars if bars is not None else zigzag()
    series = BarSeries(rows)
    config = AnalyzerConfig(range_lookback=20)
    closed = len(series) - 1
    if atr is None:
        atrs = calculate_atr_series(series, period=config.atr_period)
        atr = atrs[closed] if closed < len(atrs) else 0.0
    swings = find_swings(series, last_closed_idx=closed, k=config.swing_k)
    return SetupContext(
        bars=series,
        last_closed=closed,
        atr=atr,
        config=config,
        swings=swings,
        legs=build_legs_from_swings(swings),
    )


class StubDetector:
    """A minimal `SetupDetector`, to test the registry without real analysis."""

    def __init__(self, name: str, findings: list[SetupFinding] | None = None) -> None:
        self.name = name
        self._findings = findings or []
        self.calls = 0

    def detect(self, context: SetupContext) -> list[SetupFinding]:
        self.calls += 1
        return list(self._findings)


# --------------------------------------------------------------------------
# SetupContext
# --------------------------------------------------------------------------


def test_idx_defaults_to_the_newest_closed_bar() -> None:
    """A detector must not have to remember which bar it is evaluating.

    `idx` is separate from `last_closed` because some detectors reason about a bar
    other than the newest, but the default has to be the common case or every one
    of them would have to pass it.
    """
    assert make_context().idx == make_context().last_closed


def test_an_explicit_idx_is_respected() -> None:
    """The escape hatch for a detector that evaluates an older bar."""
    assert SetupContext(bars=zigzag(30), last_closed=29, idx=20).idx == 20


def test_last_bar_is_the_analysed_bar_not_the_newest_supplied() -> None:
    """The newest *analysed* bar — not the end of the array.

    These differ whenever `last_closed` is behind the data, which is the normal
    case for a historical query.
    """
    series = BarSeries(zigzag(40))
    ctx = SetupContext(bars=series, last_closed=20, atr=1.0)
    assert ctx.last_bar is series[20]
    assert ctx.last_bar is not series[39]


def test_last_bar_is_none_for_an_empty_window() -> None:
    """Reading a bar that does not exist returns None rather than raising."""
    assert SetupContext(bars=[], last_closed=-1).last_bar is None


def test_a_context_with_no_volatility_is_not_usable() -> None:
    """The gate that stops a fabricated "nothing found".

    Every detector here gates on ATR multiples, so a zero ATR would reject
    everything and read as a market with no structure.
    """
    ctx = SetupContext(bars=zigzag(), last_closed=10, atr=0.0)
    assert not ctx.has_volatility
    assert not ctx.is_usable


def test_a_context_with_no_closed_bars_is_not_usable() -> None:
    assert not SetupContext(bars=zigzag(), last_closed=-1, atr=1.0).is_usable


def test_a_populated_context_is_usable() -> None:
    assert make_context().is_usable


# --------------------------------------------------------------------------
# SetupFinding
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "is_long", "is_short"),
    [(1, True, False), (-1, False, True), (0, False, False)],
)
def test_direction_predicates_agree_with_the_sign(
    direction: int, is_long: bool, is_short: bool
) -> None:
    item = SetupFinding(detector="X", direction=direction)
    assert item.is_long is is_long
    assert item.is_short is is_short


def test_a_finding_serialises_to_json() -> None:
    """Downstream consumers get dicts, never Python object graphs."""
    item = SetupFinding(detector="X", kind="DOUBLE_TOP", direction=-1, payload={"a": 1})
    assert json.loads(json.dumps(item.to_dict())) == {
        "detector": "X",
        "kind": "DOUBLE_TOP",
        "direction": -1,
        "found": True,
        "payload": {"a": 1},
    }


# --------------------------------------------------------------------------
# adapt(): one shape in, a uniform one out
# --------------------------------------------------------------------------


def test_an_adapted_single_object_return_becomes_one_finding() -> None:
    out = adapt("X", lambda ctx: {"found": True, "direction": 1}).detect(make_context())
    assert len(out) == 1
    assert out[0].detector == "X"
    assert out[0].is_long


def test_an_adapted_list_return_becomes_many_findings() -> None:
    """Two of the eleven detectors return lists; both must work."""
    detector = adapt(
        "X",
        lambda ctx: [{"found": True, "direction": 1}, {"found": True, "direction": -1}],
    )
    assert [f.direction for f in detector.detect(make_context())] == [1, -1]


def test_a_none_return_is_no_finding() -> None:
    assert adapt("X", lambda ctx: None).detect(make_context()) == []


def test_a_bare_object_return_is_still_handled() -> None:
    """A detector returning a non-list scalar must not crash the run."""
    out = adapt("X", lambda ctx: 1).detect(make_context())
    assert len(out) == 1
    assert out[0].direction == 1


def test_found_false_is_not_a_finding() -> None:
    """The default presence rule, and the most common case by far."""
    assert adapt("X", lambda ctx: {"found": False}).detect(make_context()) == []


def test_a_payload_with_no_found_key_is_still_present() -> None:
    """Absence of the flag is not a claim of absence.

    `FadingSetup` has no `found` field at all, and a terminal setup is still a
    reportable fact, so "present unless it says otherwise" is the right default.
    """
    assert len(adapt("X", lambda ctx: {"direction": 1}).detect(make_context())) == 1


def test_a_custom_presence_rule_overrides_the_default() -> None:
    detector = adapt("X", lambda ctx: {"found": True}, present=lambda v, p: False)
    assert detector.detect(make_context()) == []


def test_direction_magnitude_is_normalised_to_sign() -> None:
    """A detector reporting 100/-100 agrees with one reporting 1/-1."""
    out = adapt("X", lambda ctx: {"found": True, "direction": -100}).detect(
        make_context()
    )
    assert out[0].direction == -1
    assert out[0].is_short


def test_an_unreadable_direction_is_reported_as_zero() -> None:
    """Direction 0 is "the detector did not say", and must not raise."""
    out = adapt("X", lambda ctx: {"found": True, "direction": "up"}).detect(
        make_context()
    )
    assert out[0].direction == 0


def test_direction_falls_back_to_the_object_attribute() -> None:
    class OnlyAttr:
        direction = -1

        def to_dict(self) -> dict[str, Any]:
            return {"state": "CONFIRMED"}

    assert adapt("X", lambda ctx: OnlyAttr()).detect(make_context())[0].direction == -1


def test_a_models_own_to_dict_is_the_payload() -> None:
    """The payload is the detector's own serialisation, not a reconstruction."""

    class Model:
        def to_dict(self) -> dict[str, Any]:
            return {"state": "CONFIRMED", "score": 3}

    out = adapt("X", lambda ctx: Model()).detect(make_context())
    assert out[0].payload == {"state": "CONFIRMED", "score": 3}


def test_a_non_dict_return_falls_back_rather_than_raising() -> None:
    """An unexpected return value degrades; it does not take down the run."""
    out = adapt("X", lambda ctx: "surprise").detect(make_context())
    assert out[0].payload == {"value": "surprise"}


def test_extra_kwargs_are_passed_through() -> None:
    """How a detector's own extra argument, e.g. `reversal_direction`, is supplied."""
    seen: list[int] = []

    def detector_fn(ctx: SetupContext, level: int = 0) -> dict[str, Any]:
        seen.append(level)
        return {"found": True, "direction": level}

    adapt("X", detector_fn, level=1).detect(make_context())
    assert seen == [1]


def test_an_expand_hook_transforms_a_nested_return() -> None:
    detector = adapt("X", lambda ctx: [[1, -1]], expand=lambda r: r[0])
    assert [f.direction for f in detector.detect(make_context())] == [1, -1]


def test_kind_is_carried_onto_the_finding() -> None:
    out = adapt("X", lambda ctx: {"found": True}, kind="DOUBLE_TOP").detect(make_context())
    assert out[0].kind == "DOUBLE_TOP"


def test_an_adapted_detector_reports_its_name() -> None:
    def some_detector(ctx: SetupContext) -> dict[str, Any]:
        return {"found": True}

    assert "some_detector" in repr(adapt("X", some_detector))


def test_an_adapted_detector_satisfies_the_protocol() -> None:
    """`isinstance` against a `runtime_checkable` protocol, as a caller would."""
    assert isinstance(adapt("X", lambda ctx: {"found": True}), SetupDetector)


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_register_returns_the_detector_so_it_can_be_chained() -> None:
    registry = SetupRegistry()
    stub = StubDetector("A")
    assert registry.register(stub) is stub
    assert "A" in registry


def test_a_duplicate_name_is_an_error() -> None:
    """Silently replacing would make the run order depend on import order."""
    with pytest.raises(DuplicateDetectorError):
        SetupRegistry([StubDetector("A")]).register(StubDetector("A"))


def test_replace_is_the_explicit_way_to_override() -> None:
    registry = SetupRegistry([StubDetector("A")])
    replacement = StubDetector("A")
    registry.register(replacement, replace=True)
    assert registry.get("A") is replacement
    assert len(registry) == 1


def test_an_unnamed_detector_is_rejected() -> None:
    class Nameless:
        def detect(self, context: SetupContext) -> list[SetupFinding]:
            return []

    with pytest.raises(RegistryError):
        SetupRegistry().register(Nameless())


def test_a_name_can_be_supplied_at_registration() -> None:
    """Lets an off-the-shelf callable be registered without wrapping it."""
    registry = SetupRegistry()
    registry.register(StubDetector("A"), name="OVERRIDDEN")
    assert registry.names == ["OVERRIDDEN"]


def test_unregistering_an_unknown_name_is_an_error() -> None:
    with pytest.raises(UnknownDetectorError):
        SetupRegistry().unregister("NOPE")


def test_getting_an_unknown_name_lists_what_is_available() -> None:
    """The error should say what you could have asked for."""
    with pytest.raises(UnknownDetectorError) as excinfo:
        SetupRegistry([StubDetector("A")]).get("NOPE")
    assert "A" in str(excinfo.value)


def test_registering_a_batch_returns_them_in_order() -> None:
    registry = SetupRegistry()
    out = registry.register_all([StubDetector("A"), StubDetector("B")])
    assert [d.name for d in out] == ["A", "B"]


def test_names_are_registration_order() -> None:
    """Deterministic, and explicitly not a ranking."""
    registry = SetupRegistry([StubDetector(n) for n in ("C", "A", "B")])
    assert registry.names == ["C", "A", "B"]


def test_the_registry_is_iterable_and_sized() -> None:
    registry = SetupRegistry([StubDetector("A"), StubDetector("B")])
    assert len(registry) == 2
    assert [d.name for d in registry] == ["A", "B"]


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def test_select_without_arguments_returns_everything_in_order() -> None:
    registry = SetupRegistry([StubDetector(n) for n in ("A", "B", "C")])
    assert [d.name for d in registry.select()] == ["A", "B", "C"]


def test_select_keeps_registration_order_not_the_callers_order() -> None:
    """The same set always runs the same way, however it was written."""
    registry = SetupRegistry([StubDetector(n) for n in ("A", "B", "C")])
    assert [d.name for d in registry.select(["C", "A"])] == ["A", "C"]
    assert [d.name for d in registry.select(["A", "C"])] == ["A", "C"]


def test_selecting_an_unknown_name_is_an_error() -> None:
    with pytest.raises(UnknownDetectorError) as excinfo:
        SetupRegistry([StubDetector("A")]).select(["NOPE"])
    assert "A" in str(excinfo.value)


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def test_findings_come_back_in_registration_order() -> None:
    registry = SetupRegistry(
        [
            adapt("A", lambda ctx: [{"found": True, "direction": 1}]),
            adapt("B", lambda ctx: {"found": True, "direction": -1}),
        ]
    )
    assert [f.detector for f in registry.run(make_context()).findings] == ["A", "B"]


def test_executed_records_every_detector_that_ran() -> None:
    """Including the ones that found nothing — that is what ran."""
    registry = SetupRegistry(
        [
            adapt("HIT", lambda ctx: {"found": True}),
            adapt("MISS", lambda ctx: {"found": False}),
        ]
    )
    run = registry.run(make_context())
    assert run.executed == ["HIT", "MISS"]
    assert len(run.findings) == 1


def test_only_restricts_the_run_without_unregistering() -> None:
    registry = SetupRegistry([StubDetector("A"), StubDetector("B")])
    run = registry.run(make_context(), only=["B"])
    assert run.executed == ["B"]
    assert registry.names == ["A", "B"]


def test_an_unusable_context_is_skipped_not_run() -> None:
    """The core honesty property.

    Every detector gates on ATR multiples, so running them at `atr=0` would
    return a clean, empty, entirely plausible "no structure here" for a market
    that was never measured.
    """
    registry = SetupRegistry([adapt("A", lambda ctx: {"found": True})])
    run = registry.run(SetupContext(bars=zigzag(), last_closed=10, atr=0.0))
    assert run.findings == []
    assert run.executed == []
    assert run.skipped == {"A": "NO_ATR"}


def test_a_context_with_no_closed_bars_names_that_reason() -> None:
    """A skipped detector must say *why*, not merely be absent."""
    run = SetupRegistry([StubDetector("A")]).run(
        SetupContext(bars=zigzag(), last_closed=-1, atr=1.0)
    )
    assert run.skipped == {"A": "NO_CLOSED_BARS"}


def test_skipping_can_be_turned_off() -> None:
    """A caller who wants the raw answer can have it, on purpose."""
    registry = SetupRegistry([adapt("A", lambda ctx: {"found": True})])
    run = registry.run(
        SetupContext(bars=zigzag(), last_closed=10, atr=0.0),
        skip_if_unusable=False,
    )
    assert run.executed == ["A"]


def test_a_raising_detector_is_contained_and_recorded() -> None:
    """One broken detector must not take down the ten beside it."""

    def boom(ctx: SetupContext) -> Any:
        raise RuntimeError("detector is broken")

    registry = SetupRegistry(
        [
            adapt("GOOD_A", lambda ctx: {"found": True}),
            adapt("BROKEN", boom),
            adapt("GOOD_B", lambda ctx: {"found": True}),
        ]
    )
    run = registry.run(make_context())
    assert [f.detector for f in run.findings] == ["GOOD_A", "GOOD_B"]
    assert run.executed == ["GOOD_A", "BROKEN", "GOOD_B"]
    assert not run.ok
    assert [f.detector for f in run.failures] == ["BROKEN"]
    assert isinstance(run.failures[0].error, RuntimeError)


def test_strict_reraises_for_callers_who_would_rather_fail_loudly() -> None:
    def boom(ctx: SetupContext) -> Any:
        raise RuntimeError("detector is broken")

    with pytest.raises(RuntimeError):
        SetupRegistry([adapt("BROKEN", boom)]).run(make_context(), strict=True)


def test_by_detector_groups_the_findings() -> None:
    registry = SetupRegistry(
        [
            adapt("A", lambda ctx: [{"found": True}, {"found": True}]),
            adapt("B", lambda ctx: {"found": True}),
        ]
    )
    grouped = registry.run(make_context()).by_detector()
    assert {k: len(v) for k, v in grouped.items()} == {"A": 2, "B": 1}


def test_a_run_serialises_to_json() -> None:
    """The point of a dict-shaped protocol is that results can leave the process."""
    registry = SetupRegistry([adapt("A", lambda ctx: {"found": True, "direction": 1})])
    payload = json.loads(json.dumps(registry.run(make_context()).to_dict()))
    assert payload["findings"][0]["detector"] == "A"
    assert payload["executed"] == ["A"]
    assert payload["failures"] == []


def test_an_empty_registry_runs_and_reports_nothing() -> None:
    run = SetupRegistry().run(make_context())
    assert run.findings == [] and run.ok and run.executed == []


# --------------------------------------------------------------------------
# The shipped registry
# --------------------------------------------------------------------------


def test_the_default_registry_ships_every_detector() -> None:
    """Pinned as a literal, so a dropped detector fails rather than shrinking a count."""
    assert build_default_registry().names == EXPECTED_DETECTORS


def test_every_shipped_detector_satisfies_the_protocol() -> None:
    for detector in build_default_registry():
        assert isinstance(detector, SetupDetector)


def test_a_fresh_default_registry_shares_nothing_with_the_global() -> None:
    """`build_default_registry()` is preferred over the process-wide global.

    A shared mutable global would make one test's registration the next test's
    starting state, so the two must be independent.
    """
    fresh = build_default_registry()
    assert fresh is not DEFAULT_REGISTRY
    assert len(DEFAULT_REGISTRY) == 0
    fresh.register(StubDetector("ONLY_IN_FRESH"))
    assert "ONLY_IN_FRESH" not in DEFAULT_REGISTRY
    assert len(build_default_registry()) == len(EXPECTED_DETECTORS)


def test_all_eleven_detectors_run_against_a_real_series() -> None:
    """The claim of §9: eleven detectors, five signatures, one context, no edits.

    This is the integration test. If a detector's signature drifts, or the adapter
    around it passes the wrong index, this is what notices.
    """
    run = build_default_registry().run(make_context())
    assert run.executed == EXPECTED_DETECTORS
    assert run.failures == []
    assert run.ok


def test_the_real_run_reports_direction_only_when_one_exists() -> None:
    """A finding is either directional or it is not; the field must mean that."""
    for item in build_default_registry().run(make_context()).findings:
        assert item.direction in (-1, 0, 1)
        assert item.payload, "a finding with an empty payload explains nothing"


def test_every_real_finding_serialises() -> None:
    """No finding may carry a live Python object into a downstream consumer."""
    json.dumps(build_default_registry().run(make_context()).to_dict())


def test_a_run_is_reproducible() -> None:
    """The same context twice gives the same findings."""
    registry = build_default_registry()
    first = registry.run(make_context()).to_dict()
    assert first == registry.run(make_context()).to_dict()


def test_a_detector_can_be_replaced_without_editing_the_analyzer() -> None:
    """§9 stated as an executable assertion, not a comment.

    Adding a detector is a `register()` call on a registry that already knows how
    to run detectors. If this ever needs a change in `engine/analyzer.py`, the
    architecture is violated and this test is where it should fail.
    """
    registry = build_default_registry()
    registry.register(adapt("THIRD_PARTY", lambda ctx: {"found": True, "direction": 1}))
    assert "THIRD_PARTY" in registry
    run = registry.run(make_context(), only=["THIRD_PARTY"])
    assert [f.detector for f in run.findings] == ["THIRD_PARTY"]


def test_a_fading_finding_reports_the_fade_direction_not_the_projection() -> None:
    """A bull projection is faded short; conflating them fades a trend by mistake.

    `FadingSetup.direction` is the projection's and `fade_direction` its opposite.
    The registry reports the trade-facing one, which is the whole reason the fade
    adapter supplies its own `direction`.
    """
    from albrooks.setups.fading_measured_move import FadingSetup

    def only_fades(ctx: SetupContext) -> list[Any]:
        return [
            FadingSetup(
                id=1,
                family="RANGE",
                direction=1,  # projected up
                target_price=105.0,
                mm_range=10.0,
                created_bar=ctx.last_closed,
                fade_direction=-1,  # faded down
            )
        ]

    detector = adapt(
        "FADING_MEASURED_MOVE",
        only_fades,
        present=lambda v, p: True,
        direction=lambda v, p: int(getattr(v, "fade_direction", 0) or 0),
    )
    assert detector.detect(make_context())[0].is_short, (
        "a bull projection must be reported as a short fade"
    )


def test_a_terminal_fade_is_still_a_finding() -> None:
    """A completed or invalidated fade is a fact about how price behaved.

    `FadingSetup` has no `found` field at all, so the default rule — present
    unless the payload says `found=False` — already treats it correctly. A
    terminal fade must not be silently dropped.
    """
    from albrooks.setups.fading_measured_move import FadingSetup

    def terminal_fade(ctx: SetupContext) -> list[Any]:
        return [
            FadingSetup(
                id=1,
                family="RANGE",
                direction=-1,
                target_price=90.0,
                mm_range=10.0,
                created_bar=0,
                state="INVALIDATED",
            )
        ]

    findings = adapt("FADE", terminal_fade).detect(make_context())
    assert len(findings) == 1
    assert findings[0].payload["state"] == "INVALIDATED"


def test_the_default_presence_rule_needs_no_override_for_a_foundless_model() -> None:
    """A model with no `found` field is present, not absent.

    The rule is `payload.get("found", True)`, so a payload that never mentions
    `found` is a finding. This is the case that made the fade adapter's own
    `present=` hook look necessary; it is not, and the assertion is here so that
    if the default is ever tightened to `payload["found"]`, this fails and the
    question is asked again deliberately rather than silently.
    """
    from albrooks.setups.fading_measured_move import FadingSetup

    payload = FadingSetup(
        id=1, family="RANGE", direction=1, target_price=105.0, mm_range=10.0, created_bar=0
    ).to_dict()
    assert "found" not in payload
    assert bool(payload.get("found", True)) is True


# --------------------------------------------------------------------------
# The closed-bar contract, through the registry
# --------------------------------------------------------------------------


def test_the_registry_honours_the_closed_bar_contract() -> None:
    """Findings for an index must not change when later bars exist.

    The invariant is stated once in `ARCHITECTURE.md` §6 and asserted at the
    pipeline level. The registry passes `last_closed` into eleven detectors, so
    the invariant has to hold here too — a detector handed the full series would
    pass its own unit tests and break this one.

    The cut is at 59 of 80 bars, not at the end: the measured-move detectors only
    form a projection once a full leg and pullback exist, and a cut too early
    leaves them silent, which would make the comparison below vacuous.
    """
    registry = build_default_registry()
    bars = rally(80)

    short = SetupContext(bars=BarSeries(bars[:60]), last_closed=59, atr=2.0)
    with_future = SetupContext(bars=BarSeries(bars), last_closed=59, atr=2.0)

    before = registry.run(short).to_dict()["findings"]
    after = registry.run(with_future).to_dict()["findings"]
    assert before == after


def test_the_closed_bar_test_is_not_vacuous() -> None:
    """The closed-bar test above is only meaningful if it has findings to compare.

    An earlier version compared two near-empty finding lists built from a
    perfectly regular zigzag, and passed even with lookahead deliberately
    injected into the measured-move adapter. The fixture now has to produce
    measured-move and fading findings for the comparison to have any content —
    this test is what stops that from silently regressing.
    """
    bars = rally(80)
    findings = build_default_registry().run(
        SetupContext(bars=BarSeries(bars[:60]), last_closed=59, atr=2.0)
    ).findings
    detectors = {f.detector for f in findings}
    assert "MEASURED_MOVE" in detectors
    assert "FADING_MEASURED_MOVE" in detectors
