"""Tests for the non-repaint contract (Phase 17).

The engine has claimed to be closed-bars only since Phase 1. Until now that claim
lived in `ARCHITECTURE.md` §6, four algorithm specifications, and a dozen tests
named after it. This phase makes it a **numbered contract** in
`docs/algorithms/NON_REPAINT_CONTRACT.md` and makes the document itself
accountable: the last test here parses that document, collects its `RPC-n`
identifiers, resolves every test it names against the suite's own source, and
fails if one is missing.

Four things are new in this file, and the rest of the contract is enforced
elsewhere and cited:

1. **RPC-7, per-detector closure.** Every one of the eleven registered detectors
   is checked individually, driven off `build_default_registry()` so a detector
   added later is covered by construction. RPC-1 is asserted at the *pipeline*
   level, which catches a mis-wired stage but says nothing about a detector that is
   individually wrong.
2. **RPC-15, the historical freeze.** A live series whose newest bar is still
   forming is truncated, and the frozen result is compared with the historical
   one — including while the forming bar *mutates*, which is the property that
   actually matters to a consumer recomputing on every tick.
3. **RPC-16, the truncation is load-bearing.** Analysing the forming bar as if it
   were closed must produce a *different* answer, or "freeze your series" would be
   advice with no cost attached.
4. **RPC-18, the contract is checked against the suite.**
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pytest

from albrooks.core.bars import BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.setups.base import SetupContext
from albrooks.setups.registry import build_default_registry

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACT = REPO_ROOT / "docs" / "algorithms" / "NON_REPAINT_CONTRACT.md"
TEST_DIR = Path(__file__).resolve().parent
CFG = AnalyzerConfig(range_lookback=20)

#: Fields describing the *input* rather than the analysis, excluded when comparing
#: two runs over different amounts of data.
INPUT_FIELDS = frozenset({"bars_processed"})


def _bars(n: int = 60) -> list[dict[str, float]]:
    """A deterministic rally / pullback / rally series, oldest first."""
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


def _context(bars: list[dict[str, float]], last_closed: int) -> SetupContext:
    """A registry context over the analysed window, with the swings it needs."""
    from albrooks.core.swings import find_swings

    series = BarSeries(bars)
    return SetupContext(
        bars=series,
        last_closed=last_closed,
        atr=2.0,
        config=CFG,
        swings=find_swings(series, last_closed_idx=last_closed, k=CFG.swing_k),
        legs=(),
        idx=last_closed,
    )


def _findings(bars: list[dict[str, float]], last_closed: int) -> dict[str, Any]:
    """Registry findings, keyed by detector so a failure names the culprit."""
    run = build_default_registry().run(_context(bars, last_closed))
    assert run.ok, [f.to_dict() for f in run.failures]
    return {f.detector: f.to_dict() for f in run.findings}


def _derived(result: Any) -> dict[str, Any]:
    payload = result.to_dict()
    return {k: v for k, v in payload.items() if k not in INPUT_FIELDS}


# --------------------------------------------------------------------------
# RPC-7 — every registered detector, individually
# --------------------------------------------------------------------------


@pytest.mark.parametrize("at_bar", [39, 49, 59])
def test_every_registered_detector_is_closed_bar_clean(at_bar: int) -> None:
    """RPC-7.

    Each detector's findings at `at_bar` must be identical whether the series
    continues past it or is truncated there. Driven off the registry, so a detector
    added later is covered the moment it is registered rather than by remembering
    to write a test for it.

    Keyed by detector name so a failure says *which* one leaked.
    """
    full = _bars(80)
    truncated = full[: at_bar + 1]

    assert _findings(full, at_bar) == _findings(truncated, at_bar)


def test_the_detector_closure_fixture_is_not_vacuous() -> None:
    """A closure test over a fixture where nothing fires passes forever.

    This asserts the fixture produces a real spread of findings across several
    detectors, so the comparison in the test above cannot quietly become two empty
    dicts.
    """
    found = _findings(_bars(80), 59)

    assert len(found) >= 3, sorted(found)
    assert {"PULLBACK_H", "MEASURED_MOVE"} & set(found), sorted(found)
    # And at least one of them is a directional finding, so a leaked bar could
    # actually change something.
    assert any(finding["direction"] for finding in found.values())


def test_the_registry_covers_every_detector_the_contract_claims_to() -> None:
    """The contract says "the eleven setup detectors". If the registry's count
    moves, the contract's wording has moved with it and someone should look."""
    registry = build_default_registry()

    assert len(registry) == 11, registry.names
    run = registry.run(_context(_bars(80), 59))
    assert run.executed == registry.names


