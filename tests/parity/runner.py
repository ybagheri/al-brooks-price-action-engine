"""Running the case set, and refusing to overstate what the run found.

## The report is the product

A parity harness has one failure mode that matters more than any bug in it: it
reports success when there was nothing to compare. This one is built so that
cannot happen quietly.

- A case with no MQL5 sidecar is `MQL5_ABSENT`, which is **not** a pass.
- A sidecar whose `producer` is not `mql5` is `NOT_AN_MQL5_SIDECAR`, so the
  Python-produced vectors in `tests/parity/reference/` can never be mistaken for
  a second implementation. They exist to exercise the comparator, and the runner
  says so rather than quietly ignoring them.
- `ParityReport.claims_parity` is true only when **every** case matched. Half the
  case set filled in is not half a pass; it is a report that must be read by
  someone who knows which half is missing, and a boolean cannot say that.
- The report carries its own `caveats`, following `BACKTESTING.md`'s precedent
  that a report cannot leave without them.

## Statuses

| Case status | Meaning |
|---|---|
| `MATCH` | Compared, and every declared leaf agreed. |
| `MISMATCH` | Compared, and at least one leaf did not. |
| `MQL5_ABSENT` | The case names no sidecar, or the named file is not there. |
| `NOT_AN_MQL5_SIDECAR` | A sidecar exists but was not produced by an MQL5 build. |
| `SCHEMA_MISMATCH` | The sidecar implements a different canonical form. |
| `SCOPE_REDUCED` | The sidecar covers a strict subset of `SCOPE`. |
| `CASE_ERROR` | The case file or the Python run is broken. Not a parity finding. |

The last four are not evidence of disagreement. They are evidence that the two
files do not describe the same comparison, which is a different problem for
whoever has to fix it, and folding them into `MISMATCH` would overstate what has
been learned.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from albrooks import __version__ as ALBROOKS_VERSION
from albrooks.engine.configuration import AnalyzerConfig
from tests.parity.compare import Difference, compare
from tests.parity.contract import (
    PRODUCER_MQL5,
    PRODUCER_PYTHON,
    SCHEMA_VERSION,
    CaseMismatch,
    SchemaMismatch,
    ScopeMismatch,
    VectorError,
    canonical_vector,
    dump,
    envelope,
    load_sidecar,
)

#: Where the case files live, and where Phase 21 drops its sidecars.
CASES_DIR = Path(__file__).resolve().parent / "cases"
VECTORS_DIR = Path(__file__).resolve().parent / "mql5"
#: Python-produced vectors, used to exercise the comparator. Never parity
#: evidence, and the runner refuses to treat them as such.
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"

MATCH = "MATCH"
MISMATCH = "MISMATCH"
MQL5_ABSENT = "MQL5_ABSENT"
NOT_AN_MQL5_SIDECAR = "NOT_AN_MQL5_SIDECAR"
SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
SCOPE_REDUCED = "SCOPE_REDUCED"
CASE_ERROR = "CASE_ERROR"

#: Report-level statuses. `UNVERIFIED` is the important one: it is what a run with
#: no MQL5 sidecars returns, and it is not a failure, because nothing was tested.
UNVERIFIED = "UNVERIFIED"
AGREED = "AGREED"
FAILED = "FAILED"

#: The statuses that mean two implementations were actually compared.
COMPARABLE = (MATCH, MISMATCH)

#: Exit codes. `UNVERIFIED` is distinct from `FAILED` on purpose: a CI job that
#: treats "no MQL5 build has run yet" as a test failure trains people to ignore
#: the failure that matters, which is the `RPC-18` argument again.
EXIT_AGREED = 0
EXIT_FAILED = 1
EXIT_UNVERIFIED = 2


# --------------------------------------------------------------------------
# Case files
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParityCase:
    """One bar series and the disagreement it is designed to catch.

    Deliberately **not** a golden fixture. There are no expected values here,
    because the whole point is to compare two implementations against each other
    rather than to pin one. What is pinned is the *input*, and a test asserts
    that the vector derived from it does not change when future bars are
    appended, which is the property both sides must share.
    """

    id: str
    intent: str
    spec: str
    config: Mapping[str, Any]
    last_closed: int
    bars: tuple[Mapping[str, Any], ...]
    mql5_vector: str | None
    path: Path

    def analyzer_config(self) -> AnalyzerConfig:
        return AnalyzerConfig.from_dict(dict(self.config))

    def vector(self) -> dict[str, Any]:
        """This repository's side of the comparison."""
        return canonical_vector(self.bars, self.last_closed, self.analyzer_config())


