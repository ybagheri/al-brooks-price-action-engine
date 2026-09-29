"""Compile, run and read back the MQL5 parity exporter.

    python scripts/build_mql5.py --case parity_range_breakout_001

## What this does, and why it is a script rather than a shell recipe

The loop is compile -> run -> read back, and every step has a trap that a
recipe hides:

- **MetaEditor will not compile into a portable tree.** No log and no `.ex5`,
  even with `/portable`. So sources are staged into the *data* folder, compiled
  there, and the `.ex5` is copied to the portable tree that actually runs.
- **The EA must live in a subfolder.** `Expert=AlBrooks\\Foo` means
  `MQL5/Experts/AlBrooks/Foo.ex5`. A file at `MQL5/Experts/Foo.mq5` is reported
  as *not found*, which reads like a build failure.
- **`Login` and `Server` must be in BOTH `[Common]` and `[Tester]`.** Only
  `[Common]` logs the terminal in, leaving the local agent unauthorised -- which
  looks like a broker problem and is not.
- **A tester agent's `FileOpen` lands in the agent sandbox**, not the terminal
  data folder, and the port number varies. So the sidecar has to be hunted for
  rather than at a fixed path.
- **The agent sandbox does not exist until the terminal has run once.**

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
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Verified working locations. Overridable, because a hard-coded path in a build
# script is a path that will be wrong on the next machine.
DEFAULT_PROGRAM = Path(r"C:\Users\bagheri\AppData\Roaming\Alpari MT5_4")
DEFAULT_DATA = Path(
    r"C:\Users\bagheri\AppData\Roaming\MetaQuotes\Terminal"
    r"\03C7913CF64CF66F404A7F9AC18C91E0"
)

# From the terminal's own log: "'53183424': authorized on Alpari-MT5-Demo".
DEFAULT_LOGIN = "53183424"
DEFAULT_SERVER = "Alpari-MT5-Demo"

EA_NAME = "ParityExporter"
JOB_FILE = "parity_job.json"

TESTER_INI = """[Common]
Login={login}
Server={server}
ProxyEnable=0

[Tester]
Login={login}
Server={server}
Expert=AlBrooks\\{ea}
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


def log(msg: str) -> None:
    print(f"[build_mql5] {msg}", flush=True)


def agent_files_dir(program: Path, create: bool = False) -> Path | None:
    """The tester agent's sandbox, or None if no agent has run yet.

    The `Agent-127.0.0.1-<port>` name is not stable -- this run produced port
    3000 where `MQL5_BUILD_LOOP.md` records 3001 -- so it is resolved rather
    than hard-coded.

    The agent creates `MQL5/Files` lazily, the first time something writes
    there. An agent that has only ever run an EA which failed to read its input
    has no `MQL5` directory at all, so a plain existence check reports "no
    sandbox" and the loop never converges. With `create`, the directory is made
    on demand, which is the same thing the agent itself would have done had the
    EA got far enough to write.
    """
    agents = [a for a in (program / "Tester").glob("Agent-*") if a.is_dir()]
    if not agents:
        return None

    # Prefer an agent that already has the sandbox, then the most recent.
    with_files = [a for a in agents if (a / "MQL5" / "Files").is_dir()]
    agent = max(with_files or agents, key=lambda p: p.stat().st_mtime)

    files = agent / "MQL5" / "Files"
    if create:
        files.mkdir(parents=True, exist_ok=True)
    return files if files.is_dir() else None


