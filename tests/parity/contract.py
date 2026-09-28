"""The canonical form both implementations must produce to be comparable.

## Why a canonical form at all

Two implementations cannot be compared by diffing their outputs, because they
will not have the same outputs. Python's `AnalysisResult` is a tree of dicts
built by `asdict()`; an MQL5 build is a sequence of struct writes into a CSV or a
JSON string. Comparing them directly means comparing two representations, and
every difference found would be a difference in *shape* rather than in
behaviour.

So both sides reduce their run to the same small, declared structure — the
**parity vector** — and the harness compares vectors. What is in the vector is
`SCOPE`, and `FIELD_CLASSES` says how each leaf is compared. Nothing outside
`SCOPE` is compared, and nothing inside it may be skipped.

## The scope was chosen by asking what a wrong MQL5 port would get wrong

Every field here is a field whose *disagreement* would mean the two engines are
not the same engine, and nothing else was included:

- **`last_closed_bar`, `bars_processed`** — the two sides read different bars.
  MT5 series are newest-first and this engine oldest-first, so an off-by-one here
  is the likeliest divergence in the whole port.
- **`atr`** — Wilder smoothing is a recursive chain, so a different seed, window
  or summation order shows up here before anywhere else.
- **`market_state`** — the classification everything else is conditioned on. A
  `BULL_TREND` against a `TRADING_RANGE` is not a rounding difference.
- **`swings`** — `bar_index` *and* `confirmed_bar_index`, both exactly. A port
  that emits the pivot bar instead of the confirming bar has broken the
  non-repaint contract, and one-bar slop is not rounding.
- **`setups`** — what was detected, at what direction, in what state.
- **`trade_plans`** — the geometry: entry, stop, target, reward:risk, and the
  basis of each level.
- **`decision`** — the product-level answer, including the reason code, so a
  `WAIT` for two different reasons is a visible disagreement.

**One field in that table is not closed-bar stable, and it is `bars_processed`.**
It counts the bars it was *given*, not the bars it read, so appending future bars
to a series moves it — correctly, since the input grew. Every other field in the
scope describes the analysis and is therefore covered by `RPC-1`. An MQL5 side
must be fed the same number of bars as the Python side for this field to agree,
which is a weaker obligation than "behave identically" and a much easier one to
state precisely, so it is left in rather than dropped.

## What is deliberately not in the vector

- **Prose.** `explanation`, `invalidation`, `management`, `warnings`, evidence
  `detail`. These are sentences written for a human, and two implementations
  phrasing the same reasoning differently is not a defect. If the numbers agree,
  the reasoning agrees; a text diff would only ever produce noise.
- **`is_probability` and `is_recommendation`.** Constant `false` on both sides by
  construction, so comparing them proves nothing. They are asserted on the
  Python side by the Phase 19 suite instead.
- **The `layers` map.** Also constant. Its purpose is to distinguish "found
  nothing" from "did not run", which is a property of *one* implementation.
- **Backtest and golden-fixture expectations.** Python-only concepts with no MQL5
  counterpart, and `docs/algorithms/VALIDATION.md` already owns what they mean.

## The comparison classes

An index that differs by one is a repaint bug. A price that differs in the ninth
significant digit is a summation order. Those are different failures and the
comparator treats them differently, which is why every leaf declares a class
rather than the whole vector sharing one epsilon.

The comparison classes, in a list rather than a table because a table row
cannot wrap and these are read in source:

- `EXACT_INT` — `==`. A bar index, a direction, a count.
- `EXACT_CODE` — `==`. A mode, a reason code, a basis label.
- `EXACT_BOOL` — `==`, with a `bool`/`int` guard.
- `CODE_OR_NULL` — equal when both are `null`, or both the same string.
- `NUMBER` — within `RELATIVE_TOLERANCE` of the reference, `ABSOLUTE_FLOOR` when
  the reference is near zero.

`NUMBER` is the only class with a tolerance, and `RELATIVE_TOLERANCE = 1e-9` is
about nine significant digits: far tighter than any heuristic threshold in this
project, and loose enough to absorb a different order of summation. A real logic
divergence — the wrong swing, the wrong ATR branch, a gate on the wrong side —
moves a value by a percent or by whole bars, not by the fifteenth digit. The
observed deviation is reported per case, so a run that passes with a 1e-15 margin
and one that passes with 8e-10 both say so rather than reading the same.

**A tolerance is not a proof of identical arithmetic.** It is a statement about
where two implementations may legitimately differ, and it is a weak one. The
stronger statement is `EXACT_INT` and `EXACT_CODE` everywhere else.

## Ordering is not part of the contract

Lists are compared as multisets. The harness sorts both sides by the canonical
JSON encoding of their own elements before diffing, so an MQL5 build may emit its
setups in any order — its registry is not this project's registry, and
`SETUP_ENGINE.md` §5 is explicit that registration order is not a ranking. The
cost is real and worth stating: a genuine ordering difference between the two
ports would not be caught. A *count* difference would be, and that is the
difference that changes behaviour.

Duplicates are therefore preserved, and a detector that fires twice where the
other fires once is a disagreement about counts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from albrooks.core.bars import BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.price_action.bars import calculate_atr_series

#: The version of the canonical form. Bumped whenever `SCOPE` or `FIELD_CLASSES`
#: changes meaning, and a sidecar carrying a different value is refused rather
#: than compared — two sides implementing different contracts can agree on
#: everything they both check and still not be the same contract.
SCHEMA_VERSION = "albrooks-parity/1"

#: The only value that counts as a second implementation.
#:
#: A vector whose `producer` is anything else is not evidence of parity, and the
#: runner will not compare it as though it were. This is the one field in the
#: harness that exists to stop a Python-produced file from being counted as an
#: MQL5 run.
PRODUCER_MQL5 = "mql5"

#: The producer of a vector this repository generated. Never parity evidence.
PRODUCER_PYTHON = "python"

#: Relative tolerance for `NUMBER` leaves. See the module docstring.
RELATIVE_TOLERANCE = 1e-9

#: Absolute tolerance used instead of the relative one when the reference is
#: within `RELATIVE_TOLERANCE` of zero, where a relative test is meaningless.
ABSOLUTE_FLOOR = 1e-12

EXACT_INT = "EXACT_INT"
EXACT_CODE = "EXACT_CODE"
EXACT_BOOL = "EXACT_BOOL"
CODE_OR_NULL = "CODE_OR_NULL"
NUMBER = "NUMBER"

#: The top-level groups a sidecar must cover. A sidecar declaring a strict
#: subset is refused rather than passed, because "we agree on the three fields we
#: implemented" is not parity.
SCOPE: tuple[str, ...] = (
    "last_closed_bar",
    "bars_processed",
    "atr",
    "market_state",
    "swings",
    "setups",
    "trade_plans",
    "decision",
)

#: Canonical leaf path -> comparison class. This mapping is the contract: a leaf
#: that is not declared here is an error in the harness, not a field to skip.
#:
#: `[]` is a list of any length; the count of each list is a separate declared
#: leaf so a length disagreement is reported as one rather than as a wall of
#: per-element differences.
FIELD_CLASSES: dict[str, str] = {
    "last_closed_bar": EXACT_INT,
    "bars_processed": EXACT_INT,
    "atr": NUMBER,
    "market_state.valid": EXACT_BOOL,
    "market_state.mode": EXACT_CODE,
    "market_state.direction": EXACT_INT,
    "market_state.strength": NUMBER,
    "swings_count": EXACT_INT,
    "swings[].bar_index": EXACT_INT,
    "swings[].confirmed_bar_index": EXACT_INT,
    "swings[].price": NUMBER,
    "swings[].direction": EXACT_INT,
    "setups_count": EXACT_INT,
    "setups[].detector": EXACT_CODE,
    "setups[].kind": EXACT_CODE,
    "setups[].setup_family": EXACT_CODE,
    "setups[].direction": EXACT_INT,
    "setups[].setup_type": CODE_OR_NULL,
    "trade_plans_count": EXACT_INT,
    "trade_plans[].direction": EXACT_INT,
    "trade_plans[].entry": NUMBER,
    "trade_plans[].stop": NUMBER,
    "trade_plans[].stop_basis": EXACT_CODE,
    "trade_plans[].target": NUMBER,
    "trade_plans[].target_basis": EXACT_CODE,
    "trade_plans[].reward_to_risk": NUMBER,
    "trade_plans[].is_valid": EXACT_BOOL,
    "trade_plans[].has_structural_stop": EXACT_BOOL,
    "decision.action": EXACT_CODE,
    "decision.reason": EXACT_CODE,
    "decision.direction": EXACT_INT,
    "decision.is_actionable": EXACT_BOOL,
}

#: Every list whose order is not part of the contract.
ORDER_FREE_LISTS: tuple[str, ...] = ("swings", "setups", "trade_plans")


class VectorError(Exception):
    """A sidecar is not something this harness can compare.

    Raised rather than reported as a parity failure, because "these two files do
    not describe the same contract" and "these two implementations disagree" are
    different findings and a caller must be able to tell them apart.
    """


class SchemaMismatch(VectorError):
    """The sidecar implements a different canonical form."""


class ScopeMismatch(VectorError):
    """The sidecar covers a strict subset of `SCOPE`."""


class CaseMismatch(VectorError):
    """The sidecar is for a different case."""


# --------------------------------------------------------------------------
# Building the vector
# --------------------------------------------------------------------------


def canonical_vector(
    bars: Sequence[Mapping[str, Any]] | BarSeries,
    last_closed: int,
    config: AnalyzerConfig | None = None,
) -> dict[str, Any]:
    """The canonical vector for one closed-bar analysis.

    Takes the same inputs as `Analyzer.analyze()` and reduces the result to
    `SCOPE`. The reduction is the whole point: nothing here is a decision about
    what matters, it is a projection of what was already computed, and the field
    list is `FIELD_CLASSES` rather than a judgement.
    """
    series = bars if isinstance(bars, BarSeries) else BarSeries(list(bars))
    cfg = config or AnalyzerConfig()
    result = Analyzer(cfg).analyze(series, last_closed=last_closed)

    atrs = calculate_atr_series(series[: result.last_closed_bar + 1], period=cfg.atr_period)
    atr = atrs[result.last_closed_bar] if result.last_closed_bar < len(atrs) else 0.0

    state = result.market_state
    return {
        "last_closed_bar": int(result.last_closed_bar),
        "bars_processed": int(result.bars_processed),
        "atr": float(atr),
        "market_state": {
            "valid": bool(state.get("valid", False)),
            "mode": str(state.get("mode", "UNKNOWN")),
            "direction": int(state.get("direction", 0)),
            "strength": float(state.get("strength", 0.0)),
        },
        "swings": _sort_order_free(
            [
                {
                    "bar_index": int(s["bar_index"]),
                    "confirmed_bar_index": int(s["confirmed_bar_index"]),
                    "price": float(s["price"]),
                    "direction": int(s["direction"]),
                }
                for s in result.swings
            ]
        ),
        "setups": _sort_order_free([_setup_entry(entry) for entry in result.setups]),
        "trade_plans": _sort_order_free([_plan_entry(plan) for plan in result.trade_plans]),
        "decision": {
            "action": str(result.decision.get("action", "NO_TRADE")),
            "reason": str(result.decision.get("reason", "")),
            "direction": int(result.decision.get("direction", 0)),
            "is_actionable": bool(result.decision.get("is_actionable", False)),
        },
    }


def _sort_order_free(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Sort list elements by the canonical JSON encoding of each one.

    The encoding is an implementation detail of *this* side, which is why the
    specification tells the other side it may emit any order: the harness re-sorts
    both. What is contractual is the result, not the procedure.

    Called from two places for two different reasons. `canonical_vector` calls it
    so the file a human reads has a stable order, and `flatten` calls it because
    it cannot trust that a sidecar from another implementation passed through the
    first.
    """
    return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=repr))


