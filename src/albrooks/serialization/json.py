"""A stable, LLM-facing serialization of an analysis — and an opinion about what
an LLM must never be handed.

## The problem this solves, stated as a measurement

`AnalysisResult.to_dict()` is 41,600 characters for a 60-bar series, and
**88.9% of that is `bar_features`** — 28 numeric fields for every bar. A model
handed the raw payload spends almost all its attention on per-bar arithmetic it
does not need, and almost none on the decision, the plan, or the reasons.

So this module is a **reduction with a budget**, not a reformatting. `brief()`
answers "what does a reader need to know about this bar?" in a few hundred
characters, and says what it dropped.

## The problem this solves, stated as a risk

An LLM is the most likely consumer in this project to break its central promise.
Handed `{"action": "BUY", "evidence_score": 0.85}`, a model will read a
probability, because that is what those shapes mean everywhere else. It is not:
`CONCEPT_TAXONOMY.md` §5 says no number here is `STATISTICAL`, because **nothing
in this project has been validated against outcomes**, and `VALIDATION.md` §9
lists the four missing ingredients.

So the serialization is built to make misreading *structurally hard* rather than
merely discouraged:

1. **No bare score.** Every quantity that could be misread is an object carrying
   its own `is_probability: false` and a sentence saying what it means. There is
   no `0.85` sitting alone in the output to be pattern-matched.
2. **The refusals are structural.** No `confidence`, no `pnl`, no `win_rate`, no
   `expectancy`, no `profit_factor` — and `_assert_refusals()` walks the
   serialized tree checking, so a field cannot be added later without this module
   failing. The same pattern `test_phase18_backtesting.py` uses on the backtest
   module.
3. **The caveats cannot be dropped.** `brief()` always emits them, there is no
   flag to suppress them, and a test asserts that.
4. **Truncation is always reported.** Dropping 28 fields per bar to fit a budget
   is a material change to the payload, so `truncated` says what was dropped and
   how much. A reduction that did not say so would be a quiet lie about what the
   reader is looking at.

## What `brief()` keeps, and why

| Kept | Why it survives a budget |
|---|---|
| `decision` + its reason | The answer, and *why* — the project's whole point |
| the chosen `trade_plan` | The geometry, with every level's basis |
| `market_state` | The context every gate is conditioned on |
| recent `swings` / `legs` | Where the structures are |
| `measured_moves`, `setups` | What was found |
| `evidence` | Why the score is what it is |
| `warnings` | What the engine noticed and did not act on |

| Dropped first | Why |
|---|---|
| `bar_features` | 89% of the payload, and the least load-bearing part of it |
| `explanation` prose | Long, and the reason codes say the same thing in fewer words |
| non-chosen `trade_plans` | Reported as a count, so nothing is silently lost |
| older `swings` | The recent ones are what a current reading rests on |

## Determinism

`canonical()` sorts keys and uses Python's shortest-round-trip float repr, so
**the same analysis always produces byte-identical JSON**. That matters more than
it might seem: a serialization you can diff is a serialization whose regressions
you can see, and it is what makes a golden test on the *serialized form* possible
at all — which `tests/fixtures/golden/` deliberately is not, because a snapshot of
the engine's output cannot tell a fix from a regression.

**No rounding is applied to prices.** Rounding a stop to 2dp can move it through
the level it was protecting. A `float_digits` option exists for display and is
recorded in the output as lossy.

## The budget is characters, not tokens

There is no tokenizer here and no dependency may be added, so the budget is
counted in **characters** and the approximation is stated in the output rather
than hidden: roughly four characters per token for English and JSON, so
`budget=8000` is about 2,000 tokens. A caller who needs a real token count must
count it — the alternative is a number here that looks like tokens and is not.

## What this module will not do

It will not add a field an LLM could read as a forecast, and it will not let a
reduction happen silently. Both are refusals rather than omissions, and both are
tested. If a future change needs a probability out of this engine, the answer is
`VALIDATION.md` §9, not a new key here.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from albrooks import __version__
from albrooks.engine.state import AnalysisResult

#: The version of the LLM-facing contract. Bumped whenever the *shape* changes, so
#: a consumer can tell "the fields moved" from "the market moved".
#:
#: This is deliberately separate from the parity harness's `SCHEMA_VERSION`
#: (`albrooks-parity/1`). That one is a two-implementation comparison contract
#: with per-field tolerance classes; this one is a single-implementation payload
#: for a reader. They will drift, and merging them would mean one schema serving
#: two incompatible purposes.
SCHEMA_VERSION = "albrooks-llm/1"

#: Keys that must never appear anywhere in a serialized payload.
#:
#: Each is a claim about the future that nothing here can support. `confidence` is
#: listed first because it is the one an LLM would reach for, and
#: `CONCEPT_TAXONOMY.md` §6 explains why the gate is called `min_score` instead.
#:
#: Checked mechanically by `_assert_refusals()` rather than documented, following
#: `BACKTESTING.md`'s precedent: a refusal that is only written down is a refusal
#: that erodes.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "confidence",
        "probability",
        "win_rate",
        "winrate",
        "expectancy",
        "profit_factor",
        "sharpe",
        "pnl",
        "equity",
        "balance",
    }
)

#: Approximate characters per token for English and JSON. Stated rather than
#: assumed, because a budget reported in a unit it is not measured in is worse than
#: no budget at all.
CHARS_PER_TOKEN = 4

#: Default character budget. About 2,000 tokens, which is small enough that a
#: model's attention is not spent on the payload and large enough for the decision,
#: the plan and the evidence.
DEFAULT_BUDGET = 8_000

#: How many recent swings and legs survive before truncation kicks in.
DEFAULT_RECENT_STRUCTURES = 8

#: The non-negotiable block. Present in every `brief()` with no way to suppress
#: it, because a reader who does not know these will read the numbers correctly
#: and still be misled.
CAVEATS: tuple[str, ...] = (
        "No number in this payload is a probability, a likelihood or a win rate. "
        "This project has not been validated against outcomes, and "
        "CONCEPT_TAXONOMY.md section 5 says why.",
        "The evidence score is a mean of observed factor weights. 0.85 does not "
        "mean 'right 85% of the time'; it means the factors behind this candidate "
        "averaged 0.85 on their declared weights.",
        "A BUY or SELL means one plan passed every declared gate and had the most "
        "evidence by the declared ranking. It is not a recommendation, and no "
        "order, size or entry instruction is implied.",
        "Every threshold in the engine is a chosen heuristic on a transparent "
        "number. Raising one does not improve a reading; it makes fewer readings "
        "eligible.",
        "The analysis is closed-bar only. It reads bars up to last_closed_bar and "
        "cannot see later ones.",
    "This is analysis output, not financial advice.",
)

#: What this project is, in the terms a reader needs to be skeptical with.
PROVENANCE: dict[str, Any] = {
    "package": "albrooks",
    "version": __version__,
    "is_financial_advice": False,
    "is_validated": False,
    "is_a_recommendation": False,
    "concepts": "systematic proxies for a price-action methodology, written from "
    "scratch; not affiliated with, endorsed by, or connected to its author",
    "closed_bar_only": True,
}


# --------------------------------------------------------------------------
# Deterministic serialization
# --------------------------------------------------------------------------


def canonical(result: AnalysisResult, *, indent: int | None = 2) -> str:
    """The full result as deterministic JSON.

    Sorted keys and Python's shortest-round-trip float repr make this
    byte-identical for a given analysis, which is what lets a golden test exist
    on the *serialized* form. Nothing is dropped, rounded or reordered: this is
    `to_dict()` with a promise attached.

    `indent=2` by default because a payload a human will read in a diff should be
    diffable, and `indent=None` is available for a model that pays per token.
    """
    return dumps(result.to_dict(), indent=indent)


def dumps(payload: Any, *, indent: int | None = 2) -> str:
    """`json.dumps` with the two settings this project needs everywhere.

    `sort_keys` for a stable order, and `ensure_ascii=False` so the Persian
    terminology in `README_FA.md` and any symbol name survive as text rather than
    as escape sequences — a payload full of backslash-u escapes is unreadable to
    exactly the reader it is hardest for.
    """
    return json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------
# The reduction
# --------------------------------------------------------------------------


def _scored(value: float, means: str) -> dict[str, Any]:
    """A number packaged so it cannot be read as a probability.

    This is the mechanism, and it is deliberately awkward: the caller cannot get
    a bare `0.85` out of the brief, so there is nothing for a model to
    pattern-match. The sentence travels with the number, which means the reading
    is stated at the point of use rather than in a preamble that gets skipped.
    """
    return {"value": round(float(value), 6), "is_probability": False, "means": means}


def _last(values: Sequence[Any], count: int) -> list[Any]:
    """The most recent `count` items, oldest-first within the slice."""
    return list(values[-count:]) if count > 0 else []


def brief(
    result: AnalysisResult,
    *,
    budget: int | None = DEFAULT_BUDGET,
    recent: int = DEFAULT_RECENT_STRUCTURES,
    include_explanation: bool = False,
    float_digits: int | None = None,
) -> dict[str, Any]:
    """The LLM-facing view: reduced, labelled, and honest about what it dropped.

    `budget` is in **characters** and is enforced by dropping whole sections in a
    declared order — never by truncating a sentence or a number, because half a
    stop price is a different stop. `budget=None` means no limit, which is useful
    for a caller with a large context and for testing the reduction is not what
    makes the payload small.

    `float_digits` rounds every float **for display only** and records that it
    did. Prices are not rounded by default: rounding a stop to 2dp can move it
    through the level it was protecting.
    """
    decision = dict(result.decision or {})
    plan = dict(decision.get("plan") or {})
    state = dict(result.market_state or {})

    out: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "produced_by": dict(PROVENANCE),
        "caveats": list(CAVEATS),
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "bars_processed": result.bars_processed,
        "last_closed_bar": result.last_closed_bar,
        "market_state": _market_state(state),
        "decision": _decision(decision, include_explanation=include_explanation),
        "truncated": _truncation(),
    }

    if plan:
        out["trade_plan"] = _plan(plan)

    # Optional *content*, dropped in this order when the budget is exceeded.
    # budget is exceeded. The order is the value: bar features are the least
    # load-bearing thing in the payload and the largest, so they go first.
    # Ordered by what may be dropped first. `bar_features` is 89% of the raw
    # payload and the least load-bearing part of it, so it goes first; the
    # findings come last, because dropping a *finding* hides what the engine saw
    # and a reduction that did that would be a quiet lie about the reading.
    optional: list[tuple[str, Any, str]] = [
        ("bar_features", result.bar_features,
         "89% of the raw payload and the least load-bearing part of it; "
         "per-bar arithmetic a decision does not depend on"),
        ("trends", result.trends, "derived from market_state, which is kept"),
        ("channels", result.channels, "one entry at most, and empty unless a "
         "channel was detected"),
        ("evidence", _evidence(result.evidence),
         "the factors behind the score; the score itself is kept and labelled"),
        ("legs", _last(result.legs, recent), "the recent structures are kept"),
        ("setups", _identified(result.setups), "the chosen candidate's plan is kept"),
        ("measured_moves", _identified(result.measured_moves),
         "projections that did not become the candidate"),
        ("detectors", result.detectors, "which detectors ran; visible in `layers`"),
        ("unimplemented_layers", result.unimplemented_layers,
         "empty on a normal analysis"),
    ]

    # Kept whatever the budget, because each answers a question a reader asks
    # about the reading itself rather than about the market.
    for key, value in (
        ("warnings", list(result.warnings)),
        ("swings", _last(result.swings, recent)),
    ):
        if value:
            out[key] = value

    for key, value, why in optional:
        if not value:
            continue
        projected = len(dumps({**out, key: value}))
        if budget is not None and projected > budget:
            out["truncated"]["dropped"].append(
                {
                    "section": key,
                    "reason": why,
                    "items": len(value) if isinstance(value, (list, tuple)) else 1,
                }
            )
            continue
        out[key] = value

    # Recorded after the sections are settled, so `char_used` is the size of what
    # was actually emitted rather than a running projection.
    if budget is not None:
        out["truncated"]["char_budget"] = budget
    out["truncated"]["char_used"] = len(dumps(out, indent=None))

    if float_digits is not None:
        rounded = _round_floats(out, float_digits)
        assert isinstance(rounded, dict), "_round_floats preserves the top-level dict"
        out = rounded
        out["float_rounding"] = {
            "digits": float_digits,
            "is_lossy": True,
            "note": "prices are rounded for display; use the untruncated form for "
            "arithmetic",
        }

    _assert_refusals(out)
    return out


def _truncation() -> dict[str, Any]:
    """The record of what was left out. Never absent, never empty-and-silent.

    A `truncated` section that is present and empty is a claim — "nothing was
    dropped" — and a claim worth making, because the alternative is a reader
    assuming a reduction happened for no stated reason.
    """
    return {"dropped": [], "char_budget": None, "char_used": None}


def _market_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Context, with the one number that gets misread labelled.

    `strength` is a proxy share of score and it is the field an LLM will quote
    back as "the trend is 67% strong". It is not, and the label is attached at the
    point of use.
    """
    out = {
        "valid": bool(state.get("valid", False)),
        "mode": str(state.get("mode", "UNKNOWN")),
        "direction": int(state.get("direction", 0) or 0),
    }
    if "strength" in state:
        out["strength"] = _scored(
            float(state.get("strength", 0.0) or 0.0),
            "share of proxy score held by the winning market-state mode; a chosen "
            "proxy, not a probability of continuation",
        )
    if state.get("evidence"):
        out["evidence"] = list(state["evidence"])
    if state.get("warnings"):
        out["warnings"] = list(state["warnings"])
    if not state.get("valid", False):
        out["reason"] = str(state.get("reason", ""))
    return out


