"""Structural vetoes: what disqualifies a candidate *before* anything is ranked.

## Why a separate module

A veto is a statement about a **single** candidate: this plan is not eligible,
and here is the condition it failed. It is not a comparison, and it is not a
ranking. Keeping it apart from `decision/engine.py` makes the boundary
mechanical — a veto cannot mention another candidate, so a veto list can never
become a hidden ranking.

## Blocking versus advisory

Every veto carries a `blocking` flag, and the split is the honest part:

| | Meaning |
|---|---|
| `blocking=True` | the candidate is **not eligible** and is excluded from ranking |
| `blocking=False` | the condition was noticed and reported; the candidate still competes |

A `blocking=False` veto is not a softer opinion, it is a fact the reader would
otherwise have to go looking for. `VOLATILITY_STOP_ONLY` is the clearest case: a
plan whose stop was invented from an ATR multiple is materially weaker than one
placed behind a swing low, and that is worth saying while the candidate is still
in the running — without pretending the decision engine has earned the authority
to exclude it.

## Every blocking veto names its threshold

`Veto.detail` always states the number and the limit it was compared against, so
a reader can check the comparison rather than trust the verdict. A veto that only
said `EVIDENCE_TOO_WEAK` would be unfalsifiable.

## What the gates are, and are not

Six of the seven blocking gates read a value from `AnalyzerConfig`, and every one
of them is a **chosen threshold on a transparent number** — a `HEURISTIC` in
`docs/architecture/CONCEPT_TAXONOMY.md` §2. None is calibrated, because nothing
in this project has been validated against outcomes. Setting `min_rr` to 3.0
does not make a 3.1 plan better; it makes fewer plans eligible.

The seventh, `INVALID_GEOMETRY`, is different in kind and carries no threshold: a
plan whose stop is not on the protective side of its entry is not a weak trade,
it is an arithmetically broken one, and `TradePlan` has already said so.

`AGAINST_HIGHER_TIMEFRAME` is the odd one out in a different way: it is not
raised by a gate in this module but by `albrooks.engine.pipeline`, because it is
the only condition whose evidence comes from a **different series**. It is
declared here so that `KNOWN_VETOES` covers every code a decision can carry, and
so a consumer iterating a decision's vetoes finds one list rather than two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from albrooks.trade.plan import WARN_TERMINAL_SETUP, TradePlan

# --------------------------------------------------------------------------
# Codes
# --------------------------------------------------------------------------

#: The setup named no direction, so there is nothing to rank it as.
VETO_NO_DIRECTION = "NO_DIRECTION"
#: The bundle holds no evidence about the setup itself — only shared market
#: context, which every candidate has and which therefore says nothing about this
#: one. See the note on `NO_OWN_EVIDENCE` below.
VETO_NO_OWN_EVIDENCE = "NO_OWN_EVIDENCE"
#: The plan's own geometry is broken, so there is no trade to gate.
VETO_INVALID_GEOMETRY = "INVALID_GEOMETRY"
#: The underlying setup reached a terminal negative state.
VETO_TERMINAL_SETUP = "TERMINAL_SETUP"
#: No volatility reference, so no ATR-relative gate can be evaluated.
VETO_NO_ATR = "NO_ATR"
#: The evidence score is below `min_score`.
VETO_EVIDENCE_TOO_WEAK = "EVIDENCE_TOO_WEAK"
#: reward:risk is below `min_rr`.
VETO_RISK_REWARD_TOO_LOW = "RISK_REWARD_TOO_LOW"
#: Price has moved further than `max_late_atr` ATR from the plan's entry.
VETO_TRADE_IS_LATE = "TRADE_IS_LATE"
#: More than `max_failed_attempts` adverse observations stand against it.
VETO_TOO_MANY_FAILED_ATTEMPTS = "TOO_MANY_FAILED_ATTEMPTS"
#: The higher timeframe reads against this candidate. Raised by the multi-timeframe
#: pipeline rather than by a single-timeframe gate, and the only veto whose
#: evidence comes from a *different* series — see `engine/pipeline.py`.
VETO_AGAINST_HIGHER_TIMEFRAME = "AGAINST_HIGHER_TIMEFRAME"
#: Advisory — the stop is a volatility multiple rather than a level the market
#: produced. Never blocking; see the module docstring.
VETO_VOLATILITY_STOP_ONLY = "VOLATILITY_STOP_ONLY"

#: Every veto code this module can produce. A test asserts the module and the
#: constants agree, so a new gate cannot be added without being declared.
KNOWN_VETOES: frozenset[str] = frozenset(
    {
        VETO_NO_DIRECTION,
        VETO_NO_OWN_EVIDENCE,
        VETO_INVALID_GEOMETRY,
        VETO_TERMINAL_SETUP,
        VETO_NO_ATR,
        VETO_EVIDENCE_TOO_WEAK,
        VETO_RISK_REWARD_TOO_LOW,
        VETO_TRADE_IS_LATE,
        VETO_TOO_MANY_FAILED_ATTEMPTS,
        VETO_AGAINST_HIGHER_TIMEFRAME,
        VETO_VOLATILITY_STOP_ONLY,
    }
)

#: Evidence codes that count as an adverse observation, i.e. a failed attempt.
#:
#: The list is deliberately short and deliberately named. These are the only
#: negative observations the Phase 13 adapters emit: a breakout's own two trap
#: flags. An `INVALIDATED` pullback is *excluded* by its adapter rather than
#: scored, so it never reaches a count here — which is a real limitation of the
#: count, recorded in `docs/algorithms/DECISION_ENGINE.md` §5 rather than papered
#: over by inventing a wider list.
ADVERSE_EVIDENCE_CODES: frozenset[str] = frozenset(
    {
        "BREAKOUT_TRAP",
        "SECOND_LEG_TRAP",
    }
)


# --------------------------------------------------------------------------
# The veto
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Veto:
    """One condition a candidate failed, with the comparison that failed it."""

    code: str
    #: Which candidate it applies to, so a list of vetoes is readable.
    subject: str
    #: The comparison in words, always including both numbers.
    detail: str
    blocking: bool = True
    #: The config key that set the limit, or `""` for a gate with no threshold.
    config_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "subject": self.subject,
            "detail": self.detail,
            "blocking": self.blocking,
            "config_key": self.config_key,
        }


def blocking_codes(vetoes: Iterable[Veto]) -> list[str]:
    """The blocking codes, in the order they were produced."""
    return [v.code for v in vetoes if v.blocking]


def is_blocked(vetoes: Iterable[Veto]) -> bool:
    return any(v.blocking for v in vetoes)


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


def _direction_veto(plan: TradePlan) -> Veto | None:
    """A plan with no direction cannot be ranked as a buy or a sell.

    Blocked here rather than handled in `decide()` so the invariant "every
    eligible candidate has a direction" is a property of the gates, which is one
    place a reader can check, rather than a branch in the ranking code.
    """
    if plan.direction != 0:
        return None
    return Veto(
        code=VETO_NO_DIRECTION,
        subject=plan.subject,
        detail=(
            "the setup named no direction, so the plan is neither a buy nor a "
            "sell and cannot be ranked"
        ),
    )


def _own_evidence_veto(candidate: Any) -> Veto | None:
    """Nothing was observed about this setup, only the shared context.

    `score()` averages **within** each source and then across sources, so a bundle
    with a single source scores that source's value outright. A bundle holding
    only `MARKET_STATE` — which is added to *every* candidate, and is identical for
    all of them — therefore scores at the market state's value with no penalty for
    having said nothing about the setup.

    That produced a real inversion when the pipeline started reading the registry:
    a fading measured move, whose adapter did not exist, scored 100 ppts on market
    context alone and outranked a measured move with measured factors behind it,
    then manufactured an `EVIDENCE_CONFLICT` against the real read. The adapter is
    fixed too; this gate is the structural half, so the same inversion cannot come
    back through a family nobody wrote an adapter for.
    """
    if candidate.has_own_evidence:
        return None
    return Veto(
        code=VETO_NO_OWN_EVIDENCE,
        subject=candidate.plan.subject,
        detail=(
            "the only factors behind this candidate are shared market context, "
            "which every candidate has and which says nothing about this setup, so "
            "there is no reading of this setup to act on"
        ),
    )


def _geometry_veto(plan: TradePlan) -> Veto | None:
    if plan.is_valid:
        return None
    return Veto(
        code=VETO_INVALID_GEOMETRY,
        subject=plan.subject,
        detail=(
            "the plan's levels are not geometrically consistent, so there is no "
            "trade to gate ("
            + ", ".join(plan.issues)
            + ")"
        ),
    )


def _terminal_veto(plan: TradePlan) -> Veto | None:
    if WARN_TERMINAL_SETUP not in plan.warnings:
        return None
    return Veto(
        code=VETO_TERMINAL_SETUP,
        subject=plan.subject,
        detail=(
            "the setup behind the plan reached a terminal negative state, so "
            "its geometry is coherent but the reading behind it is not"
        ),
    )


def _atr_veto(plan: TradePlan, atr: float) -> Veto | None:
    if atr > 0.0:
        return None
    return Veto(
        code=VETO_NO_ATR,
        subject=plan.subject,
        detail=(
            "there is no volatility reference, so no ATR-relative gate can be "
            "evaluated and none of them was checked"
        ),
    )


def _score_veto(plan: TradePlan, value: float, min_score: float) -> Veto | None:
    if value >= min_score:
        return None
    return Veto(
        code=VETO_EVIDENCE_TOO_WEAK,
        subject=plan.subject,
        detail=(
            f"evidence score {value:.4f} is below the min_score limit "
            f"{min_score:.4f}"
        ),
        config_key="min_score",
    )


def _risk_reward_veto(plan: TradePlan, min_rr: float) -> Veto | None:
    if plan.reward_to_risk >= min_rr:
        return None
    return Veto(
        code=VETO_RISK_REWARD_TOO_LOW,
        subject=plan.subject,
        detail=(
            f"reward:risk {plan.reward_to_risk:.4f} is below the min_rr limit "
            f"{min_rr:.4f}"
        ),
        config_key="min_rr",
    )


def _late_veto(plan: TradePlan, close: float, atr: float, max_late_atr: float) -> Veto | None:
    """Is the plan stale?

    The comparison is the distance from the plan's entry to where price is now,
    in ATR. It says the plan is **out of date**, not that it is wrong: a pullback
    whose reference entry is half an ATR behind the market can still work, it just
    is not the entry the plan described.
    """
    if atr <= 0.0 or plan.entry <= 0.0:
        return None
    drift = abs(close - plan.entry) / atr
    if drift <= max_late_atr:
        return None
    return Veto(
        code=VETO_TRADE_IS_LATE,
        subject=plan.subject,
        detail=(
            f"price has moved {drift:.4f} ATR from the plan's entry, past the "
            f"max_late_atr limit {max_late_atr:.4f}"
        ),
        config_key="max_late_atr",
    )


def _failed_attempts_veto(
    plan: TradePlan, factors: Iterable[Any], limit: int
) -> Veto | None:
    """Veto on the count of adverse observations standing against a candidate.

    The count comes from two sources and the detail lists them, because a count
    with no stated basis is a number nobody can argue with: the plan's own
    terminal flag, plus every evidence factor whose code is declared adverse.
    """
    codes = [f.code for f in factors if f.code in ADVERSE_EVIDENCE_CODES]
    if WARN_TERMINAL_SETUP in plan.warnings:
        codes.append(VETO_TERMINAL_SETUP)
    if len(codes) <= limit:
        return None
    return Veto(
        code=VETO_TOO_MANY_FAILED_ATTEMPTS,
        subject=plan.subject,
        detail=(
            f"{len(codes)} adverse observations stand against this candidate "
            f"({', '.join(codes)}), past the max_failed_attempts limit {limit}"
        ),
        config_key="max_failed_attempts",
    )


def _volatility_stop_veto(plan: TradePlan) -> Veto | None:
    """Advisory. See the module docstring: noticed, not excluded."""
    if plan.has_structural_stop:
        return None
    return Veto(
        code=VETO_VOLATILITY_STOP_ONLY,
        subject=plan.subject,
        detail=(
            "the stop is an ATR fallback rather than a level the market produced, "
            "so the plan is geometrically valid and structurally empty"
        ),
        blocking=False,
    )


def vetoes_for(
    candidate: Any,
    *,
    close: float,
    atr: float,
    config: Any,
) -> list[Veto]:
    """Every gate for one candidate, blocking and advisory, in a fixed order.

    `close` is the close of the bar the decision is being made on. Gates are
    evaluated in the order below and **no gate is short-circuited**: a candidate
    that fails two of them reports both, because a reader fixing one condition
    should not have to re-run to discover the second.

    The arguments are untyped beyond the first so that `decision.engine` can pass
    its own `TradeCandidate` without this module importing it, and so that a caller
    with a bare `TradePlan` plus a bundle is equally welcome.
    """
    plan: TradePlan = candidate.plan
    factors = tuple(getattr(candidate, "factors", ()))
    value = float(getattr(candidate, "evidence_value", 0.0))

    gates: list[Veto | None] = [
        _direction_veto(plan),
        _own_evidence_veto(candidate),
        _geometry_veto(plan),
        _terminal_veto(plan),
        _atr_veto(plan, atr),
        _score_veto(plan, value, config.min_score),
        _risk_reward_veto(plan, config.min_rr),
        _late_veto(plan, close, atr, config.max_late_atr),
        _failed_attempts_veto(plan, factors, config.max_failed_attempts),
    ]
    out = [g for g in gates if g is not None]
    advisory = _volatility_stop_veto(plan)
    if advisory is not None:
        out.append(advisory)
    return out


def summary(vetoes: Iterable[Veto]) -> dict[str, int]:
    """How many candidates each code was vetoed for.

    A count rather than a "most important" veto, because picking the most frequent
    one would be a judgement this layer has not earned and would hide the others.
    """
    out: dict[str, int] = {}
    for veto in vetoes:
        if veto.blocking:
            out[veto.code] = out.get(veto.code, 0) + 1
    return out