def _setup_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """One detected setup, reduced to the fields a port could plausibly differ on.

    `setup_type` is nullable because a payload is not required to carry one, and
    `CODE_OR_NULL` exists so "neither side had one" is distinguishable from "only
    one did".
    """
    raw = entry.get("setup_type")
    return {
        "detector": str(entry.get("detector", "")),
        "kind": str(entry.get("kind", "")),
        "setup_family": str(entry.get("setup_family", "")),
        "direction": int(entry.get("direction", 0)),
        "setup_type": None if raw is None else str(raw),
    }


def _plan_entry(plan: Mapping[str, Any]) -> dict[str, Any]:
    """One trade plan's geometry and the basis of each level.

    The bases are in scope because they are the difference between "the stop is
    at 104.10" and "the stop is at 104.10 because it came from a swing low". A
    port that computed the right number from the wrong level would be a claim
    this engine does not make, and it would be invisible without them.
    """
    return {
        "direction": int(plan.get("direction", 0)),
        "entry": float(plan.get("entry", 0.0)),
        "stop": float(plan.get("stop", 0.0)),
        "stop_basis": str(plan.get("stop_basis", "")),
        "target": float(plan.get("target", 0.0)),
        "target_basis": str(plan.get("target_basis", "")),
        "reward_to_risk": float(plan.get("reward_to_risk", 0.0)),
        "is_valid": bool(plan.get("is_valid", False)),
        "has_structural_stop": bool(plan.get("has_structural_stop", False)),
    }


