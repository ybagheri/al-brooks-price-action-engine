"""Compile, run and read back the MQL5 parity exporter.

    python scripts/build_mql5.py --case parity_range_breakout_001

## What this does, and why it is a script rather than a shell recipe

The loop is compile -> run -> read back, and every step has a trap that a
recipe hides:

- **A live terminal swallows a batch run.** Launching `terminal64.exe
  /config:...` while an instance is already open on that data folder does
  not start the tester and does not report an error: the new process hands
  over and the tester simply never runs, so the failure is an absent file
  and nothing else. This is why the terminal is run out of a **mirror**
  rather than the installed one.
- **`Program Files` is not writable without elevation**, so a portable
  tree rooted at the install directory cannot be staged into, and the
  `.ex5` cannot be copied there. The mirror is a plain directory copy.
- **A portable terminal keeps its config in `<root>/config`**, and the
  install already has a `Config` directory -- so copying the data folder's
  config *onto* that path nests it one level down, the account is silently
  not found, and the tester reports "the account is not specified". The
  copy therefore targets the directory's *contents*.
- **MetaEditor will not compile into a portable tree.** No log and no
  `.ex5`, even with `/portable`. Compiling inside the mirror sidesteps it
  because the mirror is an ordinary directory.
- **The EA must live in a subfolder.** `Expert=AlBrooks\\Foo` means
  `MQL5/Experts/AlBrooks/Foo.ex5`. A file at `MQL5/Experts/Foo.mq5` is
  reported as *not found*, which reads like a build failure.
- **`Login` and `Server` must be in BOTH `[Common]` and `[Tester]`.** Only
  `[Common]` logs the terminal in, leaving the local agent unauthorised --
  which looks like a broker problem and is not.
- **A tester agent's `FileOpen` lands in the agent sandbox**, not the
  terminal data folder, and the port number varies. So `FILE_COMMON` is the
  only place an input or an output can be exchanged.
- **The agent sandbox is wiped on every agent startup**, which is the
  other half of why `FILE_COMMON` is used.

## The line this script will not cross

It writes a sidecar only from a real MQL5 run. There is no fallback that copies
the Python reference, and no flag to make one appear. A file in
`tests/parity/mql5/` that this script did not produce is a fabrication, and it
would be worse than having no MQL5 code at all: the harness would report an
agreement it never measured.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Verified working locations. Overridable, because a hard-coded path in a build
# script is a path that will be wrong on the next machine -- and on the next
# machine, the account number is wrong too, which is why it is a flag and not a
# second hard-coded constant. `--login`/`--server` default to empty, and an
# empty value simply omits the key, leaving the terminal to use the account it
# is already signed in to.
DEFAULT_PROGRAM = Path(r"C:\Program Files\Alpari MT5_5")
DEFAULT_DATA = Path(
    r"C:\Users\BazikadeStore\AppData\Roaming\MetaQuotes\Terminal"
    r"\D1B330D0A9F747F2A29FEEEC1880DEF4"
)

DEFAULT_LOGIN = ""
DEFAULT_SERVER = ""
EA_NAME = "ParityExporter"
JOB_FILE = "parity_job.json"

TESTER_INI = """[Common]
{credentials}ProxyEnable=0

