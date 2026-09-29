"""Hand an analysis to a language model, without handing it a false claim.

Run it:

```bash
python examples/llm_analysis.py                    # built-in demo series
python examples/llm_analysis.py --bars bars.json   # your own OHLCV
python examples/llm_analysis.py --prompt            # the text form
```

## What this demonstrates, and why it is an example rather than a doc

The hard part of an LLM interface is not producing JSON. It is that the obvious
version of it **actively misleads**. `Analyzer.analyze()` gives you 53,495
characters for a 60-bar series and 88.9% of that is `bar_features` — 28 numeric
fields per bar. Hand that to a model and it has almost no attention left for the
decision.

Worse, hand a model the *unreduced* payload and it reads `evidence_score: 1.0` as
a certainty, because that is what a 1.0 means everywhere else. So this script
shows three things a consumer will not find in the docstrings:

1. `brief()` cuts the payload to about 3,000 characters and **says what it cut**.
2. No score leaves the process as a bare number. Each one is an object carrying
   `is_probability: false` and a sentence saying what it is.
3. The caveats travel *inside* the payload, and the instructions travel *after*
   it — a model reads the data first, so that is where the framing has to win.

## Try it and see the two failure modes

The demo series is a 60-bar ramp, so the analysis runs and finds structure. Two
experiments are worth doing by hand:

- **Delete the `--budget` argument's effect** by passing `--budget 1000000` and
  comparing sizes. The reduction is the whole design, and it is measurable.
- **Read `truncated`** after doing so. It names every section that was dropped
  and why. A reduction that did not report itself would be a quiet lie about
  what the reader is looking at.

## What this does not do

It makes no claim that a model will read the payload correctly, and it does not
evaluate any model. There is no model call here: the script produces the payload
and prints it, because the interesting and testable part is the *payload's shape*,
and adding an API call would make this example depend on a key, a network and a
model's mood.

**Nothing in the output is a probability, and nothing is advice.**
`docs/algorithms/VALIDATION.md` §9 lists what would be needed to change that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

# Running from a clone: `src/` is not installed, so make the import work without
# an editable install. A no-op when the package is installed properly.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from albrooks.core.bars import BarSeries  # noqa: E402
from albrooks.engine.analyzer import Analyzer  # noqa: E402
from albrooks.engine.configuration import AnalyzerConfig  # noqa: E402
from albrooks.serialization.json import (  # noqa: E402
    DEFAULT_BUDGET,
    brief,
    canonical,
    estimate_tokens,
    to_prompt,
)

#: A fixed epoch, so this script prints the same bytes every run. A demo whose
#: output changes is a demo you cannot screenshot or diff.
T0 = 1704067200.0


def demo_bars(count: int = 60) -> list[dict[str, float]]:
    """A rising series with pullbacks, so the engine finds real structure.

    Not random: a demo that produced `NO_TRADE` on every run would make the
    interesting part of the payload — the decision, the plan, the vetoes — look
    empty, and an empty payload demonstrates nothing.
    """
    bars: list[dict[str, float]] = []
    for i in range(count):
        # A slow uptrend with a shallow pullback every fifth bar, so swings,
        # legs and pullbacks all have something to work with.
        phase = i % 5
        drift = 0.30 * i
        pull = -0.45 * phase
        o = 100.0 + drift + pull
        c = o + 0.18
        bars.append(
            {
                "time": T0 + i * 900.0,
                "o": o,
                "h": max(o, c) + 0.22,
                "l": min(o, c) - 0.20,
                "c": c,
            }
        )
    return bars


def load_bars(path: Path) -> list[dict[str, float]]:
    """Read OHLCV from JSON, accepting the shapes a caller is likely to have.

    A list of bars, or `{"bars": [...]}`. Both `o/h/l/c` and `open/high/low/close`
    are accepted, because `Bar.from_dict` accepts both and a caller should not have
    to know which one this script prefers.
    """
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    raw = payload["bars"] if isinstance(payload, dict) else payload
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} has no non-empty 'bars' list")

    bars: list[dict[str, float]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"bar {index} is not an object")
        bars.append(
            {
                "time": float(row.get("time", T0 + index * 900.0)),
                "o": float(row.get("o", row.get("open", 0.0))),
                "h": float(row.get("h", row.get("high", 0.0))),
                "l": float(row.get("l", row.get("low", 0.0))),
                "c": float(row.get("c", row.get("close", 0.0))),
            }
        )
    return bars


def show_comparison(result: Any, payload: dict[str, Any], budget: int | None) -> None:
    """Print the reduction as a measurement, because that is the justification.

    The module exists to cut a payload an LLM would drown in, so a reader should
    see the number rather than take it on trust.
    """
    full = len(canonical(result))
    reduced = len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    share = 100.0 * (1.0 - reduced / full) if full else 0.0

    print("=" * 72)
    print("PAYLOAD SIZE")
    print("=" * 72)
    print(f"  canonical (everything)   {full:>8,} chars")
    print(f"  brief (LLM-facing)       {reduced:>8,} chars   "
          f"({share:.1f}% smaller)")
    print(f"  token estimate           {estimate_tokens(payload):>8,}      "
          f"(~4 chars/token, an estimate)")
    if budget is not None:
        print(f"  budget                   {budget:>8,} chars")

    dropped = payload["truncated"]["dropped"]
    print()
    if dropped:
        print(f"  dropped {len(dropped)} section(s), each with a reason:")
        for entry in dropped:
            print(f"    - {entry['section']} ({entry['items']} items): {entry['reason']}")
    else:
        print("  nothing was dropped")


def show_the_reading(payload: dict[str, Any]) -> None:
    """The parts a reader should look at, in the order a reader should look."""
    decision = payload["decision"]
    state = payload["market_state"]

    print()
    print("=" * 72)
    print("THE READING  (no figure below is a probability)")
    print("=" * 72)
    print(f"  {state['mode']}, direction {state['direction']}")
    strength = state.get("strength")
    if strength:
        print(f"  proxy strength {strength['value']}  -- {strength['means']}")

    print()
    print(f"  action      {decision['action']}")
    print(f"  reason      {decision['reason']}")
    if decision.get("subject"):
        print(f"  subject     {decision['subject']}")
    print(f"  actionable  {decision['is_actionable']}   "
          f"recommendation {decision['is_recommendation']}")
    if decision.get("evidence"):
        evidence = decision["evidence"]
        print(f"  evidence    {evidence['value']}  is_probability={evidence['is_probability']}")
    if decision.get("ranking_basis"):
        print("  ranked by   " + "; ".join(decision["ranking_basis"]))

    plan = payload.get("trade_plan")
    if plan:
        print()
        print("  plan        entry / stop / target, with the basis of each:")
        print(f"              {plan['entry']}  ({plan['entry_basis']})")
        print(f"              {plan['stop']}  ({plan['stop_basis']})")
        print(f"              {plan['target']}  ({plan['target_basis']})")
        print(f"              reward:risk {plan['reward_to_risk']}, "
              f"structural stop {plan['has_structural_stop']}")

    vetoes = decision.get("vetoes")
    if vetoes:
        print()
        print(f"  {len(vetoes)} veto(s) on the candidates that did not win:")
        for veto in vetoes[:4]:
            key = f"  [{veto['config_key']}]" if veto.get("config_key") else ""
            print(f"    {veto['code']} on {veto['subject']}{key}")
        if len(vetoes) > 4:
            print(f"    ... and {len(vetoes) - 4} more")


def show_why_it_is_shaped_this_way(payload: dict[str, Any]) -> None:
    """The three properties worth checking by eye, printed as they actually are."""
    print()
    print("=" * 72)
    print("WHY IT IS SHAPED THIS WAY")
    print("=" * 72)
    print("  1. No score is a bare number. Every one is an object carrying its")
    print("     own label, so there is nothing for a model to pattern-match:")
    for key in ("strength",):
        item = payload["market_state"].get(key)
        if item:
            print(f"       {key}: {json.dumps(item, ensure_ascii=False)[:96]}...")
    if "evidence" in payload["decision"]:
        print(f"       evidence: "
              f"{json.dumps(payload['decision']['evidence'], ensure_ascii=False)[:70]}...")

    print()
    print("  2. The refusals are enforced, not documented. `confidence`, `pnl`,")
    print("     `win_rate`, `expectancy` and `profit_factor` are refused on every")
    print("     call, at any depth, by a check in brief() itself.")

    print()
    print("  3. The caveats travel with the data, and are always present:")
    for caveat in payload["caveats"][:3]:
        print(f"       - {caveat[:88]}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--bars", type=Path, default=None,
                        help="JSON file of OHLCV bars; omit for the demo series")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                        help="character budget; 0 for no limit")
    parser.add_argument("--symbol", default="DEMO")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--config", type=Path, default=None,
                        help="JSON file of AnalyzerConfig overrides")
    parser.add_argument("--prompt", action="store_true",
                        help="print the model-facing text form and exit")
    parser.add_argument("--json", action="store_true",
                        help="print the brief as JSON and exit")
    args = parser.parse_args(argv)

    bars = load_bars(args.bars) if args.bars else demo_bars()
    config = AnalyzerConfig.from_dict(
        json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    )

    result = Analyzer(config).analyze(
        BarSeries(bars, symbol=args.symbol, timeframe=args.timeframe)
    )
    budget = None if args.budget == 0 else args.budget
    payload = brief(result, budget=budget)

    if args.prompt:
        print(to_prompt(result, budget=budget))
        return 0
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    print(f"albrooks LLM interface -- {args.symbol} {args.timeframe}, "
          f"{len(bars)} bars, last closed {result.last_closed_bar}")
    show_comparison(result, payload, budget)
    show_the_reading(payload)
    show_why_it_is_shaped_this_way(payload)

    print()
    print("=" * 72)
    print("WHAT THIS IS NOT")
    print("=" * 72)
    print("  No number above is a probability, a likelihood or a win rate. Nothing")
    print("  in this project has been validated against outcomes; see")
    print("  docs/algorithms/VALIDATION.md section 9 for what that would require.")
    print("  A BUY is a ranking under declared criteria, not advice, and no order,")
    print("  size or entry instruction is implied. Not financial advice.")
    print()
    print("  Next: --json for the raw brief, --prompt for the model-facing text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