# --------------------------------------------------------------------------
# The sidecar envelope
# --------------------------------------------------------------------------


def envelope(
    case_id: str,
    vector: Mapping[str, Any],
    producer: str,
    producer_version: str,
) -> dict[str, Any]:
    """Wrap a vector with the metadata a comparison needs to be meaningful."""
    return {
        "schema": SCHEMA_VERSION,
        "case_id": case_id,
        "producer": producer,
        "producer_version": producer_version,
        "scope": list(SCOPE),
        "vector": dict(vector),
    }


def dump(payload: Mapping[str, Any]) -> str:
    """The on-disk text form: sorted keys, two-space indent, trailing newline.

    Sorted keys and a fixed indent are not cosmetic. A parity sidecar is a file
    two implementations argue over, and a diff nobody can read is a diff nobody
    will read.
    """
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def load_sidecar(path: Path, *, case_id: str) -> dict[str, Any]:
    """Read and validate a sidecar, or raise `VectorError` saying why not.

    Four things are checked, in this order, because each is a different reason to
    refuse:

    1. the file parses as an object with the required envelope keys;
    2. `schema` is this harness's schema;
    3. `case_id` is the case being run;
    4. `scope` is not a strict subset of `SCOPE`.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VectorError(f"{path.name}: unreadable ({exc})") from exc
    if not isinstance(payload, dict):
        raise VectorError(f"{path.name}: top level is not an object")

    missing = [k for k in ("schema", "case_id", "producer", "scope", "vector") if k not in payload]
    if missing:
        raise VectorError(f"{path.name}: envelope is missing {missing}")

    if payload["schema"] != SCHEMA_VERSION:
        raise SchemaMismatch(
            f"{path.name}: schema {payload['schema']!r} is not {SCHEMA_VERSION!r}"
        )
    if payload["case_id"] != case_id:
        raise CaseMismatch(f"{path.name}: case_id {payload['case_id']!r} is not {case_id!r}")

    declared = payload["scope"]
    if not isinstance(declared, list) or set(declared) - set(SCOPE):
        raise ScopeMismatch(f"{path.name}: scope names fields outside {list(SCOPE)}")
    missing_scope = [group for group in SCOPE if group not in declared]
    if missing_scope:
        raise ScopeMismatch(f"{path.name}: scope omits {missing_scope}")
    if not isinstance(payload["vector"], dict):
        raise VectorError(f"{path.name}: vector is not an object")
    return payload


# --------------------------------------------------------------------------
# Flattening, so the comparator is a single walk
# --------------------------------------------------------------------------


def flatten(vector: Mapping[str, Any]) -> dict[str, tuple[str, Any]]:
    """`{"swings[3].price": (NUMBER, 104.1), ...}`.

    Flattening is what makes "a field the other side did not send" a *detectable*
    outcome rather than a silent skip: the two maps are walked key by key, so a
    missing key produces a difference with a path.

    It is also strict in the other direction. An **undeclared** key — at the top
    level, inside a group, or on a list element — is a `VectorError` rather than
    something quietly dropped. A sidecar carrying fields the contract does not
    describe is describing a different vector, and a harness that compared the
    parts it recognised would report agreement over a file it did not
    understand. A guessed comparison class is a comparison nobody chose.
    """
    flat: dict[str, tuple[str, Any]] = {}

    def put(path: str, value: Any) -> None:
        try:
            kind = FIELD_CLASSES[path]
        except KeyError as exc:
            raise VectorError(f"no comparison class declared for {path!r}") from exc
        flat[path] = (kind, value)

    _reject_undeclared(vector, set(SCOPE), "the vector")

    for name in ("last_closed_bar", "bars_processed", "atr"):
        put(name, vector.get(name))

    state = _require_mapping(vector, "market_state")
    _reject_undeclared(state, {"valid", "mode", "direction", "strength"}, "market_state")
    for name in ("valid", "mode", "direction", "strength"):
        put(f"market_state.{name}", state.get(name))

    for group in ORDER_FREE_LISTS:
        items = vector.get(group)
        if not isinstance(items, list):
            raise VectorError(f"{group} is not a list")
        put(f"{group}_count", len(items))
        declared = {leaf for leaf, _ in _leaves(group)}
        # Sorted here rather than trusted from the file, because the other side
        # may emit any order (§3.4 of the specification) and the harness is the
        # only thing that can put both sides in the same order. `flatten` is where
        # that has to happen: `canonical_vector` sorts for the benefit of a human
        # reading the file, and a sidecar from elsewhere will not have been
        # through it.
        for index, item in enumerate(_sort_order_free(items)):
            if not isinstance(item, dict):
                raise VectorError(f"{group}[{index}] is not an object")
            _reject_undeclared(item, declared, f"{group}[{index}]")
            for leaf, kind in _leaves(group):
                if leaf not in item:
                    raise VectorError(f"{group}[{index}] is missing {leaf!r}")
                flat[f"{group}[{index}].{leaf}"] = (kind, item[leaf])

    decision = _require_mapping(vector, "decision")
    _reject_undeclared(
        decision, {"action", "reason", "direction", "is_actionable"}, "decision"
    )
    for name in ("action", "reason", "direction", "is_actionable"):
        put(f"decision.{name}", decision.get(name))

    return flat


def _reject_undeclared(mapping: Mapping[str, Any], declared: set[str], where: str) -> None:
    extra = sorted(set(mapping) - declared)
    if extra:
        raise VectorError(f"{where} carries undeclared field(s) {extra}")


def _leaves(group: str) -> list[tuple[str, str]]:
    """The declared leaves of one list group, in declaration order.

    Derived from `FIELD_CLASSES` rather than listed again, so a leaf added to the
    contract cannot be forgotten here. `FIELD_CLASSES` preserves declaration
    order, so the resulting order is the order the contract was written in.
    """
    marker = f"{group}" + "[]" + "."
    return [
        (path[len(marker) :], kind)
        for path, kind in FIELD_CLASSES.items()
        if path.startswith(marker)
    ]


def _require_mapping(vector: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = vector.get(key)
    if not isinstance(value, dict):
        raise VectorError(f"{key} is not an object")
    return value


# --------------------------------------------------------------------------
# One number's worth of comparison
# --------------------------------------------------------------------------


def deviation(kind: str, reference: Any, candidate: Any) -> float | None:
    """The relative deviation for a `NUMBER` leaf, or `None` if not comparable.

    `None` means "this is not a tolerance question" — and the caller must then
    fall back to equality. Returning `None` rather than a large number keeps
    "compared exactly" and "compared within tolerance" from looking alike in the
    report, which is the distinction that makes the strict classes worth having.
    """
    if kind != NUMBER:
        return None
    if not _is_finite(reference) or not _is_finite(candidate):
        return None
    ref = float(reference)
    cand = float(candidate)
    if abs(ref) <= RELATIVE_TOLERANCE:
        return abs(cand - ref)
    return abs(cand - ref) / abs(ref)


def within_tolerance(kind: str, reference: Any, candidate: Any) -> bool:
    """Whether two leaves agree under their declared class."""
    if kind == CODE_OR_NULL:
        if reference is None or candidate is None:
            return reference is None and candidate is None
        return reference == candidate
    if kind in (EXACT_INT, EXACT_CODE, EXACT_BOOL):
        # `bool` is an `int` subclass, so a `True` would compare equal to `1`
        # without this. A direction of `1` and a flag of `true` are different
        # values that happen to share a representation.
        if isinstance(reference, bool) != isinstance(candidate, bool):
            return False
        return bool(reference == candidate)
    if kind == NUMBER:
        if not _is_finite(reference) or not _is_finite(candidate):
            # A NaN on either side is a failure, never a match. `nan != nan` is
            # true in every language, which is exactly why it must be handled
            # before the comparison rather than by it.
            return False
        observed = deviation(NUMBER, reference, candidate)
        if observed is None:
            return False
        if abs(float(reference)) <= RELATIVE_TOLERANCE:
            return observed <= ABSOLUTE_FLOOR
        return observed <= RELATIVE_TOLERANCE
    raise VectorError(f"unknown comparison class {kind!r}")


def _is_finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))