def load_case(path: Path) -> ParityCase:
    """Read one case file, or raise `ValueError` naming what is wrong with it.

    Every required key is required. A case that omits `config` is a case whose
    configuration nobody recorded, and the harness would then run it against
    whatever the defaults happen to be that week — which is exactly the drift a
    parity suite cannot tolerate.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: unreadable ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: top level is not an object")

    required = ("id", "intent", "spec", "config", "last_closed", "bars", "mql5_vector")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"{path.name}: missing {missing}")

    bars = payload["bars"]
    if not isinstance(bars, list) or not bars:
        raise ValueError(f"{path.name}: bars is not a non-empty list")
    for index, bar in enumerate(bars):
        for key in ("o", "h", "l", "c"):
            if key not in bar:
                raise ValueError(f"{path.name}: bar {index} has no {key!r}")

    sidecar = payload["mql5_vector"]
    if sidecar is not None and not isinstance(sidecar, str):
        raise ValueError(f"{path.name}: mql5_vector is neither null nor a filename")

    return ParityCase(
        id=str(payload["id"]),
        intent=str(payload["intent"]),
        spec=str(payload["spec"]),
        config=dict(payload["config"]),
        last_closed=int(payload["last_closed"]),
        bars=tuple(bars),
        mql5_vector=sidecar,
        path=path,
    )


def load_cases(directory: Path = CASES_DIR) -> list[ParityCase]:
    """Every case in a directory, ordered by filename so a run is reproducible."""
    paths = sorted(p for p in directory.glob("*.json") if p.is_file())
    return [load_case(path) for path in paths]


# --------------------------------------------------------------------------
# One case
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseResult:
    """What happened to one case, in enough detail to act on."""

    case_id: str
    status: str
    differences: tuple[Difference, ...] = ()
    max_deviation: float | None = None
    compared: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "compared_fields": self.compared,
            "max_relative_deviation": self.max_deviation,
            "note": self.note,
            "differences": [d.to_dict() for d in self.differences],
        }


def _resolve_sidecar(vectors_dir: Path, name: str) -> Path | CaseResult:
    """The sidecar path, or a refusal if `name` escapes the vectors directory.

    ## Why this is not paranoia

    `mql5_vector` is a string inside a case file, and joining it to a directory
    without checking where it lands is a path traversal. The input is a
    repository-tracked file, so this is not remotely exploitable — but the
    consequence is worse than an arbitrary read, and that is the reason it is fixed
    here rather than noted.

    The harness exists to answer "did a **real MQL5 run** agree with Python?". A
    case file that names a vector living anywhere else on disk lets a file that
    was never produced by an MQL5 build be compared, and a matching one would
    report `MATCH`. The refusal the runner already makes for a `producer` that is
    not `mql5` is exactly this threat; a traversal sidesteps it by supplying a
    file that *does* say `"producer": "mql5"`.

    A hostile case file is a hostile **commit**, and a pull request is a
    perfectly ordinary place for one to arrive. So the harness should not depend
    on every contributor having read this.

    The check is `Path.is_relative_to` on the resolved paths, so a symlink
    pointing out of the directory is refused too — resolving first is what makes
    that true.
    """
    root = vectors_dir.resolve()
    candidate = (vectors_dir / name).resolve()
    if not candidate.is_relative_to(root):
        return CaseResult(
            case_id=Path(name).name,
            status=CASE_ERROR,
            note=(
                f"mql5_vector {name!r} resolves outside {root}; a sidecar must be a "
                f"file in the vectors directory, and a vector from anywhere else "
                f"would defeat the producer check the harness relies on"
            ),
        )
    return candidate


def run_case(case: ParityCase, vectors_dir: Path = VECTORS_DIR) -> CaseResult:
    """Run one case on both sides, or explain why it could not be run."""
    try:
        python_vector = case.vector()
    except Exception as exc:  # noqa: BLE001 - a broken case must not kill the run
        return CaseResult(case.id, CASE_ERROR, note=f"python side failed: {exc}")

    if case.mql5_vector is None:
        return CaseResult(
            case.id,
            MQL5_ABSENT,
            note="no MQL5 sidecar named; nothing was compared",
        )

    path = _resolve_sidecar(vectors_dir, case.mql5_vector)
    if isinstance(path, CaseResult):
        return path
    if not path.is_file():
        return CaseResult(
            case.id, MQL5_ABSENT, note=f"{case.mql5_vector} is not in {vectors_dir.name}/"
        )

    try:
        payload = load_sidecar(path, case_id=case.id)
    except SchemaMismatch as exc:
        return CaseResult(case.id, SCHEMA_MISMATCH, note=str(exc))
    except ScopeMismatch as exc:
        return CaseResult(case.id, SCOPE_REDUCED, note=str(exc))
    except CaseMismatch as exc:
        return CaseResult(case.id, CASE_ERROR, note=str(exc))
    except VectorError as exc:
        return CaseResult(case.id, CASE_ERROR, note=str(exc))

    if payload["producer"] != PRODUCER_MQL5:
        return CaseResult(
            case.id,
            NOT_AN_MQL5_SIDECAR,
            note=(
                f"{path.name} was produced by {payload['producer']!r}, which is not an "
                f"MQL5 build; it is not parity evidence"
            ),
        )

    try:
        result = compare(payload["vector"], python_vector)
    except VectorError as exc:
        return CaseResult(case.id, CASE_ERROR, note=f"vector not comparable: {exc}")

    status = MATCH if result.agrees else MISMATCH
    return CaseResult(
        case.id,
        status,
        differences=result.differences,
        max_deviation=result.max_deviation,
        compared=result.compared,
    )


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

#: True whatever the run found, and carried inside the report so it cannot be
#: separated from the numbers.
CAVEATS: tuple[str, ...] = (
    "Agreement is over the declared SCOPE and the supplied cases only. It is not "
    "proof that the two implementations are equivalent, and it says nothing about "
    "inputs outside the case set.",
    "The NUMBER tolerance absorbs a different order of summation. It is not a "
    "proof that both sides perform the same arithmetic, and every index and code "
    "in the scope is compared exactly.",
    "List order is not compared. A port whose findings arrive in a different order "
    "than this repository's would pass; a port that finds a different *number* of "
    "them would not.",
    "What an MQL5 build feeds the engine is outside this harness. Whether it froze "
    "a live series, whether its bars are the same bars, and whether its chart is "
    "in sync are the adapter's obligations, per RPC-14 and RPC-15.",
    "Nothing in this project has been validated against outcomes, and neither has "
    "anything this harness compares. A parity result is an agreement about code, "
    "not about the market.",
)


@dataclass(frozen=True, slots=True)
class ParityReport:
    """The whole run, with its own verdict and its own caveats attached."""

    results: tuple[CaseResult, ...]
    schema: str = SCHEMA_VERSION
    caveats: tuple[str, ...] = field(default=CAVEATS)

    @property
    def compared(self) -> tuple[CaseResult, ...]:
        return tuple(r for r in self.results if r.status in COMPARABLE)

    @property
    def status(self) -> str:
        """`UNVERIFIED`, `AGREED` or `FAILED` — in that order of honesty.

        Nothing *compared* is `UNVERIFIED` rather than a failure, because the most
        expensive thing this harness could do is report a verdict having compared
        nothing at all — and in Phase 20 that is the normal outcome, since no MQL5
        build exists yet. Once anything is compared, any case that is not `MATCH` —
        including one that could not be compared — makes the run `FAILED`, so a
        half-filled case set can never read as agreement.
        """
        if not self.results or not self.compared:
            return UNVERIFIED
        if all(r.status == MATCH for r in self.results):
            return AGREED
        return FAILED

    @property
    def claims_parity(self) -> bool:
        return self.status == AGREED

    @property
    def claim_text(self) -> str:
        """One sentence, saying what was and was not established."""
        if self.status == AGREED:
            return (
                f"All {len(self.results)} case(s) agreed on every declared field. "
                "This is agreement on the supplied cases, not a general proof of "
                "equivalence."
            )
        if self.status == UNVERIFIED:
            return (
                "No case was compared, so nothing about parity has been established. "
                "No MQL5 sidecar has been supplied."
            )
        compared = len(self.compared)
        mismatched = sum(1 for r in self.results if r.status == MISMATCH)
        uncompared = len(self.results) - compared
        return (
            f"{compared} of {len(self.results)} case(s) were compared; {mismatched} "
            f"disagreed and {uncompared} could not be compared. Parity is not "
            "established."
        )

    def counts(self) -> dict[str, int]:
        """Status -> count, zeros included.

        Zeros are included so a report cannot imply by omission that a status did
        not occur, which is the failure mode of every count dict that only holds
        what was found.
        """
        out = {
            MATCH: 0,
            MISMATCH: 0,
            MQL5_ABSENT: 0,
            NOT_AN_MQL5_SIDECAR: 0,
            SCHEMA_MISMATCH: 0,
            SCOPE_REDUCED: 0,
            CASE_ERROR: 0,
        }
        for result in self.results:
            out[result.status] = out.get(result.status, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "claims_parity": self.claims_parity,
            "claim": self.claim_text,
            "compared_cases": len(self.compared),
            "counts": self.counts(),
            "caveats": list(self.caveats),
            "cases": [r.to_dict() for r in self.results],
        }


def run(
    cases: Sequence[ParityCase] | None = None,
    vectors_dir: Path = VECTORS_DIR,
) -> ParityReport:
    """Run every case and return the report. Never raises for a bad case."""
    loaded = list(cases) if cases is not None else load_cases()
    return ParityReport(tuple(run_case(case, vectors_dir) for case in loaded))


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def _write_reference(directory: Path) -> int:
    """Write this repository's vectors into `directory`, in the sidecar envelope.

    `--write-reference` exists here and not for the golden fixtures, and the
    difference is worth stating. A golden expectation is a *claim about what is
    right*, and a tool that regenerates it removes the only part worth having. A
    reference vector is a claim about *what this code currently prints*, used
    solely to exercise the comparator, and every file it writes says
    `"producer": "python"` — so it cannot be mistaken for the MQL5 side, which is
    the only reason it is safe to automate.

    It is also why these files are not a regression baseline. `tests/parity/`
    pins no values; `tests/fixtures/golden/` is the regression suite.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for case in load_cases():
        payload = envelope(
            case.id, case.vector(), PRODUCER_PYTHON, f"albrooks {ALBROOKS_VERSION}"
        )
        target = directory / f"{case.id}.python.json"
        target.write_text(dump(payload), encoding="utf-8")
        print(f"wrote {target}")
    return EXIT_AGREED


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Python / MQL5 parity harness")
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help="case directory")
    parser.add_argument("--vectors", type=Path, default=VECTORS_DIR, help="MQL5 sidecar directory")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help=(
            "exit 0 when no case was compared. This is scaffolding for Phase 20, "
            "during which no MQL5 build exists; Phase 21 removes it, and a test "
            "asserts the two stay in step."
        ),
    )
    parser.add_argument(
        "--write-reference",
        type=Path,
        default=None,
        metavar="DIR",
        help="write this repository's vectors into DIR as producer=python files",
    )
    args = parser.parse_args(argv)

    if args.write_reference is not None:
        return _write_reference(args.write_reference)

    try:
        cases = load_cases(args.cases)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return EXIT_FAILED

    report = run(cases, args.vectors)
    if args.json:
        print(dump(report.to_dict()), end="")
    else:
        for result in report.results:
            line = f"{result.case_id}: {result.status}"
            if result.max_deviation is not None:
                line += f" (worst relative deviation {result.max_deviation:.3e})"
            print(line)
            for difference in result.differences:
                print(f"    {difference.describe()}")
            if result.note:
                print(f"    note: {result.note}")
        print()
        print(f"status: {report.status} -- {report.claim_text}")
        for caveat in report.caveats:
            print(f"  - {caveat}")

    if report.status == AGREED:
        return EXIT_AGREED
    if report.status == UNVERIFIED:
        return EXIT_UNVERIFIED if not args.allow_unverified else EXIT_AGREED
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