# --------------------------------------------------------------------------
# RPC-15 / RPC-16 — the historical freeze
# --------------------------------------------------------------------------


def forming_bar(next_open: float, so_far_high: float, so_far_low: float) -> dict[str, float]:
    """A bar as it looks mid-period.

    `close == so_far_high` is the usual convention for a forming bar's last price,
    and it is what makes passing one to the engine *plausible*: the bar is not
    obviously broken, it is simply not finished. The open has to sit inside the
    bar's own range or `Bar` would reject it, which is the engine's one structural
    defence and the reason a real adapter can hand over a partial bar at all.
    """
    return {
        "o": min(max(next_open, so_far_low), so_far_high),
        "h": so_far_high,
        "l": so_far_low,
        "c": so_far_high,
    }


def test_a_frozen_series_gives_the_historical_answer() -> None:
    """RPC-15.

    The historical series, plus a bar that has not closed. Freezing means dropping
    the forming bar, and the frozen analysis must equal the historical one at the
    same index. This is what makes a backtest and a live run comparable.
    """
    historical = _bars(60)
    live = historical + [forming_bar(next_open=140.0, so_far_high=141.0, so_far_low=138.0)]

    frozen = Analyzer(CFG).analyze(live, last_closed=59)
    reference = Analyzer(CFG).analyze(historical, last_closed=59)

    assert len(live) == 61, "the live series must carry the extra bar"
    assert _derived(frozen) == _derived(reference)
    assert frozen.last_closed_bar == 59


def test_a_forming_bar_mutating_does_not_move_the_closed_answer() -> None:
    """The half of RPC-15 that matters most.

    A repaint is not "the wrong answer once" — it is "the answer changed after you
    had already seen it". A consumer recomputing on every tick must get the same
    closed-bar answer at every tick, so this walks the forming bar through three
    successive states and asserts the answer at bar 59 never moves.
    """
    historical = _bars(60)
    analyzer = Analyzer(CFG)
    reference = _derived(analyzer.analyze(historical, last_closed=59))

    for high, low in ((140.0, 138.0), (141.0, 138.5), (140.5, 137.0)):
        live = historical + [forming_bar(next_open=140.0, so_far_high=high, so_far_low=low)]
        result = analyzer.analyze(live, last_closed=59)
        assert _derived(result) == reference, f"answer moved with the bar at {high}"


def test_passing_a_forming_bar_changes_the_answer() -> None:
    """RPC-16 — the converse, and the reason the contract has teeth.

    Analysing the series *including* the forming bar, at its newest index, must give
    a different answer from the frozen one. If it did not, `BarSeries` might simply
    be ignoring its last bar, and "freeze your series" would be advice with no cost
    attached.
    """
    historical = _bars(60)
    live = historical + [forming_bar(next_open=140.0, so_far_high=141.0, so_far_low=138.0)]

    frozen = Analyzer(CFG).analyze(live, last_closed=59)
    untruncated = Analyzer(CFG).analyze(live)

    assert untruncated.last_closed_bar == 60
    assert _derived(frozen) != _derived(untruncated)
    # The difference is the *newest bar's* analysis, not the frozen one: bar 59 is
    # untouched by bar 60 existing, which is RPC-1 and the reason the contract is
    # usable in the first place.
    assert _derived(Analyzer(CFG).analyze(live, last_closed=59)) == _derived(
        Analyzer(CFG).analyze(historical, last_closed=59)
    )


def test_a_forming_bar_is_not_detectable_from_the_data_alone() -> None:
    """The reason the engine has no forming-bar flag, stated as a test.

    `Bar` carries no `is_forming` field, so the engine genuinely cannot tell a
    forming bar from a closed one. That is the design — a flag would have to be
    threaded through every detector, and one that forgot it would be a look-ahead
    bug no test could see — and it is why the adapter's obligation to freeze is
    load-bearing.
    """
    live = _bars(60) + [forming_bar(next_open=140.0, so_far_high=141.0, so_far_low=138.0)]

    assert not hasattr(BarSeries(live)[60], "is_forming")
    assert "forming" not in BarSeries(live)[60].to_dict()


# --------------------------------------------------------------------------
# RPC-18 — the contract document is checked against the suite
# --------------------------------------------------------------------------

#: ```tests/unit/test_x.py::test_name``` — the form the document uses, so a bare
#: test name in prose is never mistaken for a reference.
_TEST_REF = re.compile(r"`(?:tests/unit/)?(test_[A-Za-z0-9_]+)\.py::(test_[A-Za-z0-9_]+)`")
_RPC_HEADING = re.compile(r"^### (RPC-\d+) ", re.MULTILINE)