def _decision(decision: Mapping[str, Any], *, include_explanation: bool) -> dict[str, Any]:
    """The answer, its reason code, and the criteria that chose it.

    `explanation` is prose and is off by default: the reason code says the same
    thing in one token, and a model given a paragraph will quote the paragraph
    rather than the code.
    """
    out = {
        "action": str(decision.get("action", "NO_TRADE")),
        "reason": str(decision.get("reason", "")),
        "is_actionable": bool(decision.get("is_actionable", False)),
        "is_recommendation": False,
    }
    if decision.get("subject"):
        out["subject"] = str(decision["subject"])
    if "direction" in decision:
        out["direction"] = int(decision.get("direction", 0) or 0)
    if decision.get("vetoes"):
        out["vetoes"] = [
            {
                "code": str(v.get("code", "")),
                "subject": str(v.get("subject", "")),
                "config_key": str(v.get("config_key", "")),
            }
            for v in decision["vetoes"]
            if isinstance(v, Mapping)
        ]
    if decision.get("ranking_basis"):
        out["ranking_basis"] = list(decision["ranking_basis"])
    evidence = decision.get("evidence")
    if isinstance(evidence, Mapping) and "value" in evidence:
        out["evidence"] = _scored(
            float(evidence["value"]),
            "mean of observed evidence-factor weights, balanced per source; a "
            "checklist average, not a likelihood",
        )
    if include_explanation and decision.get("explanation"):
        out["explanation"] = list(decision["explanation"])
    return out


