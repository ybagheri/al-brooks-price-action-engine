#!/usr/bin/env python3
"""Fail CI when required project documentation is missing.

Documentation is a first-class deliverable for this project, so the absence of a
required document is treated as a build failure rather than a backlog item.

Documents are split into two tiers:

* `REQUIRED` -- must exist now. Missing one fails CI.
* `PENDING`  -- specced for a later phase. Reported for visibility, but does not
  fail the build until the corresponding phase is complete.

Usage:
    python scripts/check_docs_present.py           # required only (CI)
    python scripts/check_docs_present.py --all     # also fail on pending
    python scripts/check_docs_present.py --phase 12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Root-level files the project must always ship.
REQUIRED_ROOT: tuple[str, ...] = (
    "README.md",
    "README_FA.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SOURCES.md",
    "ROADMAP.md",
)

# Root-level files due with a later phase.
PENDING_ROOT: tuple[tuple[str, int], ...] = ()

# Algorithm documents. Each is (path, phase_that_owes_it).
REQUIRED_DOCS: tuple[tuple[str, int], ...] = (
    ("docs/FM_INDICATOR_AUDIT.md", 0),
    ("docs/architecture/ARCHITECTURE.md", 1),
    ("docs/architecture/CONCEPT_TAXONOMY.md", 2),
    ("docs/algorithms/BAR_BY_BAR.md", 2),
    ("docs/algorithms/SWINGS_AND_LEGS.md", 3),
    ("docs/algorithms/MARKET_CONTEXT.md", 4),
    ("docs/algorithms/STRUCTURES.md", 5),
    ("docs/algorithms/H1_H2_L1_L2.md", 6),
    ("docs/algorithms/DOUBLE_PATTERNS.md", 7),
    ("docs/algorithms/BREAKOUTS.md", 8),
    ("docs/algorithms/REVERSALS.md", 9),
    ("docs/algorithms/MEASURED_MOVES.md", 10),
    ("docs/algorithms/FADING_MEASURED_MOVE.md", 11),
    ("docs/algorithms/SETUP_ENGINE.md", 12),
    ("docs/algorithms/EVIDENCE_MODEL.md", 13),
    ("docs/algorithms/TRADE_PLAN.md", 14),
    ("docs/algorithms/DECISION_ENGINE.md", 15),
    ("docs/algorithms/MULTI_TIMEFRAME.md", 16),
    ("docs/algorithms/NON_REPAINT_CONTRACT.md", 17),
    ("docs/algorithms/BACKTESTING.md", 18),
    ("docs/algorithms/VALIDATION.md", 19),
    ("docs/PYTHON_MQL5_PARITY.md", 20),
    ("docs/algorithms/MT5_ADAPTER.md", 21),
    ("docs/algorithms/AI_INTERFACE.md", 22),
    ("docs/fa/README.md", 23),
)

# Only documents owed by a phase that has NOT been completed yet.
#
# Moving an entry from here into `REQUIRED_DOCS` is the act that says "this phase
# owes a document". Leaving a completed phase's document down here is not neutral
# bookkeeping: `--phase 13` would then fail the build over twelve files that are
# already on disk, which is a CI failure that means nothing and so trains people
# to ignore the one that does.
#
# Every phase through 22 now owes no further document. Phase 21 filled the harness
# Phase 20 defined and added `MT5_ADAPTER.md`; Phase 22 added `AI_INTERFACE.md`.
# Phase 23 is documentation-only and owes no new path: it expands the documents
# already required above.
PENDING_DOCS: tuple[tuple[str, int], ...] = ()



def _missing(paths: tuple[str, ...]) -> list[str]:
    return [p for p in paths if not (REPO_ROOT / p).is_file()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="also fail on documents owed by a later phase",
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=None,
        help="also fail if a pending document's owning phase has been reached",
    )
    args = parser.parse_args(argv)

    required_missing = _missing(REQUIRED_ROOT) + _missing(
        tuple(p for p, _ in REQUIRED_DOCS)
    )

    # Flatten the (path, phase) manifests down to plain paths.
    pending_targets = [p for p, _ in PENDING_ROOT] + [p for p, _ in PENDING_DOCS]
    if args.phase is not None:
        # Only police documents whose owning phase has already been reached.
        pending_targets = [
            p for p, ph in (*PENDING_ROOT, *PENDING_DOCS) if ph <= args.phase
        ]
    pending_missing = _missing(tuple(pending_targets))

    if pending_missing:
        print("Pending documentation (not yet due):")
        for p in pending_missing:
            print(f"  - {p}")
        print()

    if required_missing:
        print(f"FAIL: {len(required_missing)} required document(s) missing:")
        for p in required_missing:
            print(f"  - {p}")
        return 1

    if pending_missing and (args.all or args.phase is not None):
        print(f"FAIL: {len(pending_missing)} due document(s) missing.")
        return 1

    total = len(REQUIRED_ROOT) + len(REQUIRED_DOCS)
    print(f"PASS: all {total} required document(s) present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
