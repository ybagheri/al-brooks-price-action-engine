"""The decision layer: one answer, and every step that produced it.

## This is where ranking lives

`ROADMAP.md` records that this project does not rank competing setups, and that
the comparison "belongs" here. So this module does rank — and the whole design
is about making that ranking **auditable** rather than authoritative.

The ranking criteria are declared, applied in one fixed order, and echoed in the
output (`ranking_basis`). Two candidates with identical evidence and identical
reward:risk are separated only by a name, so the result is reproducible.

**A ranking by declared criteria is not an edge.** Nothing in this project has
been validated against outcomes (`CONCEPT_TAXONOMY.md` §5), so `BUY` here means
"of the plans that passed every gate, this one had the most evidence behind it by
the criteria below" — not "this is more likely to work". There is no
`confidence` field, `to_dict()` carries `"is_probability": false`, and
`CONCEPT_TAXONOMY.md` §6's wording rule (evidence score, never confidence) is
why the gate is called `min_score` and not `min_confidence`.

## Four actions, and the difference between two of them

| Action | Meaning |
|---|---|
| `NO_TRADE` | The engine declines to answer. |
| `WAIT` | There *was* something, and a stated condition is not met. |
| `BUY` / `SELL` | A ranked candidate, with its plan and the full explanation. |

`NO_TRADE` covers disabled, un-analysable, and nothing-found. `WAIT` covers only
the case where a candidate existed and was gated.

`NO_TRADE` versus `WAIT` is a real distinction and not a formality: "I have
nothing to say" and "I have something and it is not good enough yet" call for
different behaviour from a caller, and collapsing them would make an empty result
look like a judgement. `enable_decision=False` is `NO_TRADE`, never `WAIT` and
never an inferred trade.

## The evidence scale, stated once

The evidence score is **0..1** (`EvidenceScore.value`). Two things in this
module speak a different scale and say so in the field name:

- `evidence_ppts` — the same number as percentage points, 0..100, because
  `conflict_ppts` is expressed in points.
- `min_score` — on the 0..1 scale. Its declared default was `40.0`, on a 0-100
  scale the Phase 13 model never had, which would have rejected every candidate
  including a perfect one. Corrected in this phase, when the key was first read.

## What this does not do

It does not size a position, choose an order type, or evaluate a session. It
does not infer a trade from structure alone: with no eligible candidate it says
`WAIT` and names the conditions that failed, rather than reaching for the best
available reading. And it does not compare plans across timeframes — that is
Phase 16, and until HTF bias exists a decision on one timeframe is a decision
without context, which is why the explanation says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from albrooks.core.bars import Bar, BarSeries
from albrooks.decision.veto import (
    Veto,
    is_blocked,
    summary,
    vetoes_for,
)
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.evaluation.evidence import (
    EvidenceBundle,
    EvidenceFactor,
    from_breakout,
    from_fading_measured_move,
    from_market_state,
    from_measured_move,
    from_pullback,
    from_reversal,
)
from albrooks.evaluation.scoring import EvidenceScore, score
from albrooks.setups.base import family_for
from albrooks.trade.plan import TradePlan, anatomy_for, build_trade_plan


class Action(str, Enum):
    """The four answers the specification names."""

    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    NO_TRADE = "NO_TRADE"

    def to_dict(self) -> str:
        return self.value


#: Reason codes. Stable and comparable, rather than sentences a caller has to
#: parse.
REASON_DISABLED = "DECISION_DISABLED"
REASON_NO_ANALYSIS = "NO_ANALYSIS"
REASON_NO_CANDIDATES = "NO_CANDIDATES"
REASON_ALL_VETOED = "ALL_CANDIDATES_VETOED"
REASON_CONFLICT = "EVIDENCE_CONFLICT"
REASON_RANKED = "RANKED_CANDIDATE"

#: The criteria, in the order they are applied. Echoed in every decision so a
#: reader never has to open this file to know why one plan beat another.
RANKING_BASIS: tuple[str, ...] = (
    "evidence_score (0..1, higher first)",
    "reward_to_risk (higher first)",
    "candidate_id (ascending, for reproducibility only)",
)

#: Which Phase 13 adapter normalises each family's payload.
#:
#: Living here rather than in `evaluation` because it is knowledge about the
#: *setup families*, not about the evidence model. A family with no adapter here
#: contributes no factors rather than a wrong number — and the `NO_OWN_EVIDENCE`
#: gate then refuses to rank the result, so a missing adapter is visible rather
#: than silently producing a context-only candidate.
#:
#: The `Callable` annotation is not decoration: the adapters take different
#: concrete types, so without it the value type is inferred as a union and the call
#: resolves to their intersection — `from_pullback`'s `dict[str, Any]`, which a
#: `Mapping` is not.
_EVIDENCE_ADAPTERS: dict[str, Callable[[Any], list[EvidenceFactor]]] = {
    "PULLBACK": from_pullback,
    "BREAKOUT": from_breakout,
    "MEASURED_MOVE": from_measured_move,
    "REVERSAL": from_reversal,
    "FADING_MEASURED_MOVE": from_fading_measured_move,
}

#: Sources that belong to the *market context* rather than to the setup. Context
#: is added to every bundle because it is part of what backs a candidate, and it
#: is identical for all of them — so on its own it says nothing about one.
CONTEXT_SOURCES: frozenset[str] = frozenset({"MARKET_STATE"})


def bundle_for(
    family: str, payload: Mapping[str, Any], market_state: Mapping[str, Any] | None = None
) -> EvidenceBundle:
    """The evidence behind one setup payload, normalised for the evidence model.

    Market-state evidence is added to **every** bundle rather than being a
    separate input, because context is part of what backs a candidate: the same
    pullback in a strong trend and the same pullback in a tight range are not the
    same claim, and a bundle that omitted the context would score them
    identically.
    """
    adapter = _EVIDENCE_ADAPTERS.get(family)
    factors: list[EvidenceFactor] = list(adapter(payload)) if adapter else []
    state = market_state or {}
    factors.extend(from_market_state(state))
    return EvidenceBundle(
        subject=f"{family}:{_payload_label(payload)}",
        direction=int(payload.get("direction", 0) or 0),
        factors=tuple(factors),
    )


def _payload_label(payload: Mapping[str, Any]) -> str:
    """A short, human-meaningful name for what the payload actually is.

    Read in order of specificity, because a measured move and a pullback both
    carry a `family` and mean different things by it. Falls back to `NONE` rather
    than inventing a name: a bundle whose subject says nothing is still a valid
    bundle, and its factors say what it is.
    """
    for key in ("setup_type", "state", "family", "pattern_type", "verdict"):
        value = payload.get(key)
        if value and value != "NONE":
            return str(value)
    return "NONE"


# --------------------------------------------------------------------------
# The candidate
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeCandidate:
    """A plan, the evidence behind it, and the score derived from that evidence.

    The three travel together because a plan on its own cannot be judged and the
    score on its own cannot be acted on. The score is computed **once, at
    construction**, so the number a gate reads and the number the decision reports
    cannot be two different calculations of the same bundle.
    """

    #: Unique within a run, deterministic, and never a market identifier:
    #: `"<detector>#<position>"`.
    candidate_id: str
    plan: TradePlan
    bundle: EvidenceBundle
    evidence: EvidenceScore

    @property
    def direction(self) -> int:
        return self.plan.direction

    @property
    def evidence_value(self) -> float:
        return self.evidence.value

    @property
    def evidence_ppts(self) -> float:
        """The same number as percentage points, 0..100."""
        return self.evidence.value * 100.0

    @property
    def factors(self) -> tuple[EvidenceFactor, ...]:
        return self.bundle.factors

    @property
    def has_own_evidence(self) -> bool:
        """Whether the bundle says anything about *this* setup.

        Market-state context is added to every bundle, so a candidate whose only
        factors are `MARKET_STATE` has observed nothing about the setup it is a
        candidate for. The score cannot express that — see
        `NO_OWN_EVIDENCE` — so it is a separate, explicit question.
        """
        return any(f.source not in CONTEXT_SOURCES for f in self.bundle.factors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "direction": self.direction,
            "evidence_ppts": self.evidence_ppts,
            "has_own_evidence": self.has_own_evidence,
            "plan": self.plan.to_dict(),
            "bundle": self.bundle.to_dict(),
            "evidence": self.evidence.to_dict(),
        }


def candidates_from_findings(
    findings: Sequence[Any],
    *,
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    atr: float,
    market_state: Mapping[str, Any] | None = None,
    config: AnalyzerConfig | None = None,
) -> list[TradeCandidate]:
    """One candidate per finding, in the order the findings arrived.

    The order is the caller's — the registry's registration order, or the
    pipeline's layer order. It is preserved into `candidate_id` and is the final
    tie-break in the ranking, so a run over the same findings always produces the
    same decision.
    """
    cfg = config or AnalyzerConfig()
    out: list[TradeCandidate] = []
    for position, finding in enumerate(findings):
        detector = str(getattr(finding, "detector", "") or "UNKNOWN")
        payload = getattr(finding, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        family = family_for(detector, str(getattr(finding, "kind", "") or ""))
        plan = build_trade_plan(
            detector,
            payload,
            bars=bars,
            bar_index=last_closed,
            atr=atr,
            anatomy=anatomy_for(family),
            config=cfg,
        )
        bundle = bundle_for(family, payload, market_state)
        out.append(
            TradeCandidate(
                candidate_id=f"{detector}#{position}",
                plan=plan,
                bundle=bundle,
                evidence=score(bundle, cfg),
            )
        )
    return out


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Decision:
    """One answer, with the evidence, the vetoes, and the criteria behind it.

    `explanation` is ordered prose a reader can follow top to bottom, and it is
    never a substitute for the fields: the fields are for machines, the
    explanation is for the person who has to decide whether to trust them.
    """

    action: str
    reason: str
    subject: str = ""
    direction: int = 0
    plan: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: tuple[str, ...] = ()
    vetoes: tuple[dict[str, Any], ...] = ()
    #: How many candidates were considered, eligible, and rejected. Also carries
    #: `blocking_summary`, a count per veto code, when candidates were gated.
    considered: dict[str, Any] = field(default_factory=dict)
    #: The criteria that chose `subject`, echoed so the answer is checkable.
    ranking_basis: tuple[str, ...] = RANKING_BASIS
    #: Both sides' strongest evidence, in percentage points, for a caller that
    #: wants the comparison without re-deriving it. Absent when one side had
    #: nothing eligible.
    sides: dict[str, float] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        """Whether this is a direction rather than an abstention.

        Deliberately about the **action**, not the geometry: a plan can be
        perfectly well formed and still not be something to act on, and a caller
        gating on `is_actionable` wants the second question answered.
        """
        return self.action in (Action.BUY.value, Action.SELL.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "subject": self.subject,
            "direction": self.direction,
            "plan": self.plan,
            "evidence": self.evidence,
            "explanation": list(self.explanation),
            "vetoes": list(self.vetoes),
            "considered": dict(self.considered),
            "ranking_basis": list(self.ranking_basis),
            "sides": dict(self.sides),
            "is_actionable": self.is_actionable,
            # Said in the output rather than left to the reader of this file, for
            # the same reason `EvidenceScore.to_dict()` carries it.
            "is_probability": False,
        }


def _abstain(
    action: str,
    reason: str,
    explanation: Sequence[str],
    considered: dict[str, Any],
    *,
    vetoes: Sequence[Veto] = (),
    sides: Mapping[str, float] | None = None,
) -> Decision:
    """Every answer that is not a ranked candidate, built the same way.

    The veto list travels with the abstention rather than only appearing in the
    prose: a caller told `ALL_CANDIDATES_VETOED` needs the per-candidate detail
    to act on it, and an explanation is not a queryable record.
    """
    return Decision(
        action=action,
        reason=reason,
        explanation=tuple(explanation),
        considered=dict(considered),
        vetoes=tuple(v.to_dict() for v in vetoes),
        sides=dict(sides or {}),
    )


def decide(
    candidates: Sequence[TradeCandidate],
    *,
    bars: Sequence[Bar | dict[str, Any]] | BarSeries,
    last_closed: int,
    atr: float,
    config: AnalyzerConfig | None = None,
) -> Decision:
    """Choose one answer from the candidates, and explain it.

    The order of the steps is the order of the explanation, and no step is skipped
    silently:

    1. `enable_decision` — off means `NO_TRADE` / `DECISION_DISABLED`.
    2. A volatility reference — without one no ATR-relative gate is evaluable, and
       a decision over ungated candidates would rest on unchecked numbers.
    3. Nothing found — `NO_TRADE` / `NO_CANDIDATES`.
    4. Vetoes — a candidate failing a blocking gate is excluded, and **all** of
       its failures are reported rather than only the first.
    5. Nothing survived — `WAIT` / `ALL_CANDIDATES_VETOED`, with a count per code
       and the per-candidate detail kept in `vetoes`.
    6. Conflict — if both directions have an eligible candidate and neither
       dominates by `conflict_ppts`, the reading is contested: `WAIT`.
    7. Rank the dominant side and report it, with the criteria in the output.

    Market state reaches this function through the candidates' bundles rather than
    as an argument of its own: a candidate without its context is not a candidate
    this module can judge, and a separate parameter would let the two disagree.
    """
    cfg = config or AnalyzerConfig()
    counted: dict[str, Any] = {"considered": len(candidates)}


    if not cfg.enable_decision:
        return _abstain(
            Action.NO_TRADE.value,
            REASON_DISABLED,
            [
                "the decision layer is disabled by enable_decision, so it "
                "declines to answer rather than inferring a trade",
                "structure, context and setup candidates are still reported; "
                "only the decision is withheld",
            ],
            counted,
        )

    if atr <= 0.0:
        return _abstain(
            Action.NO_TRADE.value,
            REASON_NO_ANALYSIS,
            [
                "there is no volatility reference, so no ATR-relative gate could "
                "be evaluated and a decision here would rest on unchecked numbers",
            ],
            counted,
        )

    if not candidates:
        return _abstain(
            Action.NO_TRADE.value,
            REASON_NO_CANDIDATES,
            ["no setup was found, so there is nothing to decide between"],
            counted,
        )

    series = bars if isinstance(bars, BarSeries) else BarSeries(bars)
    closed = min(last_closed, len(series) - 1) if len(series) else -1
    close = series[closed].close if 0 <= closed < len(series) else 0.0

    vetoes: list[Veto] = []
    eligible: list[TradeCandidate] = []
    for candidate in candidates:
        found = vetoes_for(candidate, close=close, atr=atr, config=cfg)
        vetoes.extend(found)
        if not is_blocked(found):
            eligible.append(candidate)

    counted["eligible"] = len(eligible)
    counted["rejected"] = len(candidates) - len(eligible)

    if not eligible:
        counted["blocking_summary"] = summary(vetoes)
        return _abstain(
            Action.WAIT.value,
            REASON_ALL_VETOED,
            [
                f"{len(candidates)} candidate plans were gated and none survived",
                _describe_vetoes(vetoes, cfg),
                "nothing is being ranked, because ranking the least bad of them "
                "would be a recommendation this layer has not earned",
            ],
            counted,
            vetoes=vetoes,
        )

    bull = [c for c in eligible if c.direction > 0]
    bear = [c for c in eligible if c.direction < 0]
    sides = {
        "bull_ppts": max((c.evidence_ppts for c in bull), default=0.0),
        "bear_ppts": max((c.evidence_ppts for c in bear), default=0.0),
    }
    contested = bool(bull) and bool(bear)
    gap = abs(sides["bull_ppts"] - sides["bear_ppts"])

    if contested and gap < cfg.conflict_ppts:
        return _abstain(
            Action.WAIT.value,
            REASON_CONFLICT,
            [
                "bull and bear readings are both eligible and neither dominates",
                f"strongest bull evidence {sides['bull_ppts']:.2f} ppts against "
                f"{sides['bear_ppts']:.2f} ppts on the bear side, a gap of "
                f"{gap:.2f} below the conflict_ppts limit {cfg.conflict_ppts:.2f}",
                "a conflict this small is a disagreement, not a reading",
            ],
            counted,
            vetoes=vetoes,
            sides=sides,
        )

    pool = bull if sides["bull_ppts"] >= sides["bear_ppts"] else bear
    if not pool:
        # Unreachable while `NO_DIRECTION` is a blocking gate, which is the right
        # place for it. Kept so a future change to the gates degrades into an
        # abstention rather than an IndexError.
        return _abstain(
            Action.NO_TRADE.value,
            REASON_NO_CANDIDATES,
            ["every eligible candidate was directionless, so none can be ranked"],
            counted,
            vetoes=vetoes,
            sides=sides,
        )
    winner = sorted(
        pool,
        key=lambda c: (-c.evidence_value, -c.plan.reward_to_risk, c.candidate_id),
    )[0]

    explanation = [
        f"{len(candidates)} candidate plans were gated and {len(eligible)} "
        f"survived every gate",
        f"strongest bull evidence {sides['bull_ppts']:.2f} ppts, strongest bear "
        f"evidence {sides['bear_ppts']:.2f} ppts",
    ]
    if contested:
        explanation.append(
            f"a gap of {gap:.2f} ppts is past the conflict_ppts limit "
            f"{cfg.conflict_ppts:.2f}, so the two sides are not in conflict"
        )
    explanation.extend(
        [
            f"selected {winner.candidate_id} on the declared criteria: evidence "
            f"score {winner.evidence_value:.4f} ({winner.evidence.band}), "
            f"reward:risk {winner.plan.reward_to_risk:.4f}",
            "ranking is by declared criteria only, and none of them has been "
            "validated against outcomes; this is a comparison, not an edge",
            "the decision is on one timeframe with no higher-timeframe bias "
            "applied, which Phase 16 owns",
        ]
    )

    return Decision(
        action=Action.BUY.value if winner.direction > 0 else Action.SELL.value,
        reason=REASON_RANKED,
        subject=winner.candidate_id,
        direction=winner.direction,
        plan=winner.plan.to_dict(),
        evidence=winner.evidence.to_dict() | {"ppts": winner.evidence_ppts},
        explanation=tuple(explanation),
        vetoes=tuple(v.to_dict() for v in vetoes),
        considered=counted,
        sides=sides,
    )


def _describe_vetoes(vetoes: Sequence[Veto], cfg: AnalyzerConfig) -> str:
    """The gates that fired, with the limits, in one sentence.

    Named rather than counted, because "three candidates were rejected" tells a
    reader nothing about whether the thresholds are set sensibly.
    """
    if not vetoes:
        return "no gate was recorded, which is itself worth reporting"
    parts: list[str] = []
    for code, count in sorted(summary(vetoes).items()):
        parts.append(f"{code} on {count} candidate(s)")
    tuning = ", ".join(
        f"{key}={getattr(cfg, key)}" for key in _TUNED_KEYS
    )
    return "gates that fired — " + "; ".join(parts) + f". Current limits: {tuning}."


#: The config keys a vetoed decision names, so a reader who disagrees with the
#: outcome sees which knob to turn rather than having to look up six.
_TUNED_KEYS: tuple[str, ...] = (
    "min_score",
    "min_rr",
    "max_late_atr",
    "max_failed_attempts",
)
