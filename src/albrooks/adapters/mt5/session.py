"""A stateful caller: the Phase 19 finding, closed.

## The finding

Phase 19 recorded, in `VALIDATION.md` §5.1 and in `golden_fm_001`, that the
fading-measured-move lifecycle is **unreachable through the pipeline**. The cause
is one line: `setups/registry.py` registers `create_setups`, which only *seeds* a
projection, and the function that advances the state machine,
`track_fading_measured_moves`, is never called by the engine. So a live consumer
sees `PROJECTED` with `age 0` forever, for a projection the market has already
touched, reached and rejected.

The recorded reason for not fixing it in Phase 19 was that fixing it means giving
a **stateless** detector contract a stateful responsibility, and that belongs with
a stateful caller. This module is that caller.

## The obvious fix is the wrong one, and this is why it is worth writing down

The natural thing for a class called `AnalysisSession` to do is keep the fade
setups in `self` and advance them one bar per call. That is an incremental state
machine, and it **breaks the closed-bar contract** — `RPC-1` of
`docs/algorithms/NON_REPAINT_CONTRACT.md`, the invariant the whole engine rests
on:

> The analysis for a given bar index is identical whether or not later bars exist.

A session that has already seen bars 21..40 and then answers for bar 20 holds
state derived from bars the caller has declared unavailable. That is
look-ahead wearing the costume of a convenience, and it is invisible: the numbers
would still look plausible. Worse, the answer for bar 20 would depend on *when*
you asked, which is precisely the property `RPC-15` exists to forbid.

So this session is stateful in one respect and only one: it holds **the previous
result**, and it re-derives the fade lifecycle from the frozen window on every
call. `track_fading_measured_moves` is deterministic given `(bars, last_closed)`,
so re-deriving gives the same answer a live run, a backtest and a fresh call would
all give — and it closes the Phase 19 finding without spending the contract to do
it.

The one thing the session does *not* re-derive, and cannot, is anything that needs
bars before the window it was given. A caller who wants a longer history asks for
a longer `count`; see §"Window" below.

## The window, and why the count is a floor and not a recommendation

ATR needs `atr_period` bars to settle, swings need `swing_k` on each side, and
`state_lookback` is 20 by default. Below roughly 60 bars several layers degrade
into reporting "nothing found" for reasons that are about the input rather than
the market — and the engine reports those through `warnings` rather than hiding
them, so the distinction survives.

`WINDOW_FLOOR` is the adapter's own floor, derived from the default config rather
than invented: `atr_period + 4 * swing_k + state_lookback` = 14 + 12 + 20 = 46,
rounded up to 60 so the market-state lookback is fully populated with room to
spare. It is a floor and not a recommendation because a caller trading M1 has a
different answer available for the same cost, and this module cannot know which
one they want.

## What this produces

`SessionResult` carries the `AnalysisResult` **and** the tracked fade setups, with
the pipeline's own reading alongside. Both, deliberately: the pipeline still says
`PROJECTED` because the registry is stateless and this is not its job, and hiding
that would make a reader believe the pipeline had changed. `SessionResult` says
which is which in a field, so a consumer can choose.

A fade is an *observation*, not a trade. `FADING_MEASURED_MOVE.md` is explicit
that the lifecycle produces no entry, stop or order, and nothing here turns one
into a signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from albrooks.adapters.mt5.errors import HistoryUnavailable
from albrooks.adapters.mt5.series import FreezeReport
from albrooks.core.bars import Bar, BarSeries
from albrooks.core.legs import build_legs_from_swings
from albrooks.core.swings import find_swings
from albrooks.engine.analyzer import Analyzer
from albrooks.engine.configuration import AnalyzerConfig
from albrooks.engine.state import AnalysisResult
from albrooks.price_action.bars import calculate_atr_series
from albrooks.setups.fading_measured_move import FadingSetup, track_fading_measured_moves

#: The fewest bars this session will ask for. Derived in the module docstring from
#: the default config: `atr_period + 4 * swing_k + state_lookback`, rounded up.
WINDOW_FLOOR = 60

#: Reported when a caller asks for fewer bars than the layers can use. Not a veto:
#: the analysis still runs and the engine's own warnings describe what degraded.
WINDOW_SHORT = "MT5_WINDOW_BELOW_FLOOR"


@dataclass(frozen=True, slots=True)
class SessionResult:
    """One bar's analysis, plus the fade lifecycle a live consumer needs.

    `analysis` is the pipeline's own result, unmodified. `fades` is the *tracked*
    lifecycle, which is the reading the Phase 19 finding said was unreachable. They
    are reported side by side rather than merged, because they answer different
    questions and a merged field could not say which one it was.
    """

    analysis: AnalysisResult
    #: `track_fading_measured_moves` at the same `last_closed`. The states here are
    #: the documented lifecycle; the pipeline's own `setups` still report
    #: `PROJECTED` because the registry is stateless, and that is stated rather
    #: than papered over.
    fades: tuple[FadingSetup, ...] = ()
    #: Which reading the caller is looking at, so neither can be mistaken for the
    #: other. `PIPELINE` is `analysis.setups`; `TRACKED` is `fades`.
    fade_source: str = "TRACKED"
    #: How the series was frozen. `None` when the caller supplied bars directly
    #: rather than through a feed, because there was then no forming bar to drop.
    freeze: FreezeReport | None = None
    warnings: tuple[str, ...] = field(default=())

    @property
    def last_closed(self) -> int:
        return self.analysis.last_closed_bar

    def active_fades(self) -> tuple[FadingSetup, ...]:
        """Fades still progressing — `POTENTIAL` / `DEVELOPING` / `CONFIRMED`."""
        return tuple(f for f in self.fades if f.is_active)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_closed_bar": self.last_closed,
            "fade_source": self.fade_source,
            "fades": [f.to_dict() for f in self.fades],
            "freeze": self.freeze.to_dict() if self.freeze is not None else None,
            "warnings": list(self.warnings),
            "analysis": self.analysis.to_dict(),
        }


class AnalysisSession:
    """A stateful caller for a live or repeated analysis.

    ```python
    feed = MT5Feed()
    feed.connect("EURUSD")
    session = AnalysisSession()
    for _ in range(10):
        frozen = feed.closed_bars("EURUSD", M15, 300)
        outcome = session.on_bars(frozen)
        print(outcome.last_closed, outcome.fades)
    ```

    The loop reads like a stateful machine and is not one: every call re-derives
    from the series it was handed. The state it holds is the previous result, kept
    so a caller can ask what changed — and nothing else, because accumulating more
    is what would break `RPC-1`.
    """

    def __init__(self, config: AnalyzerConfig | None = None) -> None:
        self.config = config or AnalyzerConfig()
        self._analyzer = Analyzer(self.config)
        #: The most recent result, and the one before it. Two slots rather than one
        #: so `changed_since_previous` has a predecessor to compare against without
        #: a `__setattr__` hook — which would be clever, surprising, and exactly
        #: the kind of machinery this project does not add for tidiness.
        self._previous: SessionResult | None = None
        self._prior: SessionResult | None = None

    # -- the two entry points -------------------------------------------

    def on_bars(
        self,
        bars: Sequence[Bar | dict[str, Any]] | BarSeries,
        *,
        symbol: str = "GENERIC",
        timeframe: str = "UNKNOWN",
        last_closed: int | None = None,
        freeze: FreezeReport | None = None,
    ) -> SessionResult:
        """Analyse a series the caller has already frozen.

        This is the path that takes test data, a backtest and a golden fixture, and
        it is the one the suite drives. `on_feed` is a convenience over it.
        """
        series = (
            bars
            if isinstance(bars, BarSeries)
            else BarSeries(list(bars), symbol=symbol, timeframe=timeframe)
        )
        closed = (len(series) - 1) if last_closed is None else min(last_closed, len(series) - 1)
        analysis = self._analyzer.analyze(
            series, symbol=series.symbol, timeframe=series.timeframe, last_closed=closed
        )
        fades = self._track(series, closed)

        warnings: list[str] = []
        if len(series) < WINDOW_FLOOR:
            warnings.append(WINDOW_SHORT)

        result = SessionResult(
            analysis=analysis,
            fades=tuple(fades),
            freeze=freeze,
            warnings=tuple(warnings),
        )
        self._prior, self._previous = self._previous, result
        return result

    def on_feed(
        self,
        feed: Any,
        symbol: str,
        timeframe: int,
        count: int,
        *,
        now: float | None = None,
        period_seconds: float | None = None,
    ) -> SessionResult:
        """Fetch, freeze, analyse — the whole live path in one call.

        `feed` is duck-typed on `closed_bars()` rather than imported as `MT5Feed`,
        for the same reason the core never imports the adapters: a caller with a
        recorded-bar source can pass that instead, and the session does not care
        where the bars came from.

        `now` and `period_seconds` are forwarded to the freeze rather than left to
        the feed's defaults. They are parameters because the freeze decides *which*
        bar is forming from the clock, and a caller replaying recorded data has no
        business letting the live clock decide it.

        A fetch that returns nothing raises `HistoryUnavailable` rather than
        returning an empty session. An empty series would reach the engine and come
        back as `NO_BARS` — a statement about the market, made because the
        *connection* failed.
        """
        frozen = feed.closed_bars(
            symbol, timeframe, count, period_seconds=period_seconds, now=now
        )
        if len(frozen.series) == 0:
            raise HistoryUnavailable(
                f"every one of {count} bars for {symbol!r} was still forming; "
                f"there is nothing closed to analyse yet"
            )
        return self.on_bars(frozen.series, freeze=frozen.freeze)

    # -- the lifecycle the pipeline cannot reach ------------------------

    def _track(self, series: BarSeries, closed: int) -> list[FadingSetup]:
        """Seed and advance the fade lifecycle over the frozen window.

        Every input is the window the caller gave, at the index they asked for, so
        the answer is a pure function of `(series, closed)` — the property that
        makes this safe to call from a loop. `swings` and `legs` are computed here
        for the same reason the pipeline computes them: the lifecycle needs the
        structures, and re-deriving them is cheaper than holding them across calls.
        """
        if closed < 0 or len(series) == 0:
            return []
        atrs = calculate_atr_series(series[: closed + 1], period=self.config.atr_period)
        atr = atrs[closed] if closed < len(atrs) else 0.0
        if atr <= 0:
            return []
        swings = find_swings(series, last_closed_idx=closed, k=self.config.swing_k)
        legs = build_legs_from_swings(swings)
        return track_fading_measured_moves(
            series,
            last_closed=closed,
            atr=atr,
            swings=swings,
            legs=legs,
            config=self.config,
        )

    # -- what changed ----------------------------------------------------

    @property
    def previous(self) -> SessionResult | None:
        """The last result, or `None` before the first call.

        Kept so a caller can diff two bars without holding both. It is the *only*
        state this class has, and the module docstring says why it is not more.
        """
        return self._previous

    def changed_since_previous(self) -> dict[str, Any]:
        """What moved between the last two calls, and what did not.

        A repaint is not "the wrong answer once" — `RPC-15` says it is "the answer
        changed after you had already seen it". So the useful question is not "what
        is the decision" but "what changed", and a caller watching a live series
        wants to know that the *decision* held while the *fade* advanced, or the
        reverse.

        `first_call` is reported rather than treated as a diff against nothing, so
        a caller that diffs before its second call is told it had no predecessor
        instead of being handed an empty change set that reads as "nothing moved".
        """
        current = self._previous
        previous = self._prior
        if current is None or previous is None:
            return {"first_call": True, "changed": False}

        was = previous.analysis.decision.get("action")
        now = current.analysis.decision.get("action")
        was_states = {f.id: f.state for f in previous.fades}
        now_states = {f.id: f.state for f in current.fades}
        return {
            "first_call": False,
            "changed": was != now or was_states != now_states,
            "decision": {"from": was, "to": now, "changed": was != now},
            "fades": {
                "from": was_states,
                "to": now_states,
                "changed": was_states != now_states,
            },
        }


__all__ = ["WINDOW_FLOOR", "WINDOW_SHORT", "AnalysisSession", "SessionResult"]