#: The check cannot assert itself exists, so it is excluded from its own scan.
_SELF = "test_every_guarantee_names_a_test_that_exists"


def _contract_text() -> str:
    with io.open(CONTRACT, "r", encoding="utf-8") as handle:
        return handle.read()


def _guarantee_sections() -> dict[str, str]:
    """Each `RPC-n` heading's body, so a guarantee is checked on its own claims."""
    text = _contract_text()
    matches = list(_RPC_HEADING.finditer(text))
    sections: dict[str, str] = {}
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.start() : end]
    return sections


def _defined_test_names() -> dict[str, set[str]]:
    """Every `def test_*` in the suite, by module stem.

    Read from source rather than by importing: importing the suite from inside the
    suite is a thing that works until it does not, and this only needs names.
    """
    out: dict[str, set[str]] = {}
    pattern = re.compile(r"^def (test_[A-Za-z0-9_]*)\(", re.MULTILINE)
    for path in sorted(TEST_DIR.glob("test_*.py")):
        with io.open(path, "r", encoding="utf-8") as handle:
            out[path.stem] = set(pattern.findall(handle.read()))
    return out


def test_the_contract_document_exists_and_declares_its_guarantees() -> None:
    sections = _guarantee_sections()

    assert CONTRACT.is_file()
    # Compared as a set, because `sorted` on these strings is lexicographic and
    # would order RPC-10 before RPC-2.
    assert set(sections) == {f"RPC-{i}" for i in range(1, 19)}, sorted(sections)
    assert len(sections) == 18, sorted(sections)


def test_every_guarantee_names_a_test_that_exists() -> None:
    """RPC-18. The check that makes the contract worth writing.

    Every `RPC-n` must name at least one test, and every test it names must be
    defined in the module the reference says. A renamed or deleted test fails here
    rather than leaving the document quietly claiming something false.
    """
    defined = _defined_test_names()

    for name, body in sorted(_guarantee_sections().items()):
        references = [ref for ref in _TEST_REF.findall(body) if ref[1] != _SELF]
        assert references, f"{name} names no test"
        for module, test in references:
            assert test in defined.get(module, set()), f"{name} -> {module}::{test}"


def test_a_broken_reference_is_caught_rather_than_ignored() -> None:
    """The check above is worth its existence only if it can fail, so prove it does
    with a body that names a test which does not exist."""
    defined = _defined_test_names()
    bogus = ("test_phase17_non_repaint", "test_this_does_not_exist_anywhere")

    assert _TEST_REF.findall(f"`tests/unit/{bogus[0]}.py::{bogus[1]}`") == [bogus]
    assert bogus[1] not in defined.get(bogus[0], set())


def test_the_contract_covers_every_layer_that_reads_bars() -> None:
    """The contract names the pipeline, the registry, the measured-move layer, the
    fade lifecycle, plans, the decision layer and the multi-timeframe pipeline.

    A layer added later is not covered by construction — `RPC-7` covers *detectors*
    — so this is the reminder: either cite the contract or assert RPC-1 for the new
    layer yourself.
    """
    text = _contract_text()

    for layer in (
        "test_engine_pipeline",
        "test_phase12_setup_registry",
        "test_phase10_measured_move",
        "test_phase11_fading_measured_move",
        "test_phase14_trade_plan",
        "test_phase15_decision",
        "test_phase16_multi_timeframe",
    ):
        assert layer in text, layer


def test_the_contract_document_is_required_by_ci() -> None:
    """A contract that can go missing is not a contract. `check_docs_present.py`
    is the script CI runs, and its required list is asserted here rather than
    trusted."""
    import importlib.util

    path = REPO_ROOT / "scripts" / "check_docs_present.py"
    spec = importlib.util.spec_from_file_location("check_docs_present", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    required = [document for document, _ in module.REQUIRED_DOCS]
    assert "docs/algorithms/NON_REPAINT_CONTRACT.md" in required
    assert (
        "docs/algorithms/NON_REPAINT_CONTRACT.md",
        17,
    ) not in module.PENDING_DOCS


def test_the_contract_states_what_it_does_not_promise() -> None:
    """An honesty contract that only lists what is guaranteed is a warranty. This
    project does not warrant anything."""
    text = _contract_text()

    assert "What this contract does not promise" in text
    for caveat in ("does not promise the analysis is", "across brokers", "gap"):
        assert caveat in text, caveat
