"""The Python / MQL5 parity harness (Phase 20).

## What is actually being tested here

The engine is already covered: `test_phase17_non_repaint.py` carries the
non-repaint contract and `test_phase19_golden.py` carries the semantics. This
file tests the *harness*, and the harness has one job beyond comparing numbers —
which is **not reporting a verdict it has not earned**.

No MQL5 build of this engine exists. Every case names `null` for its sidecar and a
run reports `UNVERIFIED`. That is the state Phase 20 ships, and the assertions
below are mostly about keeping that state legible:

- `test_the_shipped_state_claims_no_parity` — a run over the committed cases
  compares nothing, says so, and does not set `claims_parity`.
- `test_a_python_produced_vector_is_not_parity_evidence` — the reference vectors
  in `tests/parity/reference/` exist to exercise the comparator, and the runner
  refuses to count one as a second implementation. Without this the harness
  could be satisfied by comparing Python against itself, which is the failure
  mode worth spending a whole test on.
- `test_a_reduced_scope_is_refused` — a port that implemented three fields is not
  a port that agreed.
- `test_the_report_status_invariant` — `AGREED` requires *every* case to have
  matched. A half-filled case set is `FAILED`, not a pass.
- `test_the_unverified_scaffold_stays_in_step_with_ci` — `--allow-unverified`
  exists in the runner and is used by CI, and it exists exactly while the shipped
  state is `UNVERIFIED`. Phase 21 removes the side, so the two cannot drift apart
  and leave CI green over an unverified claim.

The rest is the comparison policy: an index differing by one is a failure while a
price differing in the fifteenth digit is not, a field one side did not send is a
difference rather than a skip, list order is not contractual but list *count* is,
and the parity vector is closed-bar stable — which is `RPC-1` restated for the
thing the MQL5 side has to reproduce.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import pytest

from albrooks.core.bars import BarSeries
from tests.parity.compare import (
    MISMATCH,
    MISSING_IN_CANDIDATE,
    NOT_A_NUMBER,
    compare,
)
from tests.parity.contract import (
    ABSOLUTE_FLOOR,
    EXACT_INT,
    FIELD_CLASSES,
    NUMBER,
    PRODUCER_MQL5,
    PRODUCER_PYTHON,
    RELATIVE_TOLERANCE,
    SCHEMA_VERSION,
    SCOPE,
    CaseMismatch,
    SchemaMismatch,
    ScopeMismatch,
    VectorError,
    canonical_vector,
    deviation,
    dump,
    envelope,
    flatten,
    load_sidecar,
    within_tolerance,
)
from tests.parity.runner import (
    AGREED,
    CASES_DIR,
    EXIT_AGREED,
    EXIT_FAILED,
    EXIT_UNVERIFIED,
    FAILED,
    MQL5_ABSENT,
    NOT_AN_MQL5_SIDECAR,
    SCHEMA_MISMATCH,
    SCOPE_REDUCED,
    UNVERIFIED,
    VECTORS_DIR,
    ParityCase,
    ParityReport,
    load_case,
    load_cases,
    run,
    run_case,
)

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "PYTHON_MQL5_PARITY.md"
CI = REPO / ".github" / "workflows" / "ci.yml"

CASES = load_cases()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _vector(case: ParityCase) -> dict[str, Any]:
    return case.vector()


def _sidecar(
    case: ParityCase,
    *,
    vector: dict[str, Any] | None = None,
    producer: str = PRODUCER_MQL5,
    schema: str = SCHEMA_VERSION,
    scope: list[str] | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    payload = envelope(
        case_id or case.id,
        vector if vector is not None else _vector(case),
        producer,
        "test",
    )
    payload["schema"] = schema
    if scope is not None:
        payload["scope"] = scope
    return payload


def _write(directory: Path, case: ParityCase, payload: dict[str, Any]) -> ParityCase:
    """Put a sidecar in `directory` and point a copy of the case at it."""
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{case.id}.mql5.json"
    (directory / name).write_text(dump(payload), encoding="utf-8")
    return dataclasses.replace(case, mql5_vector=name)


def _wild_bars(count: int, after: int) -> list[dict[str, float]]:
    """Bars far outside anything the case contains, appended after it."""
    return [
        {"time": 1700000000.0 + (after + i) * 3600.0, "o": 500.0, "h": 520.0, "l": 10.0, "c": 12.0}
        for i in range(count)
    ]


# --------------------------------------------------------------------------
# The case set
# --------------------------------------------------------------------------


def test_the_case_set_is_not_empty() -> None:
    """A parity harness with no cases is a comparator and nothing else."""
    assert len(CASES) >= 3, f"only {len(CASES)} parity case(s) committed"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_every_case_states_the_divergence_it_exists_to_catch(case: ParityCase) -> None:
    """An `intent` is the difference between a case and a bar dump.

    When the MQL5 side disagrees, the first question is what the case was *for*,
    and a case that cannot answer it is a case nobody can act on.
    """
    assert len(case.intent.split()) > 12, f"{case.id}: intent is too short to be useful"
    assert (REPO / case.spec).is_file(), f"{case.id}: spec {case.spec} does not exist"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_every_case_bar_is_a_bar_the_engine_will_accept(case: ParityCase) -> None:
    """`BarSeries` validates OHLC ordering, so building one is a real check.

    The same reason the golden fixtures run it: a case with an impossible bar
    would produce a `CASE_ERROR` on both sides and look like agreement.
    """
    series = BarSeries(list(case.bars))
    assert len(series) == len(case.bars)
    assert series[0].time < series[-1].time, f"{case.id}: bar times are not increasing"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_every_case_has_bars_enough_for_a_settled_atr(case: ParityCase) -> None:
    """A series shorter than the ATR period runs the short-series path, and both
    sides would agree about a degenerate answer rather than an engine answer."""
    assert len(case.bars) >= 20, f"{case.id}: {len(case.bars)} bars"
    assert 0 <= case.last_closed < len(case.bars), f"{case.id}: last_closed is out of range"


def test_a_case_without_its_configuration_key_is_refused(tmp_path: Path) -> None:
    """`config` may be empty but it may not be absent.

    A case that omits it runs against whatever the defaults happen to be that
    week, which is the one kind of drift a parity suite cannot tolerate.
    """
    path = tmp_path / "broken.json"
    path.write_text(
        json.dumps(
            {
                "id": "broken",
                "intent": "a case that forgot to record its configuration",
                "spec": "docs/algorithms/BAR_BY_BAR.md",
                "last_closed": 3,
                "bars": [{"o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5}],
                "mql5_vector": None,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="config"):
        load_case(path)


# --------------------------------------------------------------------------
# The canonical form
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_the_vector_covers_every_declared_field(case: ParityCase) -> None:
    """Nothing declared may be silently absent from a vector.

    A field in `FIELD_CLASSES` that no vector produces is a field the harness
    never compares, and the contract would be claiming coverage it does not have.
    """
    produced = {path.split("[", 1)[0] for path in flatten(_vector(case))}
    declared = {path.split("[", 1)[0] for path in FIELD_CLASSES}
    assert produced == declared, f"{case.id}: {sorted(declared ^ produced)}"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_the_vector_is_deterministic(case: ParityCase) -> None:
    """Two runs of the same input produce byte-identical vectors.

    Worth asserting because the vector is built from dicts, and a report that
    disagreed with itself would be unreadable in a way that looks like a parity
    failure.
    """
    assert dump(_vector(case)) == dump(_vector(case))


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_the_vector_does_not_depend_on_bars_after_the_analysed_one(
    case: ParityCase,
) -> None:
    """`RPC-1`, restated for the thing the MQL5 side has to reproduce.

    The whole promise this project makes is that an analysis for bar `k` is
    identical whether or not later bars exist. A parity vector that moved when
    future bars were appended would be measuring something other than what the
    contract says, so the guarantee is asserted on the vector itself and not only
    on the engine.

    `bars_processed` is excluded, and it is the only field that is: it counts the
    bars the run was *given*, so a longer input correctly reports more of them.
    The MQL5 side's obligation for that field is to be fed the same number of
    bars, which is an input condition rather than a behavioural claim. See
    `docs/PYTHON_MQL5_PARITY.md` §3.2.
    """
    extended = dataclasses.replace(
        case, bars=case.bars + tuple(_wild_bars(12, len(case.bars)))
    )
    assert _without_bar_count(_vector(extended)) == _without_bar_count(_vector(case))


def _without_bar_count(vector: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in vector.items() if k != "bars_processed"}


def test_the_vector_reports_a_clamped_last_closed_rather_than_raising() -> None:
    """Clamping is `RPC-4`, and a port that *rejects* an out-of-range index would
    otherwise be reported as agreeing with a clamp."""
    case = CASES[0]
    clamped = canonical_vector(case.bars, len(case.bars) + 50, case.analyzer_config())
    exact = canonical_vector(case.bars, len(case.bars) - 1, case.analyzer_config())
    assert clamped == exact


# --------------------------------------------------------------------------
# The comparison policy
# --------------------------------------------------------------------------


def test_an_index_differing_by_one_is_a_failure_and_names_no_tolerance() -> None:
    """One-bar slop in a confirmation index is a repaint bug, not rounding.

    `observed is None` is the assertion that matters: it says the leaf was
    compared exactly, so a reader can tell this apart from a tolerance pass.
    """
    case = CASES[0]
    other = _vector(case)
    other["swings"][0]["confirmed_bar_index"] += 1
    result = compare(_vector(case), other)

    assert not result.agrees
    assert len(result.differences) == 1
    difference = result.differences[0]
    assert difference.path.endswith("confirmed_bar_index")
    assert difference.kind == MISMATCH
    assert difference.observed is None and difference.tolerance is None


def test_a_price_differing_in_the_fifteenth_digit_agrees() -> None:
    """The tolerance exists for a different order of summation, and this is the
    size of difference that produces."""
    case = CASES[0]
    other = _vector(case)
    other["atr"] = other["atr"] * (1.0 + 1e-15)
    assert compare(_vector(case), other).agrees


def test_a_price_differing_in_the_ninth_digit_does_not_agree() -> None:
    """And this is the size of difference that means the two sides are computing
    something different."""
    case = CASES[0]
    other = _vector(case)
    other["atr"] = other["atr"] * (1.0 + 1e-8)
    result = compare(_vector(case), other)
    assert not result.agrees
    assert result.differences[0].path == "atr"
    assert result.differences[0].tolerance == RELATIVE_TOLERANCE


def test_a_near_zero_reference_uses_the_absolute_floor() -> None:
    """A relative test on a value near zero is meaningless, and the limit the
    comparator reports has to be the limit it actually applied.

    Exercised directly rather than through a case vector, because no real case
    produces a `NUMBER` leaf within 1e-9 of zero — and inventing one to test the
    rule would be testing the fixture, not the rule.
    """
    assert within_tolerance(NUMBER, 0.0, ABSOLUTE_FLOOR / 2)
    assert not within_tolerance(NUMBER, 0.0, ABSOLUTE_FLOOR * 10)
    assert deviation(NUMBER, 0.0, 1e-13) == pytest.approx(1e-13)
    assert within_tolerance(NUMBER, 105.0, 105.0 * (1.0 + 1e-10))


def test_a_nan_is_never_a_match() -> None:
    """`nan != nan` in every language, which is why this is handled before the
    comparison and not by it."""
    case = CASES[0]
    other = _vector(case)
    other["atr"] = math.nan
    result = compare(_vector(case), other)
    assert not result.agrees
    assert result.differences[0].kind == NOT_A_NUMBER
    assert not within_tolerance(NUMBER, math.nan, 1.0)
    assert not within_tolerance(NUMBER, 1.0, math.inf)


def test_a_boolean_never_passes_as_an_integer() -> None:
    """`isinstance(True, int)` is true in Python and false nowhere anybody counts
    on. A `true` where a direction belongs is a type error worth naming."""
    case = CASES[0]
    other = _vector(case)
    other["market_state"]["direction"] = True
    result = compare(_vector(case), other)
    assert not result.agrees
    assert result.differences[0].path == "market_state.direction"


def test_a_field_the_other_side_omitted_is_a_difference_not_a_skip() -> None:
    """The property that stops a three-field implementation passing a
    thirty-three-field contract."""
    case = CASES[0]
    other = _vector(case)
    del other["decision"]["reason"]
    result = compare(_vector(case), other)
    assert not result.agrees
    assert result.differences[0].path == "decision.reason"
    assert result.differences[0].kind == MISSING_IN_CANDIDATE


def test_list_order_is_not_compared_but_a_list_count_is() -> None:
    """Both halves of the stated trade-off, asserted together.

    Order is not contractual because an MQL5 registry is not this registry. Count
    is, because a detector firing once where the other fires twice changes the
    answer.
    """
    case = CASES[0]
    shuffled = _vector(case)
    shuffled["setups"] = list(reversed(shuffled["setups"]))
    shuffled["trade_plans"] = list(reversed(shuffled["trade_plans"]))
    assert compare(_vector(case), shuffled).agrees

    shortened = _vector(case)
    shortened["setups"] = shortened["setups"][:-1]
    result = compare(_vector(case), shortened)
    assert not result.agrees
    assert any(d.path == "setups_count" for d in result.differences)


def test_a_difference_is_reported_with_both_values_and_a_path() -> None:
    """A report that says *that* the two sides differ, without saying where or
    how much, is not actionable."""
    case = CASES[0]
    other = _vector(case)
    other["decision"]["action"] = "BUY" if other["decision"]["action"] != "BUY" else "SELL"
    result = compare(_vector(case), other)
    described = result.differences[0].describe()
    assert result.differences[0].path == "decision.action"
    assert "reference=" in described and "candidate=" in described


def test_a_vector_covering_undeclared_fields_is_refused() -> None:
    """`flatten` raises rather than guessing a comparison class, because a guessed
    one is a comparison nobody chose."""
    case = CASES[0]
    vector = _vector(case)
    vector["decision"]["confidence"] = 0.8
    with pytest.raises(VectorError, match="confidence"):
        flatten(vector)


def test_the_observed_deviation_is_reported_even_on_a_pass() -> None:
    """Two runs can both pass with very different margins, and the difference
    between them is why the tolerance exists."""
    case = CASES[0]
    other = _vector(case)
    other["atr"] = other["atr"] * (1.0 + 1e-12)
    result = compare(_vector(case), other)
    assert result.agrees
    assert result.max_deviation is not None and result.max_deviation > 0.0
    assert result.compared > 0


def test_the_exact_classes_report_no_deviation() -> None:
    """`deviation()` returns `None` for them precisely so "compared exactly" and
    "compared within tolerance" cannot read alike in a report.

    The other half is the count of leaves that carry a tolerance at all: most of
    the contract has none, and a reader should be able to see that.
    """
    assert compare(_vector(CASES[0]), _vector(CASES[0])).max_deviation == 0.0
    assert deviation(EXACT_INT, 1, 1) is None
    assert deviation("EXACT_CODE", "BUY", "BUY") is None
    assert deviation("EXACT_BOOL", True, True) is None
    tolerant = sorted(path for path, kind in FIELD_CLASSES.items() if kind == NUMBER)
    assert tolerant == [
        "atr",
        "market_state.strength",
        "swings[].price",
        "trade_plans[].entry",
        "trade_plans[].reward_to_risk",
        "trade_plans[].stop",
        "trade_plans[].target",
    ]


# --------------------------------------------------------------------------
# The sidecar envelope
# --------------------------------------------------------------------------


def test_a_sidecar_from_another_schema_is_refused(tmp_path: Path) -> None:
    case = CASES[0]
    path = tmp_path / "old.json"
    path.write_text(dump(_sidecar(case, schema="albrooks-parity/0")), encoding="utf-8")
    with pytest.raises(SchemaMismatch):
        load_sidecar(path, case_id=case.id)


def test_a_sidecar_covering_less_than_the_scope_is_refused(tmp_path: Path) -> None:
    """The refusal that matters: a port which implemented three fields must not be
    able to report agreement with a thirty-three-field contract."""
    case = CASES[0]
    path = tmp_path / "thin.json"
    payload = _sidecar(case, scope=["atr", "decision"])
    path.write_text(dump(payload), encoding="utf-8")
    with pytest.raises(ScopeMismatch, match="swings"):
        load_sidecar(path, case_id=case.id)


def test_a_sidecar_for_another_case_is_refused(tmp_path: Path) -> None:
    """Otherwise a passing vector could be reused across every case in the set,
    which would make the whole run one comparison wearing three hats."""
    path = tmp_path / "wrong.json"
    path.write_text(dump(_sidecar(CASES[0], case_id="some_other_case")), encoding="utf-8")
    with pytest.raises(CaseMismatch):
        load_sidecar(path, case_id=CASES[0].id)


def test_the_declared_scope_is_exactly_the_contract() -> None:
    """`SCOPE` and the top-level vector keys are the same list, written twice.

    A group added to one and not the other is a field the harness promises to
    compare and does not, or one it compares and never promised.
    """
    for case in CASES:
        assert set(_vector(case)) == set(SCOPE)
    assert SCOPE == (
        "last_closed_bar",
        "bars_processed",
        "atr",
        "market_state",
        "swings",
        "setups",
        "trade_plans",
        "decision",
    )


# --------------------------------------------------------------------------
# The runner
# --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_a_python_produced_vector_is_not_parity_evidence(
    case: ParityCase, tmp_path: Path
) -> None:
    """Comparing Python against itself must be impossible to mistake for parity.

    `tests/parity/reference/` holds exactly such files, and they are committed on
    purpose, so this is the test that keeps that safe.
    """
    reference = case.path.parent.parent / "reference" / f"{case.id}.python.json"
    assert reference.is_file(), f"{case.id}: no committed reference vector"
    payload = json.loads(reference.read_text(encoding="utf-8"))
    assert payload["producer"] == PRODUCER_PYTHON

    directory = tmp_path / "vectors"
    directory.mkdir()
    name = f"{case.id}.mql5.json"
    (directory / name).write_text(dump(payload), encoding="utf-8")
    pointed = dataclasses.replace(case, mql5_vector=name)
    assert run_case(pointed, directory).status == NOT_AN_MQL5_SIDECAR


def test_a_case_naming_a_missing_sidecar_reports_absent(tmp_path: Path) -> None:
    case = CASES[0]
    pointed = dataclasses.replace(case, mql5_vector="not_there.mql5.json")
    result = run_case(pointed, tmp_path)
    assert result.status == MQL5_ABSENT
    assert "not in" in result.note


def test_a_case_whose_sidecar_reduces_its_scope_is_not_a_mismatch(
    tmp_path: Path,
) -> None:
    """`SCOPE_REDUCED` is not `MISMATCH`, and conflating them would overstate what
    has been learned about the two implementations."""
    case = CASES[0]
    pointed = _write(tmp_path, case, _sidecar(case, scope=list(SCOPE)[:-1]))
    result = run_case(pointed, tmp_path)
    assert result.status == SCOPE_REDUCED
    assert not result.differences


def test_a_case_whose_sidecar_uses_another_schema_is_not_a_mismatch(
    tmp_path: Path,
) -> None:
    case = CASES[0]
    pointed = _write(tmp_path, case, _sidecar(case, schema="albrooks-parity/0"))
    result = run_case(pointed, tmp_path)
    assert result.status == SCHEMA_MISMATCH
    assert not result.differences


def test_a_broken_case_is_contained_rather_than_raising(tmp_path: Path) -> None:
    """One broken case must not end the run: the other two may still disagree, and
    that is worth knowing."""
    case = dataclasses.replace(CASES[0], last_closed=10**6, id="impossible")
    result = run_case(case, tmp_path)
    assert result.status in (MQL5_ABSENT, "CASE_ERROR")
    assert run([case, *CASES], tmp_path).results[-1].case_id == CASES[-1].id


# --------------------------------------------------------------------------
# The report, and what it is not allowed to claim
# --------------------------------------------------------------------------


def test_the_shipped_state_claims_no_parity() -> None:
    """The assertion that keeps Phase 20 from being read as Phase 21.

    No MQL5 build exists, so nothing was compared, and the report says exactly
    that rather than reporting a pass over an empty comparison.
    """
    report = run()
    assert report.status == UNVERIFIED
    assert report.claims_parity is False
    assert report.compared == ()
    assert report.counts()[MQL5_ABSENT] == len(CASES)
    assert "nothing about parity has been established" in report.claim_text


def test_agreement_needs_every_case_to_have_been_compared(tmp_path: Path) -> None:
    """Half a case set is not half a pass.

    Three cases with two filled in must be `FAILED`, because a boolean cannot
    express "these two agreed and that one was never run".
    """
    vectors = tmp_path / "vectors"
    filled = [_write(vectors, case, _sidecar(case)) for case in CASES[:2]]
    assert all(r.status == "MATCH" for r in (run_case(c, vectors) for c in filled))

    results = [run_case(c, vectors) for c in filled]
    results.append(run_case(CASES[2], vectors))
    report = ParityReport(tuple(results))
    assert report.status == FAILED
    assert report.claims_parity is False
    assert len(report.compared) == 2
    assert "2 of 3 case(s) were compared" in report.claim_text


def test_a_full_run_of_agreeing_sidecars_reports_agreement(tmp_path: Path) -> None:
    """The path Phase 21 will take, exercised today with vectors this repository
    produced and labelled honestly."""
    vectors = tmp_path / "vectors"
    filled = [_write(vectors, case, _sidecar(case)) for case in CASES]
    report = ParityReport(tuple(run_case(case, vectors) for case in filled))

    assert report.status == AGREED
    assert report.claims_parity is True
    assert "agreement on the supplied cases" in report.claim_text
    assert report.counts()["MATCH"] == len(CASES)


def test_one_disagreeing_field_fails_the_whole_run(tmp_path: Path) -> None:
    """Not a per-case pass rate with an overall shrug: a port that disagrees once
    is a port that does not agree."""
    vectors = tmp_path / "vectors"
    vectors.mkdir()
    filled = []
    for position, case in enumerate(CASES):
        vector = _vector(case)
        if position == 1:
            vector["atr"] = vector["atr"] * 1.01
        filled.append(_write(vectors, case, _sidecar(case, vector=vector)))
    report = ParityReport(tuple(run_case(case, vectors) for case in filled))

    assert report.status == FAILED
    assert report.claims_parity is False
    assert report.counts()[MISMATCH] == 1
    assert report.counts()["MATCH"] == len(CASES) - 1


def test_the_report_carries_its_own_caveats() -> None:
    """`BACKTESTING.md`'s precedent: a report cannot leave without them, because a
    reader takes the numbers and leaves the prose behind."""
    report = run()
    assert report.caveats
    joined = " ".join(report.caveats).lower()
    for required in ("scope", "tolerance", "order", "outcomes"):
        assert required in joined, f"no caveat mentions {required}"
    assert report.to_dict()["caveats"] == list(report.caveats)


def test_the_report_serialises_with_its_verdict_attached() -> None:
    """`claims_parity` and the claim sentence travel inside the payload, so a
    consumer cannot read the case list and miss the verdict."""
    payload = run().to_dict()
    assert payload["schema"] == SCHEMA_VERSION
    assert payload["status"] == UNVERIFIED
    assert payload["claims_parity"] is False
    assert payload["compared_cases"] == 0
    assert set(payload["counts"]) >= {MQL5_ABSENT, MISMATCH, "MATCH"}


def test_the_unverified_scaffold_stays_in_step_with_ci() -> None:
    """`--allow-unverified` exists for exactly one period: while the shipped state
    is `UNVERIFIED`.

    Phase 21 removes both the flag and the CI use of it. A test that checked only
    that the flag works would let CI keep passing over an unverified claim after
    the real build landed, so the two are linked in both directions.
    """
    ci_text = CI.read_text(encoding="utf-8")
    flag_in_ci = "--allow-unverified" in ci_text
    state_is_unverified = run().status == UNVERIFIED

    assert flag_in_ci == state_is_unverified, (
        "CI's --allow-unverified and the shipped parity state disagree: "
        f"ci={flag_in_ci}, unverified={state_is_unverified}"
    )
    if flag_in_ci:
        result = _main(["--allow-unverified"])
        assert result == 0
        assert _main([]) == 2, "without the flag, an unverified run must not exit 0"


def _main(argv: list[str]) -> int:
    from tests.parity.runner import main

    return main(argv)


def test_a_verified_run_exits_zero_and_a_failed_one_exits_one(tmp_path: Path) -> None:
    """The exit-code mapping, asserted on the three report statuses it maps from.

    `main` reads the case directory from disk, so the mapping is asserted where it
    is defined rather than by running the command against a temporary tree.
    """
    vectors = tmp_path / "vectors"
    good = [_write(vectors, case, _sidecar(case)) for case in CASES]
    assert ParityReport(tuple(run_case(c, vectors) for c in good)).status == AGREED

    broken = _vector(CASES[0])
    broken["decision"]["action"] = "SELL" if broken["decision"]["action"] != "SELL" else "BUY"
    _write(vectors, CASES[0], _sidecar(CASES[0], vector=broken))
    assert ParityReport(tuple(run_case(c, vectors) for c in good)).status == FAILED

    assert ParityReport(()).status == UNVERIFIED
    assert (EXIT_AGREED, EXIT_FAILED, EXIT_UNVERIFIED) == (0, 1, 2)


# --------------------------------------------------------------------------
# The document must not claim more than the code does
# --------------------------------------------------------------------------


def test_the_document_states_the_honest_status() -> None:
    """`RPC-18`'s pattern applied to this document: it makes a claim about the
    number of comparisons performed, and the number is checkable."""
    text = DOC.read_text(encoding="utf-8")
    assert "Zero MQL5 sidecars exist" in text
    assert "Zero cases have been compared" in text
    assert "No parity claim is made anywhere in this project" in text
    assert SCHEMA_VERSION in text
    for group in SCOPE:
        assert group in text, f"the document never names the scope group {group!r}"


def test_the_document_names_the_three_refusals() -> None:
    """The refusals are the design, so a document that dropped them would be
    describing a weaker harness than the one that exists."""
    text = DOC.read_text(encoding="utf-8")
    for marker in ("NOT_AN_MQL5_SIDECAR", "SCOPE_REDUCED", "SCHEMA_MISMATCH"):
        assert marker in text
    assert "UNVERIFIED" in text


def test_the_vector_reports_at_least_one_case_with_real_content() -> None:
    """A case whose vector is empty everywhere would pass a comparison trivially.

    Three cases with setups, plans and a decision is the minimum that makes a
    comparison worth running.
    """
    for case in CASES:
        vector = _vector(case)
        assert vector["swings"], f"{case.id}: no swings, so nothing is being compared"
        assert vector["setups"], f"{case.id}: no setups"
        assert vector["trade_plans"], f"{case.id}: no trade plans"
        assert vector["decision"]["action"] in ("BUY", "SELL", "WAIT", "NO_TRADE")


def test_the_committed_cases_are_the_ones_the_runner_will_find() -> None:
    """Case discovery is by glob, so a file in the wrong place is a case that
    never runs and never fails."""
    on_disk = {p.stem for p in CASES_DIR.glob("*.json")}
    assert on_disk == {case.id for case in CASES}


def test_the_mql5_directory_exists_and_is_empty() -> None:
    """Phase 21 writes the first sidecar here, and until it does the directory is
    part of the claim: it exists, it is documented, and it holds nothing.

    Asserted against `VECTORS_DIR` rather than a path built by hand, because a
    `glob` over a directory that does not exist returns an empty list and would
    have passed the same assertion vacuously.
    """
    assert VECTORS_DIR.is_dir(), "the MQL5 sidecar directory is missing"
    assert (VECTORS_DIR / "README.md").is_file()
    assert list(VECTORS_DIR.glob("*.json")) == [], "an MQL5 sidecar exists"
    for case in CASES:
        assert case.mql5_vector is None, f"{case.id} names a sidecar that does not exist"
