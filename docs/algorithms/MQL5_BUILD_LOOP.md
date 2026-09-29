# MQL5 build and run loop

The exact commands that compile MQL5 and run it headlessly, verified end to end on
an Alpari MT5 installation. Written down because finding this took a full
investigation, and because a claim of "blocked on tooling" that was never checked
cost a whole phase's worth of false reporting.

## The two programs

Both live in the terminal's **program** folder, not its data folder:

```text
C:\Users\bagheri\AppData\Roaming\Alpari MT5_4\MetaEditor64.exe    compiler
C:\Users\bagheri\AppData\Roaming\Alpari MT5_4\terminal64.exe       terminal + tester
```

The data folder that terminal uses in normal mode is
`C:\Users\bagheri\AppData\Roaming\MetaQuotes\Terminal\03C7913CF64CF66F404A7F9AC18C91E0`,
which MetaTrader names in `terminal_info().data_path` and which the Python bindings
report. **Editing your own core then obviously fights the project rule that
`MetaTrader5` appears in exactly one module.**

## 1. Compile

```bat
set MT4_DATA=C:\Users\bagheri\AppData\Roaming\MetaQuotes\Terminal\03C7913CF64CF66F404A7F9AC18C91E0
set MT4_PROG=C:\Users\bagheri\AppData\Roaming\Alpari MT5_4

"%MT4_PROG%\MetaEditor64.exe" /compile:"%MT4_DATA%\MQL5\Experts\AlBrooks\Foo.mq5" ^
                              /log:"C:\...\foo.log" ^
                              /inc:"%MT4_DATA%\MQL5"
```

Takes about a second. Success looks like:

```text
Result: 0 errors, 0 warnings, 1049 ms elapsed
```

and the `.ex5` appears beside the source.

**Two things that cost time.**

- **MetaEditor will not compile into a portable tree.** It silently produces no
  log and no `.ex5` when the target is under the program folder, even with
  `/portable` and `/inc` supplied. Compile in the *data* folder and `Copy-Item`
  the resulting `.ex5` to wherever the runner needs it. The `.ex5` is just a
  binary; it does not need to be compiled where it will be run.
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
Symbol=EURUSD
Period=M15
Model=0
FromDate=2024.01.02
ToDate=2024.01.05
Deposit=10000
UseLocal=1
ShutdownTerminal=1
Visual=0
```

```bat
"%MT4_PROG%\terminal64.exe" /config:"C:\...\foo.ini"
```

**`Login` and `Server` must be in BOTH sections, and this is the whole trick.**

| Where they are | Result |
|---|---|
| neither | `Tester  tester not started because the account is not specified` |
| `[Common]` only | terminal logs in, then `Tester  Core 1  tester agent authorization error` |
| **both** | `Tester  automatic testing started` then `last test passed with result "successfully finished"` |

`[Common]` is what logs the *terminal* in; `[Tester]` is what authorises the local
*agent*. Supplying only the first gets you a connected terminal and an agent that
cannot authorise — which reads like a broker problem and is not.

### Use `/portable` so a running terminal does not block you

In normal mode the data folder is **locked** by any running instance of that
terminal, and a second launch exits silently with no log line. Add `/portable`:

```bat
"%MT4_PROG%\terminal64.exe" /portable /config:"C:\...\foo.ini"
```

Portable mode puts the data folder inside the program folder, so it is independent
of the terminals the user already has open. It is the same executable — it is a
mode, not a different install. The first launch re-downloads history (about a
minute for EURUSD) and compiles the bundled examples; subsequent runs are fast.

## 3. Read what the EA wrote

MQL5 `FileOpen` inside a tester agent lands in the **agent's** sandbox, not the
terminal folder:

```text
<program folder>\Tester\Agent-127.0.0.1-3001\MQL5\Files\<file>
```

The port number is the agent's and can change. Resolve it rather than hard-coding
it:

```python
from pathlib import Path

def agent_files_dir(program_folder: str) -> Path:
    agents = sorted((Path(program_folder) / "Tester").glob("Agent-*"))
    return max((a / "MQL5" / "Files" for a in agents if a.is_dir()), default=None)
```

## Verification performed

A throwaway EA that writes one line with `FileOpen`/`FileWrite` was compiled, run
headlessly, and the file read back from Python:

```text
MetaEditor:  Result: 0 errors, 0 warnings
Tester:      automatic testing started
Tester:      last test passed with result "successfully finished" in 0:00:00.602
File:        hello_from_mql5
```

So the loop is **compile, run, read back** and needs nothing further. Phase 21's
MQL5 port is unwritten, not blocked.

## What is still not permitted

Producing a `tests/parity/mql5/*.mql5.json` by hand, or by any route that is not
an MQL5 build computing the vector from the case's bars. A file that is not
produced by a real MQL5 run must carry `"producer": "python"`, and the runner
refuses to count it as parity evidence. Writing one by hand to turn the harness
green would turn the Phase 20 harness into a decoration.
