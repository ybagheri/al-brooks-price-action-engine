"""Aggregating evidence factors into one number, honestly.

## The number, and what it is not

`score()` reduces a bundle to a single value in 0..1. It is an **evidence
score**: the mean of the factors' weights. That is all it is.

It is **not** a probability, a win rate, an expected value, or a likelihood.
Nothing in this project has been calibrated against outcomes, so there is no
population of cases to compute a rate against. `docs/architecture/CONCEPT_TAXONOMY.md`
§5 classifies no value in this project as `STATISTICAL` for exactly this reason,
and §6 asks for "evidence score" rather than "confidence" in prose. `0.8` means
"the factors were, on average, at 0.8 of their own scales" — it does not mean the
reading is right 80% of the time.

## Why the mean is weighted per source, not per factor

A flat mean over all factors would let the source with the most factors dominate
the result. That is not a neutral choice: the pullback adapter emits one factor
per pullback while the reversal adapter emits one per satisfied leg, so a
four-leg reversal would outweigh a confirmed pullback on arithmetic alone.

`score()` therefore averages *within* each source first, then across sources, so
each contributing source gets an equal say. The within-source means are kept in
the result, because a caller that wants to know which source dragged the number
down needs to be able to see it.

## The properties that are asserted in the tests

1. **Reproducible.** The score is a pure function of the bundle's own factors and
   can never drift away from them, exactly as the measured-move `confidence`
   already guarantees for projections.
2. **Order-independent.** Factors are held in a frozen tuple and the arithmetic
   is a mean, so the result does not depend on the order they were collected in.
3. **No evidence, no score.** An empty bundle scores 0.0 and says so, rather
   than raising or reporting a confident default.
4. **Gaps are not interpolated.** A source contributing only unquantified
   assertions is reported as such, and never quietly promoted to a measurement.

## Banding is deliberately coarse

`band()` maps a score to `STRONG` / `MODERATE` / `WEAK` / `NONE` using
thresholds from `AnalyzerConfig`, because the project rule is that no threshold
is a literal buried in a detector (ARCHITECTURE.md §11). Three bands, not ten:
finer banding would imply a resolution these heuristics do not have, and a
caller who needs the number has it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from albrooks.engine.configuration import AnalyzerConfig
from albrooks.evaluation.evidence import EvidenceBundle

#: Bands, weakest-first. Deliberately coarse — see the module docstring.
BAND_NONE = "NONE"
BAND_WEAK = "WEAK"
BAND_MODERATE = "MODERATE"
BAND_STRONG = "STRONG"

#: Why a score carries a caveat, as a stable code rather than a sentence.
WARN_NO_EVIDENCE = "NO_EVIDENCE"
WARN_UNQUANTIFIED_ONLY = "UNQUANTIFIED_EVIDENCE_ONLY"
WARN_PARTIAL_QUANTIFIED = "PARTIALLY_QUANTIFIED_EVIDENCE"
WARN_SINGLE_SOURCE = "SINGLE_SOURCE_EVIDENCE"


@dataclass(frozen=True, slots=True)
class EvidenceScore:
    """A bundle's aggregate, with the breakdown that produced it."""

    #: The evidence score in 0..1. **Not** a probability.
    value: float = 0.0
    #: Which band `value` falls in.
    band: str = BAND_NONE
    #: Per-source means, in first-seen order. The reason `value` is not simply
    #: the mean of every factor.
    by_source: dict[str, float] = field(default_factory=dict)
    #: Share of factors that are measured rather than asserted.
    quantified_share: float = 0.0
    #: Caveat codes, stable and comparable.
    warnings: tuple[str, ...] = ()

    @property
    def is_usable(self) -> bool:
        """Whether there is any evidence here at all.

        A caller gating on a threshold should check this first: a bundle with no
        evidence scores 0.0, which would otherwise read as "weak" rather than
        "nothing was observed".
        """
        return bool(self.by_source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "band": self.band,
            "by_source": dict(self.by_source),
            "quantified_share": self.quantified_share,
            "warnings": list(self.warnings),
            # Recorded in the output so a consumer reading the number is told
            # what it is, rather than having to find this module to find out.
            "is_probability": False,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def score(bundle: EvidenceBundle, config: AnalyzerConfig | None = None) -> EvidenceScore:
    """Reduce a bundle to one evidence score, keeping the breakdown.

    Sources are weighted equally: each source's factors are averaged first, and
    those means are then averaged. A flat mean over all factors would let
    whichever source emits the most factors dominate, which is an artefact of
    how many fields each layer happens to expose rather than a statement about
    the market.
    """
    cfg = config or AnalyzerConfig()
    grouped = bundle.by_source()
    if not grouped:
        return EvidenceScore(
            value=0.0,
            band=BAND_NONE,
            by_source={},
            quantified_share=0.0,
            warnings=(WARN_NO_EVIDENCE,),
        )

    by_source = {
        name: _mean([f.weight for f in factors]) for name, factors in grouped.items()
    }
    value = _mean(list(by_source.values()))
    share = bundle.quantified_share

    return EvidenceScore(
        value=value,
        band=band(value, cfg),
        by_source=by_source,
        quantified_share=share,
        warnings=_warnings(bundle, share, len(grouped)),
    )


def _warnings(
    bundle: EvidenceBundle, share: float, source_count: int
) -> tuple[str, ...]:
    """Caveat codes describing how much of this evidence is measured."""
    if not bundle.factors:
        return (WARN_NO_EVIDENCE,)
    out: list[str] = []
    if share == 0.0:
        # Every factor is an assertion or a lifecycle position. A number built
        # entirely from those is not a measurement, and saying so is the whole
        # point of reporting it.
        out.append(WARN_UNQUANTIFIED_ONLY)
    elif share < 1.0:
        out.append(WARN_PARTIAL_QUANTIFIED)
    if source_count == 1:
        out.append(WARN_SINGLE_SOURCE)
    return tuple(out)


def band(value: float, config: AnalyzerConfig | None = None) -> str:
    """Map an evidence score to a coarse band.

    The thresholds come from `AnalyzerConfig` because ARCHITECTURE.md §11
    requires every heuristic threshold to be configurable rather than a literal
    inside a detector. An empty bundle is `NONE` rather than `WEAK`, so "nothing
    was observed" and "what was observed was weak" stay different statements.
    """
    cfg = config or AnalyzerConfig()
    if value <= 0.0:
        return BAND_NONE
    if value >= cfg.evidence_strong_band:
        return BAND_STRONG
    if value >= cfg.evidence_moderate_band:
        return BAND_MODERATE
    return BAND_WEAK


def measured_only(bundle: EvidenceBundle) -> EvidenceBundle:
    """The bundle with everything but its `MEASURED` factors removed.

    Provided because "what did we actually measure?" is the question a reader of
    a low score should be able to ask without rebuilding the filter themselves.
    A bundle with no measured factors comes back empty rather than raising, so
    the result is still a valid bundle that scores 0.0 with `NO_EVIDENCE`.
    """
    return EvidenceBundle(
        subject=bundle.subject,
        direction=bundle.direction,
        factors=tuple(f for f in bundle.factors if f.is_quantified),
        warnings=bundle.warnings,
    )


def compare(
    bundles: list[EvidenceBundle], config: AnalyzerConfig | None = None
) -> list[tuple[str, float]]:
    """Rank bundles by evidence score, for display only.

    Sorted by score, then by subject so the order is deterministic for equal
    scores. This is a **presentation** helper: ranking two different kinds of
    claim — a measured-move target and a reversal leg count — is a judgement
    this project has not earned, so nothing downstream may treat the order as a
    recommendation. `docs/algorithms/EVIDENCE_MODEL.md` §6 says the same.
    """
    scored = [(b.subject, score(b, config).value) for b in bundles]
    return sorted(scored, key=lambda pair: (-pair[1], pair[0]))
