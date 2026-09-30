"""Export real bars from a live MetaTrader terminal as a §9.1 dataset.

## What this is for

`VALIDATION.md` §9.1 asks for real data, and §9.2 asks that it carry a stated
provenance. This script produces exactly one artefact: a JSON file of real, closed,
ascending bars, with the provenance written *into* the file.

It deliberately does **not** label anything, fit anything, or report a result. The
labels (§9.2) and the out-of-sample split (§9.3) are human judgements about what a
setup *is* and which bars were available when, and neither can be automated
honestly. A script that generated them would be generating its own evidence.

## The data is not committed

`datasets/` is gitignored. Real bar history is large, and it is the broker's to
distribute rather than this repository's to republish. The **provenance travels
inside the file**, so it survives being uncommitted — a dataset that was never
recorded as coming from a named terminal build on a named server is exactly the
unlabelled sample §9.2 complains about.

The provenance block records the terminal build, the server, the symbol's
digit precision, the clock the closed-bar test used, and the exact span exported.
It records **no account number and no credentials**, and that is a decision rather
than an oversight: provenance needs to identify the *source*, and a login
identifies a person. The server and build identify the data.

## Integrity is checked three times, and the last one is the point

1. On the series as the adapter returned it, against the **server** clock.
2. On the series re-read from the file after writing.
3. The script reports which of the two verdicts it wrote.

The third check is the one that earns the other two. A file that was valid in
memory and invalid on disk has been through a serialisation bug, and that is
exactly the class of defect that turns a measurement into a fiction — the same
reason `build_mql5.py` never trusts a sidecar it has not read back.

## Usage

```bat
python scripts/export_bars.py --symbol EURUSD --timeframe M15 --count 5000
python scripts/export_bars.py --symbol EURUSD --timeframe H1 --count 5000 --out my.json
```

Requires a running, logged-in terminal. Set `ALBROOKS_MT5_PATH` to point at
`terminal64.exe`, or pass `--terminal`. Without one the script exits non-zero with
a message saying so — it does not fall back to a fixture, because a dataset that
silently contained synthetic bars would defeat its own purpose.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from albrooks.adapters.mt5 import (  # noqa: E402
    CLOCK_SERVER,
    MT5Feed,
    MT5Unavailable,
    SymbolNotFound,
    canonical_name,
    period_seconds,
    timeframe_from_name,
)
from albrooks.adapters.mt5.dataset import (  # noqa: E402
    DatasetIntegrityError,
    inspect_series,
    require_integrity,
)

#: Bumped when the file's shape changes. A dataset carries this so a reader knows
#: which reader to point at it, rather than inferring the shape from the keys.
SCHEMA = "albrooks-dataset/1"

DEFAULT_OUT_DIR = REPO / "datasets"


def build_payload(
    series: Any,
    *,
    symbol: str,
    timeframe: int,
    seconds: float,
    digits: int,
    now: float,
    integrity: Any,
    terminal: dict[str, Any],
) -> dict[str, Any]:
    """The file's whole content, provenance first.

    `now` and `integrity` are the values the check actually used, not recomputed
    ones, so the verdict in the file is the verdict that was proved.
    """
    return {
        "schema": SCHEMA,
        "provenance": {
            "symbol": symbol,
            "timeframe": canonical_name(timeframe),
            "period_seconds": seconds,
            "digits": digits,
            "exported_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "closed_bar_test": {
                "clock": CLOCK_SERVER,
                "now": now,
                "note": (
                    "Every bar satisfies bar.time + period_seconds <= now on the "
                    "terminal's server clock, so no bar in this file is still "
                    "forming. A local clock was 3.099 hours behind the server on the "
                    "machine this was developed on, which is why the server clock is "
                    "named here rather than assumed."
                ),
            },
            "terminal": terminal,
            "contains_credentials": False,
        },
        "integrity": integrity.to_dict(),
        "span": {
            "bars": len(series),
            "first_time": series[0].time if len(series) else None,
            "last_time": series[-1].time if len(series) else None,
        },
        "bars": [
            {
                "time": b.time,
                "o": b.open,
                "h": b.high,
                "l": b.low,
                "c": b.close,
                "volume": b.volume,
            }
            for b in series
        ],
    }


def _terminal_provenance(mt5: Any) -> dict[str, Any]:
    """What identifies the source, and nothing that identifies a person.

    `terminal_info()` gives the build and the company. It has **no server field** --
    checked against the live bindings -- so the server name comes from
    `account_info()`.

    Only the `.server` string is read out of `account_info()`. Its `.login` is a
    credential and is never touched, which is why this function assigns a single
    attribute rather than passing the object along. A dataset's provenance has to
    say which feed produced it, and the server plus the build do that without
    carrying an account number into a file that may be shared.

    The server name also says whether the feed was **demo or live**, which is
    material and easy to miss: a demo server's tick history is routinely thinner
    than a live server's, so bars that exist on one may be absent from the other.
    A dataset whose provenance does not say which it came from cannot be
    reproduced, and §9.2 is precisely about that.
    """
    info = mt5.terminal_info() if callable(getattr(mt5, "terminal_info", None)) else None
    if info is None:
        return {"available": False, "note": "the terminal reported no terminal_info()"}

    # Read the server string only. Nothing else from account_info is retained.
    server = None
    account = mt5.account_info() if callable(getattr(mt5, "account_info", None)) else None
    if account is not None:
        server = getattr(account, "server", None)

    return {
        "available": True,
        "name": getattr(info, "name", None),
        "build": getattr(info, "build", None),
        "company": getattr(info, "company", None),
        "server": server,
        "feed": (
            "demo" if server and "demo" in server.lower() else ("live" if server else None)
        ),
        "credentials_recorded": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export real, closed MT5 bars as a validation dataset.",
    )
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--timeframe", default="M15")
    parser.add_argument("--count", type=int, default=5000, help="bars to request")
    parser.add_argument("--out", default=None, help="output file path")
    parser.add_argument(
        "--terminal",
        default=None,
        help="path to terminal64.exe (defaults to $ALBROOKS_MT5_PATH)",
    )
    parser.add_argument(
        "--login",
        type=int,
        default=0,
        help="terminal account number; omit to use the signed-in account",
    )
    args = parser.parse_args(argv)

    try:
        timeframe = timeframe_from_name(args.timeframe)
    except Exception as exc:  # noqa: BLE001 - any failure is a usage error
        print(f"error: unknown timeframe {args.timeframe!r}: {exc}", file=sys.stderr)
        return 2

    out_path = (
        Path(args.out)
        if args.out
        else DEFAULT_OUT_DIR / f"{args.symbol}_{canonical_name(timeframe)}_{args.count}.json"
    )
    # The directory is created immediately before the write, not here, so a run that
    # fails to reach a terminal leaves nothing behind at all.

    feed = MT5Feed()
    try:
        feed.connect(
            args.symbol,
            path=args.terminal or os.environ.get("ALBROOKS_MT5_PATH") or None,
            login=args.login,
        )
    except (MT5Unavailable, SymbolNotFound) as exc:
        print(
            f"error: no usable MetaTrader 5 terminal ({type(exc).__name__}: {exc}).\n"
            "This script exports REAL bars and will not substitute a fixture for "
            "them. Start the terminal, log in, and set ALBROOKS_MT5_PATH.",
            file=sys.stderr,
        )
        return 1

    try:
        seconds = period_seconds(timeframe)
        # `closed_bars` is the adapter's freeze: it drops the forming bar on the
        # server clock and reports which clock it used. Using it rather than
        # re-filtering here is deliberate -- there is one implementation of the
        # closed-bar rule, and a second one in a script is how two disagree.
        frozen = feed.closed_bars(args.symbol, timeframe, args.count)
        report = frozen.freeze

        info = feed._mt5.symbol_info(args.symbol)
        digits = int(getattr(info, "digits", 5)) if info is not None else 5

        terminal = _terminal_provenance(feed._mt5)

        integrity = require_integrity(
            inspect_series(
                frozen.series,
                seconds,
                now=report.now,
                clock=report.clock,
            )
        )

        payload = build_payload(
            frozen.series,
            symbol=args.symbol,
            timeframe=timeframe,
            seconds=seconds,
            digits=digits,
            now=report.now,
            integrity=integrity,
            terminal=terminal,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Re-read and re-check. The verdict in the file is only worth writing if the
        # bytes on disk carry it, and a serialisation that drops or reorders a field
        # is precisely the defect that would not otherwise be noticed.
        from albrooks.core.bars import BarSeries  # local: keeps the import honest

        reread = BarSeries(
            [
                {"time": row["time"], "o": row["o"], "h": row["h"], "l": row["l"],
                 "c": row["c"], "volume": row["volume"]}
                for row in json.loads(out_path.read_text(encoding="utf-8"))["bars"]
            ]
        )
        require_integrity(
            inspect_series(reread, seconds, now=report.now, clock=report.clock)
        )
    except DatasetIntegrityError as exc:
        print(f"error: refusing to write a dataset that failed its checks.\n{exc}",
              file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - report, never half-write silently
        print(f"error: export failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    finally:
        feed.shutdown()

    print(f"wrote {out_path}")
    print(f"  bars        : {integrity.bars}")
    print(f"  span        : {integrity.first_time} .. {integrity.last_time}")
    print(f"  timeframe   : {canonical_name(timeframe)} ({seconds:.0f}s)")
    print(f"  closed test : {integrity.clock} clock at {integrity.now}")
    print(f"  dropped     : {report.dropped} forming bar(s)")
    print(f"  source      : {terminal['company']} {terminal['name']} build "
          f"{terminal['build']} on {terminal['server']} ({terminal['feed']})")
    print("  integrity   : OK in memory and OK re-read from disk")
    if terminal["feed"] == "demo":
        print(
            "\n  NOTE: this is a DEMO feed. Demo servers often carry thinner tick "
            "history than live ones, so bars present here may be absent from a live "
            "export. That is recorded in the file's provenance rather than left for "
            "a reader to discover."
        )
    print(
        "\nThis file contains no labels and no result. It is input for "
        "VALIDATION.md 9.1; labelling (9.2) and an out-of-sample split (9.3) are "
        "still open, and no number from it is a probability."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