[Tester]
{credentials}Expert=AlBrooks\\{ea}
Symbol={symbol}
Period={period}
Model=0
FromDate={from_date}
ToDate={to_date}
Deposit=10000
UseLocal=1
ShutdownTerminal=1
Visual=0
Report={report}
"""

#: The `Login`/`Server` pair, present in BOTH sections or not at all.
#:
#: Only `[Common]` logs the terminal in, which leaves the local agent
#: unauthorised and looks exactly like a broker problem. An empty `Login=`
#: is not the same as an absent one, so the lines are omitted rather than
#: blanked when no credentials were supplied.
CREDENTIALS = "Login={login}\nServer={server}\n"


def log(msg: str) -> None:
    print(f"[build_mql5] {msg}", flush=True)


def read_account(data: Path) -> tuple[str, str]:
    """The account the installed terminal is signed in to, from its own config.

    Read rather than hard-coded, and that is the point. A login baked into a
    build script is a login that is wrong on the next machine, and the
    symptom is `tester not started because the account is not specified` --
    which reads as a permissions or broker problem and is neither. The data
    folder already knows, because the user signed in with it.
    """
    common = data / "config" / "common.ini"
    if not common.is_file():
        return ("", "")
    found: dict[str, str] = {}
    for line in common.read_text(encoding="utf-16", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in ("Login", "Server"):
            found.setdefault(key.strip(), value.strip())
    return (found.get("Login", ""), found.get("Server", ""))


def prepare_mirror(program: Path, data: Path, work: Path, symbol: str) -> Path:
    """A writable, self-contained copy of the terminal to actually run.

    ## Why the installed terminal is not simply used

    Two independent reasons, and the first one is the expensive one.

    1. **A live instance eats the batch run.** `terminal64.exe /config:...`
       against a data folder that already has an open instance does not
       start the tester. It produces no error, no log entry and no
       report -- the run is silently a no-op, and the symptom is an
       absent sidecar, which looks like a broken EA. A developer machine
       with four terminals open is a normal machine, so the loop cannot
       depend on all of them being closed.
    2. **`Program Files` is not writable** without elevation, so a
       `/portable` tree rooted at the install cannot be staged into --
       `mkdir` raises `PermissionError`, which says nothing about the
       tester and invites the wrong fix.

    A directory copy sidesteps both. It is ~300 MB, copied once and
    reused; the copy is refreshed only when the install is missing.

    ## What has to come across from the data folder

    Two things, and omitting either produces a *confident* failure rather
    than an error:

    - **`config/*`, into the directory's contents.** `accounts.dat` is
      what lets the tester agent authorise. The install already has a
      `Config` folder, so copying the data folder's `config` *onto* that
      path nests it one level deeper, the account is not found, and the
      terminal says `tester not started because the account is not
      specified`.
    - **Cached history for `symbol`.** A portable tree starts with an
      empty `Bases`. The EA reads its bars from the case file, so history
      is not what the vector is made of -- but the tester still refuses
      to start on a symbol with no data in range. Copying the symbol's
      cached history makes the run offline and deterministic. The symbol
      itself is irrelevant to the result and defaults to the one the
      machine has cached.
    """
    mirror = work / "terminal"
    if not (mirror / "terminal64.exe").is_file():
        log(f"building the mirror at {mirror} (one time, ~300 MB)")
        if mirror.exists():
            shutil.rmtree(mirror)
        mirror.mkdir(parents=True)
        shutil.copytree(program, mirror, dirs_exist_ok=True)

    config_src = data / "config"
    if config_src.is_dir():
        # `into` the contents, not `onto` the directory -- see the docstring.
        shutil.copytree(config_src, mirror / "config", dirs_exist_ok=True)

    for history in data.glob("bases/*/history"):
        symbol_history = history / symbol
        if not symbol_history.is_dir():
            continue
        server = symbol_history.parent.parent.name
        dst = mirror / "Bases" / server / "history" / symbol
        if not dst.is_dir():
            log(f"copying cached {symbol} history for {server}")
            shutil.copytree(symbol_history, dst)

    log(f"mirror ready: {mirror}")
    return mirror


def stage_sources(root: Path) -> Path:
    """Copy the repo's mql5/ tree into the terminal root that will run.

    The root is where the terminal loads the EA from, so staging and
    running into the same tree removes the "compiled in one place, looked
    for in another" class of failure entirely.
    """
    include_dst = root / "MQL5" / "Include" / "AlBrooks"
    experts_dst = root / "MQL5" / "Experts" / "AlBrooks"
    include_dst.mkdir(parents=True, exist_ok=True)
    experts_dst.mkdir(parents=True, exist_ok=True)

    n = 0
    for mqh in sorted((REPO / "mql5" / "Include" / "AlBrooks").glob("*.mqh")):
        shutil.copy2(mqh, include_dst / mqh.name)
        n += 1
    for mq5 in sorted((REPO / "mql5" / "Experts" / "AlBrooks").glob("*.mq5")):
        shutil.copy2(mq5, experts_dst / mq5.name)
        n += 1
    log(f"staged {n} source file(s) into {root}")
    return experts_dst / f"{EA_NAME}.mq5"


def compile_ea(source: Path, root: Path, work: Path) -> bool:
    """Compile, and return whether MetaEditor reported success.

    The verdict is read from MetaEditor's own log rather than from an exit code,
    which MetaEditor does not set meaningfully.
    """
    metaeditor = root / "MetaEditor64.exe"
    if not metaeditor.is_file():
        log(f"ERROR: {metaeditor} not found")
        return False

    log_path = work / "compile.log"
    if log_path.exists():
        log_path.unlink()

    subprocess.run(
        [
            str(metaeditor),
            f"/compile:{source}",
            f"/log:{log_path}",
            f"/inc:{root / 'MQL5'}",
        ],
        check=False,
        timeout=180,
    )

    if not log_path.is_file():
        log("ERROR: MetaEditor wrote no log. "
            "It does not compile into a portable tree -- stage into the tree "
            "that will actually run.")
        return False

    # MetaEditor writes UTF-16 on some builds and UTF-8 on others, so the BOM is
    # what decides. Decoding the wrong one yields a log full of NULs and a
    # "0 errors" that is never found.
    raw = log_path.read_bytes()
    encoding = "utf-16" if raw[:2] == b"\xff\xfe" else "utf-8"
    text = raw.decode(encoding, errors="replace")
    tail = [ln.strip() for ln in text.splitlines() if ln.strip()][-6:]
    for line in tail:
        log(f"  {line}")

    if "0 errors" not in text:
        log("ERROR: compile reported errors")
        return False

    ex5 = source.with_suffix(".ex5")
    if not ex5.is_file():
        log(f"ERROR: no .ex5 produced at {ex5}")
        return False
    log(f"compiled -> {ex5.name}")
    return True


def write_ini(
    work: Path,
    report: str,
    symbol: str,
    period: str,
    login: str = DEFAULT_LOGIN,
    server: str = DEFAULT_SERVER,
) -> Path:
    credentials = CREDENTIALS.format(login=login, server=server) if login else ""
    ini = work / "parity_tester.ini"
    ini.write_text(
        TESTER_INI.format(
            credentials=credentials,
            ea=EA_NAME,
            symbol=symbol,
            period=period,
            from_date="2024.01.02",
            to_date="2024.01.05",
            report=report,
        ),
        encoding="utf-8",
    )
    return ini


def run_tester(root: Path, ini: Path, timeout: int = 600) -> int:
    """Run the batch test and return the terminal's exit code.

    `/portable` is always passed. The terminal then uses the directory it
    lives in as its data root, which is what makes the mirror work: the
    EA it loads, the account it signs in with and the sandbox the agent
    writes into are all then the ones this script staged. Without the flag
    the terminal goes to the registry's data folder instead, where a live
    instance may already be running -- and a batch run against a live
    instance is a silent no-op.
    """
    terminal = root / "terminal64.exe"
    log(f"running the tester via {terminal} (this takes a moment)")
    completed = subprocess.run(
        [str(terminal), "/portable", f"/config:{ini}"],
        check=False,
        timeout=timeout,
    )
    return completed.returncode


def terminal_log_tail(root: Path, lines: int = 8) -> str:
    """The last few lines of the terminal's own log, for diagnosing a no-op.

    A batch run that does nothing writes nothing to the tester journal, so
    the terminal log is the only place the reason appears -- and the reason
    is nearly always one of the traps in this module's docstring.
    """
    logs = sorted((root / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return "(no terminal log)"
    return "\n".join(logs[-1].read_text(encoding="utf-16", errors="replace").splitlines()[-lines:])


def common_files_dir(data: Path, create: bool = False) -> Path:
    """The terminal's *shared* `Common/Files`, reached with MQL5's `FILE_COMMON`.

    ## Why not the agent's own `MQL5/Files`

    That directory is wiped by the agent on every startup. Staging inputs there
    before a run means they are gone by the time `OnInit` executes, and the EA
    correctly reports it "cannot read" a file that is demonstrably sitting on
    disk. This was measured, not assumed: the EA printed
    `TERMINAL_DATA_PATH=<program>\\Tester\\Agent-127.0.0.1-3000`, and after the
    run the staged files were gone.

    `Common/Files` is shared across agents and survives, so it is the only place
    an input can be staged for an EA to read it.
    """
    files = data.parent / "Common" / "Files"
    if create:
        files.mkdir(parents=True, exist_ok=True)
    return files


def stage_inputs(files: Path, case_id: str) -> None:
    """Put the case and the job file where the agent's FileOpen can reach them."""
    case_src = REPO / "tests" / "parity" / "cases" / f"{case_id}.json"
    if not case_src.is_file():
        raise SystemExit(f"no such case: {case_src}")
    shutil.copy2(case_src, files / case_src.name)
    (files / JOB_FILE).write_text(
        json.dumps({"case": case_src.name}, indent=2) + "\n", encoding="utf-8"
    )
    log(f"staged {case_src.name} and {JOB_FILE} into {files}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, help="parity case id, without .json")
    ap.add_argument(
        "--program",
        type=Path,
        default=DEFAULT_PROGRAM,
        help="the installed terminal to mirror. Never run directly -- see "
        "prepare_mirror().",
    )
    ap.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="the data folder the installed terminal uses. Supplies the saved "
        "account and the cached history the mirror needs.",
    )
    ap.add_argument(
        "--symbol",
        default="XAUUSD",
        help="chart symbol for the test. Irrelevant to the result -- the EA "
        "reads its bars from the case file -- but the tester needs a symbol "
        "with history in range, so this defaults to the one the machine has "
        "cached.",
    )
    ap.add_argument("--period", default="H1")
    ap.add_argument(
        "--login",
        default=DEFAULT_LOGIN,
        help="terminal account number. Omit to use the account the terminal "
        "is already signed in to; a wrong one is a broker-looking failure.",
    )
    ap.add_argument("--server", default=DEFAULT_SERVER, help="terminal server name")
    ap.add_argument(
        "--work",
        type=Path,
        default=Path(os.environ.get("TEMP", ".")) / "opencode" / "mql5",
        help="scratch directory. The terminal mirror lives here.",
    )
    args = ap.parse_args()

    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)

    root = prepare_mirror(args.program, args.data, work, args.symbol)

    login, server = read_account(args.data)
    if not args.login:
        args.login = login
    if not args.server:
        args.server = server
    log(f"tester account: {args.login or '(none found)'} on {args.server or '(none)'}")

    source = stage_sources(root)
    if not compile_ea(source, root, work):
        return 1

    files = common_files_dir(args.data, create=True)
    log(f"shared file exchange: {files}")

    stage_inputs(files, args.case)

    sidecar_name = f"{args.case}.mql5.json"
    target = files / sidecar_name
    if target.exists():
        target.unlink()

    code = run_tester(
        root,
        write_ini(
            work, str(work / "report"), args.symbol, args.period, args.login, args.server
        ),
    )

    # The agent may run asynchronously; give the file a moment rather than
    # reporting a failure that is only a race.
    for _ in range(20):
        if target.is_file():
            break
        time.sleep(0.5)

    if not target.is_file():
        log(f"ERROR: the run produced no {sidecar_name} (terminal exit {code}). "
            "The terminal's own log is below; a run that starts and stops "
            "without a line mentioning the tester never ran it.")
        for line in terminal_log_tail(root).splitlines():
            log(f"  {line}")
        return 1

    dest = REPO / "tests" / "parity" / "mql5" / sidecar_name
    shutil.copy2(target, dest)
    log(f"sidecar -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