def _plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Geometry, with every level's basis.

    The bases are the reason a level is defensible: a stop derived from a swing
    low and one derived from an ATR multiple are the same number meaning different
    things, and `has_structural_stop` says which this is.
    """
    out = {
        "subject": str(plan.get("subject", "")),
        "direction": int(plan.get("direction", 0) or 0),
        "entry": float(plan.get("entry", 0.0)),
        "stop": float(plan.get("stop", 0.0)),
        "target": float(plan.get("target", 0.0)),
        "entry_basis": str(plan.get("entry_basis", "")),
        "stop_basis": str(plan.get("stop_basis", "")),
        "target_basis": str(plan.get("target_basis", "")),
        "reward_to_risk": float(plan.get("reward_to_risk", 0.0)),
        "is_valid": bool(plan.get("is_valid", False)),
        "has_structural_stop": bool(plan.get("has_structural_stop", False)),
        "is_recommendation": False,
    }
    for field_name in ("risk", "reward", "bar_index", "signal_bar"):
        if field_name in plan:
            out[field_name] = plan[field_name]
    if plan.get("issues"):
        out["issues"] = list(plan["issues"])
    if plan.get("warnings"):
        out["warnings"] = list(plan["warnings"])
    if plan.get("invalidation"):
        out["invalidation"] = str(plan["invalidation"])
    return out


def _evidence(items: Sequence[Any]) -> list[dict[str, Any]]:
    """Evidence factors, flattened and labelled by source.

    Sources keep their own vocabulary and are not merged: a market-state reason
    and a measured-move factor measure different things, and summing them would
    imply a comparability that does not exist.
    """
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        out.append(
            {
                "source": str(item.get("source", "")),
                "code": str(item.get("code", "")),
                "is_probability": False,
            }
        )
    return out


def _identified(items: Sequence[Any]) -> list[dict[str, Any]]:
    """Setups and projections, reduced to their identity and direction.

    Their full payloads contain prose `detail` strings and nested evidence, which
    is where a reduction stops: a model quoting "the target is 111.1" needs the
    number and the basis, not the derivation.
    """
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {}
        for key in (
            "detector",
            "kind",
            "setup_family",
            "family",
            "state",
            "setup_type",
            "direction",
            "target_price",
            "bar_index",
        ):
            if key in item and item[key] is not None:
                entry[key] = item[key]
        if entry:
            out.append(entry)
    return out


def _round_floats(node: Any, digits: int) -> Any:
    """Round every float in the tree. Used only for display."""
    if isinstance(node, bool):
        return node
    if isinstance(node, float):
        return round(node, digits)
    if isinstance(node, dict):
        return {k: _round_floats(v, digits) for k, v in node.items()}
    if isinstance(node, list):
        return [_round_floats(v, digits) for v in node]
    return node


# --------------------------------------------------------------------------
# The refusals, enforced
# --------------------------------------------------------------------------


def _assert_refusals(payload: Any, path: str = "$") -> None:
    """Fail if a forbidden key appears anywhere in the payload.

    Not a test-only check: this runs on every `brief()` call, so a field cannot be
    added later without a caller noticing at the point they use it. The test suite
    asserts that the check itself can fail, because a guard that has never failed
    is indistinguishable from a guard that cannot.
    """
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(
                    f"{path}.{key} is a claim about outcomes that this project "
                    f"cannot support; see VALIDATION.md section 9"
                )
            _assert_refusals(value, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_refusals(value, f"{path}[{index}]")


def estimate_tokens(payload: Mapping[str, Any]) -> int:
    """An **estimate** of token count, and the number is labelled as one.

    Four characters per token is a reasonable English-and-JSON rule of thumb and a
    poor one for code, symbol names or Persian text. A caller who needs a real
    count must measure it with their own tokenizer; this exists so a budget can be
    expressed in a familiar unit without pretending to precision it does not have.
    """
    return max(1, len(dumps(payload, indent=None)) // CHARS_PER_TOKEN)


def to_prompt(
    result: AnalysisResult,
    *,
    budget: int | None = DEFAULT_BUDGET,
    include_instructions: bool = True,
) -> str:
    """The brief as a single text block, ready to hand a model.

    The instructions are appended **after** the data deliberately. A model reads
    the data first and the framing second, so putting the framing first would have
    it compete for attention with 8,000 characters of numbers, and putting it
    after means it is the last thing in the context — the position that recency
    favours.

    The instructions say what the payload is *not*, and are not optional by
    default, for the reason in the module docstring: the most likely way this
    project gets misread is a model that was handed a number without the caveat
    attached to it.
    """
    payload = brief(result, budget=budget)
    body = dumps(payload, indent=None)
    if not include_instructions:
        return body
    return (
        f"{body}\n\n"
        "---\n"
        "Read the caveats above before answering. Specifically:\n"
        "- No figure here is a probability or a likelihood. If asked for a "
        "percentage chance of success, say that the project has not been "
        "validated and that the number is a factor average.\n"
        "- `action` is a ranking result under declared criteria, not advice.\n"
        "- Do not add a stop, target, size or entry that is not in the payload.\n"
        "- If something is missing, say it is missing rather than inferring it. "
        "The `truncated` section records what was dropped.\n"
    )


__all__ = [
    "CAVEATS",
    "CHARS_PER_TOKEN",
    "DEFAULT_BUDGET",
    "DEFAULT_RECENT_STRUCTURES",
    "FORBIDDEN_KEYS",
    "PROVENANCE",
    "SCHEMA_VERSION",
    "brief",
    "canonical",
    "dumps",
    "estimate_tokens",
    "to_prompt",
]