def stage_sources(data: Path) -> Path:
    """Copy the repo's mql5/ tree into the data folder.

    The data folder is the compile target because MetaEditor ignores `/portable`
    trees entirely.
    """
    include_dst = data / "MQL5" / "Include" / "AlBrooks"
    experts_dst = data / "MQL5" / "Experts" / "AlBrooks"
    include_dst.mkdir(parents=True, exist_ok=True)
    experts_dst.mkdir(parents=True, exist_ok=True)

    n = 0
    for mqh in sorted((REPO / "mql5" / "Include" / "AlBrooks").glob("*.mqh")):
        shutil.copy2(mqh, include_dst / mqh.name)
        n += 1
    for mq5 in sorted((REPO / "mql5" / "Experts" / "AlBrooks").glob("*.mq5")):
        shutil.copy2(mq5, experts_dst / mq5.name)
        n += 1
    log(f"staged {n} source file(s) into the data folder")
    return experts_dst / f"{EA_NAME}.mq5"


def compile_ea(source: Path, data: Path, program: Path, work: Path) -> bool:
    """Compile, and return whether MetaEditor reported success.

    The verdict is read from MetaEditor's own log rather than from an exit code,
    which MetaEditor does not set meaningfully.
    """
    metaeditor = program / "MetaEditor64.exe"
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
            f"/inc:{data / 'MQL5'}",
        ],
        check=False,
        timeout=180,
    )

    if not log_path.is_file():
        log("ERROR: MetaEditor wrote no log. "
            "It does not compile into a portable tree -- stage into the data folder.")
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


def write_ini(work: Path, report: str, symbol: str, period: str) -> Path:
    ini = work / "parity_tester.ini"
    ini.write_text(
        TESTER_INI.format(
            login=DEFAULT_LOGIN,
            server=DEFAULT_SERVER,
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


def run_tester(program: Path, ini: Path, timeout: int = 600) -> None:
    terminal = program / "terminal64.exe"
    log(f"running the tester via {terminal.name} (this takes a moment)")
    subprocess.run(
        [str(terminal), "/portable", f"/config:{ini}"],
        check=False,
        timeout=timeout,
    )


def deploy_ex5(ex5: Path, program: Path) -> Path:
    """Copy the compiled EA from the data folder into the portable tree.

    ## The trap this exists for

    MetaEditor will not compile into a portable tree, so the `.ex5` is produced
    under the *data* folder. But the terminal is launched with `/portable`, so
    it looks for the EA under the *program* folder. Compile in one, run in the
    other, and the tester reports:

        Experts\\AlBrooks\\ParityExporter.ex5 not found
        tester didn't start

    which reads like a build failure and is really a missing copy. The `.ex5` is
    a plain binary, so where it is compiled does not matter -- only where it is
    found.
    """
    dst_dir = program / "MQL5" / "Experts" / "AlBrooks"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / ex5.name
    shutil.copy2(ex5, dst)
    log(f"deployed {ex5.name} -> {dst}")
    return dst


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
    ap.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--period", default="H1")
    ap.add_argument(
        "--work", type=Path, default=Path("C:/Users/bagheri/AppData/Local/Temp/opencode/mql5")
    )
    args = ap.parse_args()

    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)

    source = stage_sources(args.data)
    if not compile_ea(source, args.data, args.program, work):
        return 1

    # Compile lands in the data folder; the portable run looks in the program
    # folder. Without this the tester reports the .ex5 as not found.
    deploy_ex5(source.with_suffix(".ex5"), args.program)

    files = common_files_dir(args.data, create=True)
    log(f"shared file exchange: {files}")

    stage_inputs(files, args.case)

    sidecar_name = f"{args.case}.mql5.json"
    target = files / sidecar_name
    if target.exists():
        target.unlink()

    run_tester(args.program, write_ini(work, str(work / "report"), args.symbol, args.period))

    # The agent may run asynchronously; give the file a moment rather than
    # reporting a failure that is only a race.
    for _ in range(20):
        if target.is_file():
            break
        time.sleep(0.5)

    if not target.is_file():
        log(f"ERROR: the run produced no {sidecar_name}. "
            "Check the EA's Print output in the tester journal.")
        return 1

    dest = REPO / "tests" / "parity" / "mql5" / sidecar_name
    shutil.copy2(target, dest)
    log(f"sidecar -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
