# MQL5 build and run loop

The loop is scripted. **Use the script**, because every step of it has a trap that
a shell recipe hides, and two of the traps are silent:

```bat
python scripts/build_mql5.py --case parity_range_breakout_001
python -m tests.parity.runner
```

`scripts/build_mql5.py` is the whole loop -- compile, run, read back -- and it
writes a sidecar only from a real MQL5 run. There is no flag that makes one appear
without one.

## The terminal is run from a mirror, and that is the whole trick

The installed terminal is **never run directly**. The script copies it to a
writable mirror under the work directory and runs that with `/portable`. Two
independent reasons, and the first one is the expensive one:

- **A live instance swallows a batch run.** `terminal64.exe /config:...` against a
  data folder that already has an open instance does not start the tester. It
  produces no error, no log entry and no report: the run is silently a no-op, and
  the symptom is an absent sidecar, which looks like a broken EA. A developer
  machine with four terminals open is a normal machine, so the loop cannot depend
  on all of them being closed.
- **`C:\Program Files` is not writable without elevation**, so a `/portable` tree
  rooted at the install cannot be staged into. `mkdir` raises `PermissionError`,
  which says nothing about the tester and invites the wrong fix.

A directory copy sidesteps both. It is ~300 MB, copied once and reused.

The mirror needs two things from the data folder, and omitting either produces a
*confident* failure rather than an error:

- **`config/*`, copied into the directory's _contents_.** `accounts.dat` is what
  lets the tester agent authorise. The install already has a `Config` folder, so
  copying the data folder's `config` *onto* that path nests it one level deeper,
  the account is not found, and the terminal says
  `tester not started because the account is not specified`.
- **Cached history for the test symbol.** A portable tree starts with an empty
  `Bases`. The EA reads its bars from the case file, so history is not what the
  vector is made of -- but the tester still refuses to start on a symbol with no
  data in range. `--symbol` defaults to `XAUUSD` for that reason: it is the
  symbol the machine has cached. The symbol is irrelevant to the result.

The account is read out of the data folder's own `config/common.ini` rather than
hard-coded. A login baked into a build script is a login that is wrong on the
next machine, and the symptom is a permissions-looking failure.

## 1. Compile

Inside the mirror, which is an ordinary directory:

```bat
"%WORK%\terminal\MetaEditor64.exe" ^
    /compile:"%WORK%\terminal\MQL5\Experts\AlBrooks\ParityExporter.mq5" ^
    /log:"%WORK%\compile.log" ^
    /inc:"%WORK%\terminal\MQL5"
```

Takes a few seconds. Success looks like:

```text
Result: 0 errors, 0 warnings, 2419 ms elapsed
```

and the `.ex5` appears beside the source.

**Two things that cost time.**

- **MetaEditor will not compile into a portable tree.** It silently produces no
  log and no `.ex5` when the target is under an install folder, even with
  `/portable` and `/inc` supplied. The mirror is a plain directory copy, so it
  is not a "portable tree" in the sense that matters, and the compile works.
- **The EA must live in a subfolder**, because the config names it as
  `Expert=AlBrooks\Foo`, which means `MQL5\Experts\AlBrooks\Foo.ex5`. A file at
  `MQL5\Experts\Foo.mq5` is *not* found, and the tester says so:
  `Tester  Experts\AlBrooks\Foo.ex5 not found`.

## 2. Run headlessly

```ini
[Common]
Login=<account>
Server=<Broker-Server>
ProxyEnable=0

[Tester]
Login=<account>
Server=<Broker-Server>
Expert=AlBrooks\Foo
Symbol=XAUUSD
Period=H1
Model=0
FromDate=2024.01.02
ToDate=2024.01.05
Deposit=10000
UseLocal=1
ShutdownTerminal=1
Visual=0
```

```bat
"%WORK%\terminal\terminal64.exe" /portable /config:"%WORK%\parity_tester.ini"
```

**`Login` and `Server` must be in BOTH sections, and this is a real trap.**

| Where they are | Result |
|---|---|
| neither | `Tester  tester not started because the account is not specified` |
| `[Common]` only | terminal logs in, then `Tester  Core 1  tester agent authorization error` |
| **both** | `Tester  automatic testing started` then `last test passed with result "successfully finished"` |

`[Common]` is what logs the *terminal* in; `[Tester]` is what authorises the local
*agent*. Supplying only the first gets you a connected terminal and an agent that
cannot authorise -- which reads like a broker problem and is not.

## 3. Read what the EA wrote

MQL5 `FileOpen` inside a tester agent lands in the **agent's** sandbox, not the
terminal folder:

```text
<terminal root>\Tester\Agent-127.0.0.1-<port>\MQL5\Files\<file>
```

The port number is the agent's and can change.

**So the EA uses `FILE_COMMON`**, which resolves to the shared
`MetaQuotes\Terminal\Common\Files` outside every data folder. That is load-bearing
in both directions, and both halves were measured rather than assumed:

- The agent **wipes its own `MQL5\Files` on every startup**, so an input staged
  there before a run is gone by the time `OnInit` executes. The EA correctly
  reports it "cannot read" a file that is demonstrably sitting on disk.
- An *output* staged there is in the same position, and the sandbox does not
  exist until the terminal has run once, so a plain existence check reports "no
  sandbox" and the loop never converges.

`Common\Files` is shared across agents and survives, so it is the only place an
input or an output can be exchanged.

## Two more traps the script encodes

- **MetaEditor writes UTF-16 on some builds and UTF-8 on others**, so the BOM is
  what decides. Decoding the wrong one yields a log full of NULs and a "0 errors"
  that is never found, which reads as a compiler fault.
- **`FileReadString` consumes the newline and does not return it**, so naively
  concatenating the lines of a pretty-printed JSON file silently deletes every
  line break in it. The result still looks like JSON and parses as nothing, which
  is a miserable failure to diagnose. The newline is put back explicitly.

## Verification performed

A real build, on a real terminal, producing real sidecars for all three cases:

```text
MetaEditor:  Result: 0 errors, 0 warnings
Tester:      automatic testing started
Tester:      last test passed with result "successfully finished"
Parity:      status: AGREED -- All 3 case(s) agreed on every declared field
```

with a **worst relative deviation of `0.0`** on every `NUMBER` leaf of every case.
Not merely inside the `1e-9` tolerance: exactly zero, across `atr`, `swings`,
`market_state`, `setups`, `trade_plans` and `decision`.

## What is still not permitted

Producing a `tests/parity/mql5/*.mql5.json` by hand, or by any route that is not
an MQL5 build computing the vector from the case's bars. A file that is not
produced by a real MQL5 run must carry `"producer": "python"`, and the runner
refuses to count it as parity evidence. Writing one by hand to turn the harness
green would turn the Phase 20 harness into a decoration.

And note what an `AGREED` run is not: agreement on the supplied cases and the
declared scope, not a proof that the two implementations are equivalent, and not a
claim about the market. Nothing in this project has been validated against
outcomes.
