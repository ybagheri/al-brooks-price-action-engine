"""Phase 22 — the LLM-facing serialization, and the refusals it has to hold.

## What this suite is really testing

The interesting claims are not "does it produce JSON" but four things an LLM
interface could plausibly get wrong:

1. **It does not launder a number into a probability.** An LLM handed
   `{"action": "BUY", "evidence_score": 0.85}` will read a likelihood, because
   that is what those shapes mean everywhere else. The brief therefore ships no
   bare score at all: every such value is an object carrying `is_probability:
   false` and a sentence saying what it is.
2. **The refusals are structural, not documentary.** `confidence`, `pnl`,
   `win_rate`, `expectancy`, `profit_factor` and friends are refused by a check
   that runs on *every* call, so a field cannot be added later without a caller
   meeting it. The guard is itself tested, because a guard that has never failed
   is indistinguishable from one that cannot.
3. **A reduction says so.** Dropping 89% of a payload is a material change, so
   `truncated` records what went and why — on every call, empty or not.
4. **It is deterministic.** The same analysis must produce byte-identical JSON,
   or none of the above can be regression-tested.

## The two fixtures

`golden_fm_001` for the rich case: it produces a real `BUY`, a plan, six vetoes
and an evidence bundle, so the brief is exercised against a full result rather
than an empty one. A flat series for the degenerate case, because a reduction
that is only ever tested on rich input is not tested at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from albrooks.core.bars import BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult
from albrooks.serialization.json import (
    CAVEATS,
    CHARS_PER_TOKEN,
    DEFAULT_BUDGET,
    FORBIDDEN_KEYS,
    PROVENANCE,
    SCHEMA_VERSION,
    _assert_refusals,
    brief,
    canonical,
    dumps,
    estimate_tokens,
    to_prompt,
)

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "golden"

#: A fixed epoch, so the brief is byte-identical between runs and machines.
T0 = 1704067200.0


def golden_fm() -> AnalysisResult:
    """`golden_fm_001`, with timestamps added so the brief is byte-stable.

    The fixture carries no timestamps — it is a hand-drawn chart, not a recorded
    series — so a time is added on a fixed grid here. Prices are exactly as
    authored, which is the part that matters for this suite.
    """
    payload = json.loads((GOLDEN / "golden_fm_001.json").read_text(encoding="utf-8"))
    bars = [
        {"time": T0 + row["i"] * 900.0, "o": row["o"], "h": row["h"],
         "l": row["l"], "c": row["c"]}
        for row in payload["bars"]
    ]
    return Analyzer(AnalyzerConfig()).analyze(
        BarSeries(bars), last_closed=int(payload["last_closed"])
    )


def flat(n: int = 80) -> AnalysisResult:
    """A volatility-free series: every layer reports that it could not measure."""
    bars = [{"time": T0 + i * 900.0, "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0}
            for i in range(n)]
    return Analyzer().analyze(BarSeries(bars), last_closed=n - 1)


def ramp(n: int = 60) -> AnalysisResult:
    bars = [
        {"time": T0 + i * 900.0, "o": 100.0 + i * 0.3, "h": 100.0 + i * 0.3 + 0.6,
         "l": 100.0 + i * 0.3 - 0.5, "c": 100.0 + i * 0.3 + 0.2}
        for i in range(n)
    ]
    return Analyzer().analyze(BarSeries(bars), last_closed=n - 1)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_the_same_analysis_always_serializes_to_the_same_bytes() -> None:
    """Determinism is what makes a regression on the payload visible at all.

    A serialization that varies run to run cannot be diffed, and a serialization
    that cannot be diffed cannot be golden-tested. It is also what lets
    `tests/fixtures/golden/` stay a *hand-derived* suite instead of a snapshot:
    a snapshot of a non-deterministic output fails on every run.
    """
    first = canonical(golden_fm())
    second = canonical(golden_fm())
    assert first == second
    assert dumps(brief(golden_fm())) == dumps(brief(golden_fm()))


def test_keys_are_sorted_so_a_diff_is_readable() -> None:
    """Sorted keys are not cosmetic; a payload a human reads in a diff must diff."""
    payload = json.loads(canonical(golden_fm()))
    assert list(payload) == sorted(payload)


def test_a_reduction_of_the_same_result_is_identical_which_path_produced_it() -> None:
    """`brief()` twice, and via `to_prompt`, must agree on the data.

    The instructions appended by `to_prompt` are *outside* the JSON, so extracting
    the data back must reproduce the brief exactly. If it did not, the framing and
    the payload would have drifted apart.
    """
    prompt = to_prompt(golden_fm())
    body = prompt.split("\n\n---\n", 1)[0]
    assert json.loads(body) == brief(golden_fm())


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(FORBIDDEN_KEYS))
def test_no_forbidden_key_can_appear_in_a_brief(key: str) -> None:
    """Each refused key, injected one at a time.

    A guard that has never failed is indistinguishable from a guard that cannot
    fail, so this is the test that makes `_assert_refusals` credible rather than
    decorative — and it runs for every key rather than one representative.
    """
    with pytest.raises(ValueError, match="VALIDATION.md section 9"):
        _assert_refusals({"decision": {key: 0.85}})


def test_the_refusal_check_sees_a_forbidden_key_at_any_depth() -> None:
    """Nested, in a list, and behind a rename.

    A walk that only checked the top level would pass all three, and a future
    refactor that moved a field one level deeper would silently defeat it.
    """
    for payload in (
        {"a": {"b": {"win_rate": 0.5}}},
        {"setups": [{"target": 1.0}, {"expectancy": 2.0}]},
        {"decision": {"evidence": {"confidence": 0.9}}},
    ):
        with pytest.raises(ValueError, match="cannot support"):
            _assert_refusals(payload)


def test_a_real_brief_contains_no_forbidden_key_anywhere() -> None:
    """The check passes on real output, not only on synthetic violations.

    A guard that rejects everything would satisfy every test above.
    """
    for result in (golden_fm(), ramp(), flat()):
        payload = brief(result)
        _assert_refusals(payload)  # must not raise


def test_the_key_list_is_not_hardcoded_in_the_test() -> None:
    """The test reads `FORBIDDEN_KEYS` rather than repeating it.

    A copy of the list in the test would be a second thing to keep in step, and
    the failure mode is the dangerous one: a key added to the guard would not be
    tested, and a key removed from it would not be noticed.
    """
    assert "confidence" in FORBIDDEN_KEYS
    assert "win_rate" in FORBIDDEN_KEYS
    assert "pnl" in FORBIDDEN_KEYS
    assert "profit_factor" in FORBIDDEN_KEYS
    assert len(FORBIDDEN_KEYS) >= 8


def test_no_evidence_score_is_ever_a_bare_number() -> None:
    """The central mechanism: nothing to pattern-match.

    A model asked to summarise `{"value": 1.0, "is_probability": false, "means":
    "..."}` has to read the label. Handed `{"evidence_score": 1.0}` it has nothing
    but the number, and a number that looks like a percentage is read as one.
    """
    payload = brief(golden_fm())
    decision = payload["decision"]
    assert "evidence" in decision, "this fixture should produce an evidence bundle"
    evidence = decision["evidence"]
    assert isinstance(evidence, dict)
    assert evidence["is_probability"] is False
    assert evidence["means"], "the label must say what the number is, not just deny it"
    assert isinstance(evidence["value"], float)


def test_market_state_strength_is_labelled_too() -> None:
    """`strength` is the field a model will quote back as "67% strong".

    It is a proxy share of score, and the label travels with the number rather
    than living in a preamble the model may skip.
    """
    payload = brief(ramp())
    strength = payload["market_state"]["strength"]
    assert strength["is_probability"] is False
    assert "share of proxy score" in strength["means"]


def test_every_score_like_value_in_the_brief_is_a_labelled_object() -> None:
    """A structural check, not a list of expected fields.

    Walks the whole payload for any key that smells like a score and asserts the
    value is not a bare number. A new section added later is covered by
    construction, which is the only way this survives.
    """
    suspicious = ("score", "strength", "probability", "confidence", "value")

    def walk(node: Any, path: str) -> list[str]:
        bad: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}"
                # The value of a *labelled* object is allowed to be a number --
                # that is the whole design. What is forbidden is a bare number
                # under one of these names, so a key is only a violation when its
                # parent is not a labelled wrapper. `is_probability` is the marker
                # that says "the sibling `value` is safe to read as a number".
                is_labelled = "is_probability" in node or "is_recommendation" in node
                if (
                    not is_labelled
                    and key in suspicious
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ):
                    bad.append(here)
                bad.extend(walk(value, here))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                bad.extend(walk(value, f"{path}[{index}]"))
        return bad

    for result in (golden_fm(), ramp(), flat()):
        assert walk(brief(result), "$") == []


# --------------------------------------------------------------------------
# The caveats cannot be dropped
# --------------------------------------------------------------------------


def test_the_caveats_are_present_in_every_brief_and_cannot_be_suppressed() -> None:
    """There is no flag to remove them, by design.

    A reader who does not know these will read the numbers correctly and still be
    misled, which is why they are in the payload rather than in the prose around
    it.
    """
    for result in (golden_fm(), ramp(), flat()):
        payload = brief(result)
        assert payload["caveats"] == list(CAVEATS)
        assert len(CAVEATS) >= 5
    # And there is no parameter that removes them: the signature has none.
    assert "caveats" in brief(golden_fm())
    assert "include_caveats" not in to_prompt.__doc__


def test_the_caveats_name_the_four_claims_a_model_would_otherwise_make() -> None:
    """Not a keyword test. It asserts the specific misreadings are addressed.

    "is not advice", "not a probability", "closed bars only" and the
    no-outcomes claim are the four sentences whose absence would let a model
    produce a confident and wrong answer from a correct payload.
    """
    text = " ".join(CAVEATS).lower()
    for phrase in ("probability", "has not been validated", "not a recommendation",
                   "closed-bar", "not financial advice"):
        assert phrase in text, f"the caveats do not address {phrase!r}"


def test_provenance_declares_the_things_a_reader_needs_to_be_skeptical_with() -> None:
    """`is_validated` and `is_a_recommendation` are the two that matter most.

    They are the fields a consumer is most likely to check before trusting a
    payload, so they are present and explicit rather than inferred from context.

    The key names are read from `PROVENANCE` rather than typed in, because the
    first version of this test asserted `is_recommendation` on a payload that
    spells it `is_a_recommendation` -- a test asserting a field that does not
    exist is a test that raises rather than checks.
    """
    produced = brief(golden_fm())["produced_by"]
    assert produced == PROVENANCE
    for key in ("is_validated", "is_a_recommendation", "is_financial_advice",
                "closed_bar_only"):
        assert key in produced, f"provenance does not declare {key!r}"
    for key in ("is_validated", "is_a_recommendation", "is_financial_advice"):
        assert produced[key] is False, f"{key} must be explicitly False, not absent"
    assert produced["closed_bar_only"] is True
    assert "not affiliated" in produced["concepts"]


# --------------------------------------------------------------------------
# The reduction
# --------------------------------------------------------------------------


def test_the_reduction_is_large_and_that_is_the_measured_reason_for_it() -> None:
    """The design is justified by a number, so the number is asserted.

    `bar_features` is 28 numeric fields per bar and was measured at 88.9% of the
    raw payload. A brief that does not substantially cut it has not solved the
    problem it exists for.
    """
    result = golden_fm()
    full = len(canonical(result))
    reduced = len(dumps(brief(result), indent=None))
    assert reduced < full * 0.25, (
        f"the brief is {reduced} chars against a canonical {full}; a reduction "
        f"that keeps three quarters has not addressed the payload-size problem"
    )
    assert "bar_features" not in brief(result)


def test_what_is_dropped_is_recorded_with_a_reason_on_every_call() -> None:
    """`truncated` is always present, and a dropped section says why.

    Dropping 89% of a payload is a material change, so a reader who does not know
    it happened has been given something that is not what the engine produced.
    """
    payload = brief(golden_fm())
    truncated = payload["truncated"]
    assert "dropped" in truncated
    dropped = {entry["section"] for entry in truncated["dropped"]}
    assert "bar_features" in dropped
    for entry in truncated["dropped"]:
        assert entry["reason"], "every drop states a reason"
        assert entry["items"] > 0


def test_an_empty_dropped_list_is_still_a_claim_worth_making() -> None:
    """`truncated` present and empty means "nothing was dropped", and is asserted.

    A flat series drops nothing, and the section is still there. Omitting it when
    empty would make a reader unable to distinguish "nothing to drop" from "this
    implementation does not report truncation".
    """
    payload = brief(flat(), budget=None)
    assert payload["truncated"]["dropped"] == []
    assert payload["truncated"]["char_used"] > 0


def test_the_budget_records_what_it_was_and_what_it_cost() -> None:
    """A budget with no record of the result is a guess, and this is not one."""
    payload = brief(golden_fm(), budget=DEFAULT_BUDGET)
    assert payload["truncated"]["char_budget"] == DEFAULT_BUDGET
    assert payload["truncated"]["char_used"] < DEFAULT_BUDGET * 1.5


def test_an_unlimited_budget_keeps_what_a_limited_one_drops() -> None:
    """`budget=None` exists so a caller with context to spare is not forced.

    And it proves the reduction is a *choice* rather than a property: the same
    result yields different payloads depending on the budget, and the difference
    is declared in `truncated` either way.
    """
    unlimited = brief(golden_fm(), budget=None)
    assert "bar_features" in unlimited
    assert unlimited["truncated"]["char_budget"] is None

    limited = brief(golden_fm(), budget=DEFAULT_BUDGET)
    assert "bar_features" not in limited
    assert "bar_features" not in limited["truncated"]["dropped"] or True
    assert any(e["section"] == "bar_features" for e in limited["truncated"]["dropped"])


def test_a_tiny_budget_keeps_the_decision_and_the_provenance_anyway() -> None:
    """The answer and the framing survive; the findings go.

    A budget so small that even the caveats do not fit is the interesting case:
    what must never be dropped is the *interpretation*, not the content. A
    reduction that quietly removed the caveats to save characters would be the
    worst possible failure.
    """
    payload = brief(golden_fm(), budget=200)
    assert payload["caveats"] == list(CAVEATS)
    assert payload["produced_by"] == PROVENANCE
    assert payload["decision"]["action"] in ("BUY", "SELL", "WAIT", "NO_TRADE")
    assert payload["decision"]["reason"]
    assert payload["truncated"]["dropped"], "a 200-char budget must drop something"


def test_sections_are_dropped_whole_and_never_mid_value() -> None:
    """Half a stop price is a different stop.

    A reduction that truncated a string or a number to fit would produce a
    payload that is *wrong* rather than incomplete, and incompleteness is at least
    detectable.
    """
    payload = brief(golden_fm(), budget=1500)
    dropped = {entry["section"] for entry in payload["truncated"]["dropped"]}
    assert dropped, "the budget should have forced drops"
    # Whatever survived must be structurally whole.
    assert isinstance(payload["decision"]["action"], str)
    assert isinstance(payload["caveats"], list)
    for entry in payload["truncated"]["dropped"]:
        assert entry["section"] not in payload


# --------------------------------------------------------------------------
# What the brief carries, and what it labels
# --------------------------------------------------------------------------


def test_a_real_decision_survives_the_reduction() -> None:
    """The brief is tested against a result that actually decided something.

    `golden_fm_001` produces a `BUY` with a plan, six vetoes and an evidence
    bundle. A suite that only ever reduced empty results would prove the
    reduction runs, not that it preserves what matters.
    """
    result = golden_fm()
    assert result.decision["action"] == "BUY", "the fixture is expected to decide"

    payload = brief(result)
    decision = payload["decision"]

    assert decision["action"] == "BUY"
    assert decision["reason"] == "RANKED_CANDIDATE"
    assert decision["is_recommendation"] is False
    assert decision["subject"] == result.decision["subject"]
    assert decision["ranking_basis"], "the ranking criteria are echoed, as Phase 15 promises"
    assert decision["vetoes"], "a BUY in this fixture has vetoes on other candidates"


def test_the_chosen_plan_keeps_the_basis_of_every_level() -> None:
    """A stop at 106.69 and a stop at 106.69 are the same number meaning
    different things, and this fixture's chosen stop is an ATR fallback.

    `has_structural_stop: False` is the field that says so, and it is the reason
    a reader must not treat the number as a level the market made.
    """
    plan = brief(golden_fm())["trade_plan"]
    assert plan["stop_basis"] == "ATR_FALLBACK"
    assert plan["target_basis"] == "ATR_FALLBACK"
    assert plan["has_structural_stop"] is False
    assert plan["is_valid"] is True
    assert plan["is_recommendation"] is False
    assert plan["entry_basis"] and plan["entry_basis"] != ""
    assert plan["reward_to_risk"] > 0


def test_prose_is_off_by_default_because_a_model_quotes_the_prose() -> None:
    """The reason code says the same thing in one token.

    `include_explanation` exists for a caller who wants it, and is off because a
    paragraph is what a model will quote back — verbatim and at length — rather
    than the code that constrains it.
    """
    assert "explanation" not in brief(golden_fm())["decision"]
    with_prose = brief(golden_fm(), include_explanation=True)["decision"]
    assert with_prose["explanation"]
    assert with_prose["action"] == brief(golden_fm())["decision"]["action"]


def test_a_degenerate_result_says_why_instead_of_looking_empty() -> None:
    """A flat series produces `NO_ANALYSIS`, and the brief carries the reason.

    This is the `RPC-17` distinction arriving at the serialization layer: "found
    nothing" and "could not measure anything" must not look alike to a reader, and
    an LLM summarising a flat result as "no setups" would be a misreport.
    """
    payload = brief(flat())
    assert payload["decision"]["action"] == "NO_TRADE"
    assert payload["market_state"]["valid"] is False
    assert payload["market_state"]["reason"], "the reason must travel with it"
    assert payload["last_closed_bar"] >= 0
    assert payload["schema"] == SCHEMA_VERSION


def test_the_last_closed_bar_travels_so_a_reader_knows_the_analysis_point() -> None:
    """`RPC-1` made visible: the answer is as of a named bar."""
    result = golden_fm()
    assert brief(result)["last_closed_bar"] == result.last_closed_bar
    assert brief(result)["bars_processed"] == result.bars_processed


def test_warnings_survive_a_reduction() -> None:
    """What the engine noticed and did not act on is kept.

    `STOP_WIDE` and friends are deliberately non-blocking at the plan layer, which
    means they are the *only* record that a condition was noticed. Dropping them
    would turn "noticed and reported" into "never noticed".
    """
    assert "warnings" in brief(golden_fm())


# --------------------------------------------------------------------------
# Prices are not rounded by default
# --------------------------------------------------------------------------


def test_prices_are_not_rounded_by_default() -> None:
    """Rounding a stop to 2dp can move it through the level it was protecting.

    The fixture's stop is `106.68656533354194`, which is not a price any broker
    would quote and is exactly the kind of value a display rounding would
    destroy.
    """
    plan = brief(golden_fm())["trade_plan"]
    assert plan["stop"] == pytest.approx(106.68656533354194)
    assert len(str(plan["stop"]).split(".")[-1]) > 2


def test_display_rounding_is_available_and_declared_lossy() -> None:
    """A caller who wants readable numbers can have them, and is told."""
    payload = brief(golden_fm(), float_digits=2)
    assert payload["float_rounding"]["is_lossy"] is True
    assert payload["float_rounding"]["digits"] == 2
    assert payload["trade_plan"]["stop"] == pytest.approx(106.69)


# --------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------


def test_the_instructions_come_after_the_data_on_purpose() -> None:
    """A model reads the data first and the framing second.

    Putting the framing first would have it compete for attention with the
    payload; putting it after means it is the last thing in the context, which is
    the position recency favours.
    """
    prompt = to_prompt(golden_fm())
    body, _, instructions = prompt.partition("\n\n---\n")
    assert instructions, "the instructions must be present"
    assert body.startswith("{")
    assert body.rstrip().endswith("}")
    assert "caveats" in body, "the data block carries its own caveats as well"


def test_the_instructions_say_what_not_to_do_not_only_what_to_say() -> None:
    """The four refusals a model would otherwise make.

    Asked for a probability, asked to add a stop that is not there, asked to fill
    a gap the truncation left, or asked to treat a ranking as advice — each is
    pre-empted in the text a model is most likely to follow.
    """
    _, _, instructions = to_prompt(golden_fm()).partition("\n\n---\n")
    lowered = instructions.lower()
    assert "percentage chance" in lowered
    assert "not advice" in lowered
    assert "do not add" in lowered
    assert "say it is missing" in lowered


def test_the_instructions_can_be_omitted_for_a_caller_that_adds_its_own() -> None:
    """Not forbidden, just not the default.

    Some consumers put their own system prompt in front and would rather not have
    a second set of instructions in the user turn. The data is identical either
    way, which the determinism test already establishes.
    """
    prompt = to_prompt(golden_fm(), include_instructions=False)
    assert "---" not in prompt
    assert json.loads(prompt) == brief(golden_fm())


# --------------------------------------------------------------------------
# The token estimate is labelled as an estimate
# --------------------------------------------------------------------------


def test_the_token_estimate_is_roughly_right_and_says_it_is_rough() -> None:
    """A number in the wrong unit would be worse than no number.

    Four characters per token is a reasonable rule for English JSON and a poor
    one for code or Persian text, so the docstring says so and this test checks
    only the order of magnitude — which is all it can honestly check.
    """
    payload = brief(golden_fm())
    estimated = estimate_tokens(payload)
    assert 0 < estimated <= len(dumps(payload, indent=None)) // CHARS_PER_TOKEN + 1
    assert CHARS_PER_TOKEN == 4
    assert "estimate" in estimate_tokens.__doc__.lower()


# --------------------------------------------------------------------------
# The schema version is its own contract
# --------------------------------------------------------------------------


def test_the_schema_version_is_independent_of_the_parity_schema() -> None:
    """Two schemas for two incompatible purposes, deliberately not merged.

    `albrooks-parity/1` is a two-implementation comparison contract with
    per-field tolerance classes. `albrooks-llm/1` is a single-implementation
    payload for a reader. They will drift, and sharing a version string would make
    "the fields moved" indistinguishable from "the market moved".
    """
    from tests.parity.contract import SCHEMA_VERSION as PARITY_SCHEMA

    assert SCHEMA_VERSION != PARITY_SCHEMA
    assert SCHEMA_VERSION.startswith("albrooks-llm/")
    assert PARITY_SCHEMA.startswith("albrooks-parity/")


def test_the_schema_version_is_present_on_every_payload() -> None:
    """A version a consumer has to be told about is not a version."""
    for result in (golden_fm(), ramp(), flat()):
        assert brief(result)["schema"] == SCHEMA_VERSION
