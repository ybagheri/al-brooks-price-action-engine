"""The documentation must not lie about how far the project has got.

This exists for a specific reason. A reader — or a model — arriving at this
repository has exactly one cheap way to find out what state it is in, and that
is by reading `README.md` and `ROADMAP.md`. If those two are stale, the reader
draws a false conclusion and no amount of correct code makes up for it.

The failure mode is not hypothetical. Before this file existed, an audit found:

- `README.md`'s status table stopped at Phase 17, so **backtesting and the golden
  fixtures read as unbuilt** in the one table a reader is most likely to look at,
  while two other sections of the same file documented both in detail.
- `README_FA.md` had no status table at all, only a two-line callout, so a Persian
  reader had no per-area state to read.
- `BACKTESTING.md`, `DECISION_ENGINE.md` and `TRADE_PLAN.md` each described
  Phase 19 as future work, under headings reading *Known limitations* — which
  makes a completed phase read as a live gap.
- `scripts/check_docs_present.py` listed **twelve** documents owed by completed
  phases as still pending, so `check_docs_present.py --phase 13` failed CI over
  files that were sitting on disk.

The `RPC-18` pattern is the one this project already trusts: a document that
makes claims is made accountable to something that checks them. That is what
these tests do.

The checks are deliberately narrow. They assert *consistency*, not correctness of
prose, and none of them can tell you whether an algorithm is any good.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROADMAP = REPO / "ROADMAP.md"
README = REPO / "README.md"
README_FA = REPO / "README_FA.md"

#: The phases known to be complete, as a set rather than a watermark.
#:
#: This was a `LAST_COMPLETE_PHASE = 20` watermark until Phase 22 landed, which
#: exposed an assumption baked into three tests: that completed phases are
#: **contiguous**. They are not, and now cannot be — Phase 21's MQL5 port is
#: blocked on MetaEditor indefinitely, while Phase 22 needed nothing external and
#: shipped.
#:
#: A watermark models "phases land in order", which was true until the first phase
#: had to wait on hardware. A set models what is actually true, and a phase that is
#: genuinely complete after a blocked one is not a defect to be encoded away.
#:
#: Phase 23 is complete and the set is therefore everything except 21.
LAST_COMPLETE_PHASE = 23
LAST_PHASE = 23

#: Phases that are complete, derived from the watermark. Everything at or below
#: `LAST_COMPLETE_PHASE` except those listed in `PHASES_STILL_OPEN`.
#:
#: **Now empty.** Phase 21 was the last one open, and it closed when the MQL5
#: port was written, built by a real MetaEditor compile and a real Strategy
#: Tester run, and agreed with Python on all three cases at zero deviation.
#:
#: The set is kept rather than deleted, because it is the mechanism: a phase is
#: removed from here in the same change that fills its checkbox, and the test
#: below fails in both directions. Deleting the constant would remove the only
#: place that could be wrong, and the roadmap sentence it generates is asserted
#: against it.
PHASES_STILL_OPEN: frozenset[int] = frozenset()

#: Every complete phase. Used by the roadmap tests instead of a range.
COMPLETE_PHASES: frozenset[int] = (
    frozenset(range(LAST_COMPLETE_PHASE + 1)) - PHASES_STILL_OPEN
)

#: The highest phase that has *started*, which may own a document that is already
#: required because the part of it that shipped needs documenting.
#:
#: A document for work that has *not* started is still refused -- the distinction
#: this constant draws is between a phase in flight and a phase not yet begun.
#: Note that Phase 21 is *not* complete either: its MQL5 port is blocked on
#: MetaEditor, and nothing here should be read as saying otherwise.
IN_PROGRESS_PHASE = 23

MARKDOWN = sorted(
    p
    for p in REPO.rglob("*.md")
    if ".git" not in p.parts
    and "__pycache__" not in p.parts
    and "node_modules" not in p.parts
)

#: Documents excluded from the *path existence* check only, each for a stated
#: reason. Excluding a file is a decision, so each one is named and justified.
PATH_CHECK_EXEMPT = {
    "CHANGELOG.md": "a historical record; its rename entry names the old filename on purpose",
    "FM_INDICATOR_AUDIT.md": (
        "audits the separate FM-indicator repository, so its paths are that repo's,"
        " in past tense, not ours"
    ),
}

#: Documents excluded from the *forward-reference* check. A changelog is history
#: by definition and its 0.1.0 section describes 0.1.0; a future-tense sentence
#: about a phase that was pending then is correct there.
FORWARD_CHECK_EXEMPT = {"CHANGELOG.md"}

PHASE_LINE = re.compile(r"^- \[(x| )\]\s+\*\*Phase (\d+)\b", re.MULTILINE)
#: Paths that look like they point at a file in this repository.
REPO_PATH = re.compile(
    r"`((?:src|tests|docs|scripts|mql5|examples)/[A-Za-z0-9_./-]+\.(?:py|md|json|mqh|pyi))`"
)

#: Phases whose deliverables are named by a path, and therefore may be named in
#: prose even while the phase is pending. Everything else must not be.
#:
#: `tests/parity/` is here because the harness shipped with Phase 20 and the only
#: thing still missing inside it is the MQL5 sidecar Phase 21 writes. Naming a
#: harness that exists is not naming unfinished work.
PENDING_PHASE_PATHS = (
    "src/albrooks/serialization/json.py",
    "examples/llm_analysis.py",
    "docs/algorithms/AI_INTERFACE.md",
    "mql5/",
    "src/albrooks/adapters/mt5/",
)

#: The grammatical constructions by which a *completed* phase gets described as
#: work still to do. This is deliberately a short list of specific shapes rather
#: than a general tense heuristic.
#:
#: An earlier version of this check tried to infer pending-ness from the whole
#: line and produced seventy false positives on the first run, because "Phase 13's
#: `basis` field" and "**Phase 11** -- `src/...`" are both legitimate attributions
#: of a shipped phase. A check that cries wolf gets deleted, and a deleted check
#: protects nothing. So: exact shapes, verified against the corpus.
#:
#: Note what is *absent*. "X is Phase N" was tried and removed, because it cannot
#: be told apart from "This is Phase 13's `basis` field applied to prices" -- one
#: is a stale excuse and the other is a correct citation, and the shapes are
#: identical. Losing that coverage is the right trade.
FORWARD_REFERENCE = re.compile(
    r"\bPhase\s+(\d+)'s\s+(?:job|work)\b"  # "calibrating is Phase 13's job"
    r"|\bPhase\s+(\d+)\s+(?:will|shall)\b"  # "Phase 19 will supply"
    r"|\b(?:is|are)\s+(?:future|pending)\s+work\b"
    r"|\bdoes not exist yet\b",
    re.IGNORECASE,
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The roadmap is the authoritative progress document
# --------------------------------------------------------------------------


def test_the_roadmap_marks_every_completed_phase_and_leaves_the_rest_open() -> None:
    """The one checkbox per phase, and it must match reality.

    A phase left unchecked after shipping is the most expensive kind of stale
    documentation, because it is the answer to "what is left to do" and it is
    wrong in the direction that invites rework.
    """
    found = {int(n): done == "x" for done, n in PHASE_LINE.findall(_text(ROADMAP))}

    assert sorted(found) == list(range(LAST_PHASE + 1)), (
        f"the roadmap lists phases {sorted(found)}, expected 0..{LAST_PHASE}"
    )
    for phase, done in sorted(found.items()):
        if phase in COMPLETE_PHASES:
            assert done, f"Phase {phase} is complete but unchecked in ROADMAP.md"
        else:
            assert not done, f"Phase {phase} is not complete but checked in ROADMAP.md"


def test_the_roadmap_states_how_much_is_done() -> None:
    """A reader should not have to count checkboxes.

    The document's own premise is honest self-reporting, and a progress count is
    the single most-consumed fact about a project of this kind. It was missing.

    The count is `len(COMPLETE_PHASES)` rather than a watermark, and the
    "which are done" assertion changed with it. "Phases 0 through 22 are done" was
    **false** the moment Phase 22 landed while Phase 21 is still blocked on
    MetaEditor — a sentence that reads as a summary and is a lie. The roadmap now
    names the gap explicitly instead.
    """
    text = _text(ROADMAP)
    expected_done = len(COMPLETE_PHASES)
    expected_total = LAST_PHASE + 1  # phases 0..23 inclusive

    assert f"{expected_done} of {expected_total} phases are complete" in text
    # The count must agree with the checkboxes, or the two disagree in the two
    # places a reader is most likely to look.
    assert expected_done == sum(
        done == "x" for done, _ in PHASE_LINE.findall(text)
    ), "the stated count disagrees with the checkboxes"
    # Every phase still open must be named as such rather than swept into a range.
    for phase in sorted(PHASES_STILL_OPEN):
        assert f"Phase {phase} is" in text or f"Phase {phase} " in text, (
            f"Phase {phase} is not complete but the prose does not single it out"
        )
    # And it must say where the remaining work is, not merely count it.
    assert "## Where the project stands" in text


def test_the_roadmap_navigates_to_every_section_it_advertises() -> None:
    """An anchor that does not resolve is a dead link in the document a reader is
    sent to first."""
    text = _text(ROADMAP)
    headings = {
        re.sub(r"[^a-z0-9 -]", "", m.group(1).lower()).replace(" ", "-")
        for m in re.finditer(r"^#{2,3}\s+(.+?)\s*$", text, re.MULTILINE)
    }
    for anchor in re.findall(r"\]\(#([a-z0-9-]+)\)", text):
        assert anchor in headings, f"ROADMAP.md links to #{anchor}, which is not a heading"


# --------------------------------------------------------------------------
# The READMEs must carry the same picture
# --------------------------------------------------------------------------


def test_the_readme_status_table_covers_every_area_of_the_engine() -> None:
    """Both READMEs, and they must agree on shape.

    An English table with per-area state and a Persian callout with no table is an
    asymmetry a Persian reader cannot navigate around, and Phase 23 exists
    precisely because these documents are supposed to be equivalent.
    """
    for readme, marker in ((README, "## Status"), (README_FA, "## معماری")):
        text = _text(readme)
        assert marker in text, f"{readme.name} has no status area"

    english = _text(README)
    assert "## Status" in english
    assert f"{len(COMPLETE_PHASES)} of {LAST_PHASE + 1} phases are complete" in english

    for area in (
        "Backtesting",
        "Golden fixtures",
        "Non-repaint contract",
        "Trade plans",
        "Decisions",
    ):
        assert area in english, f"README.md status table is missing {area!r}"

    # Phase 21 split one row into two, and this assertion is what keeps that honest.
    # It used to be a single `"MT5 adapter" in english` check, which passed for as
    # long as the phrase appeared *anywhere* -- so it went on passing after the
    # adapter shipped and the row changed meaning, testing nothing. The rows are
    # now matched on the line they appear in, which is the thing a reader reads.
    # A markdown row splits as ['', ' name ', ' state ', '', ...] -- the leading
    # pipe produces an empty first field, which is why the name is cells[1].
    rows = {
        cells[1].strip(): cells[2].strip()
        for line in english.splitlines()
        if line.strip().startswith("|")
        for cells in [line.split("|")]
        if len(cells) > 3 and cells[1].strip()
    }
    assert "Implemented" in rows["MT5 adapter"], (
        f"README.md still reports the MT5 adapter as {rows['MT5 adapter']!r}; "
        f"Phase 21 shipped it"
    )
    # `MQL5 parity` is a different claim from `MQL5 layer`: one is about what the
    # comparison found, the other about whether there is a second implementation
    # to compare. Collapsing the two would be the error this project keeps
    # refusing elsewhere.
    #
    # This row was checked for "the harness exists and compares nothing", which
    # was true while the port was partial. It is now checked for the thing that is
    # true *instead*, and the limits of that claim are checked with it: an
    # `AGREED` row that did not also say it is not a proof of equivalence would
    # be a table making a stronger claim than the run does.
    assert "MQL5 parity" in rows
    parity = rows["MQL5 parity"]
    assert "Agreed on all 3 cases" in parity, (
        f"the parity row must report the comparison that actually happened; it says "
        f"{parity!r}"
    )
    assert "0.0" in parity, (
        f"the parity row must state the observed deviation, because 'within "
        f"tolerance' and 'exactly zero' are different claims; it says {parity!r}"
    )
    assert "Not a proof of equivalence" in parity, (
        f"an AGREED parity row that does not limit its own claim is the failure "
        f"this guards; it says {parity!r}"
    )
    # Rows whose state is asserted, so a stale table fails here rather than in a
    # reader's head. `MQL5 parity` is deliberately absent from the "shipped" group
    # below: it is a *result*, not a layer, and asserting "Implemented" on it would
    # be the same collapsing the project refuses elsewhere.
    for shipped in ("MT5 adapter", "AI / LLM interface", "MQL5 layer"):
        assert shipped in rows, f"README.md has no {shipped!r} row"
        assert "Implemented" in rows[shipped], (
            f"README.md reports {shipped!r} as {rows[shipped]!r}"
        )
    # `Bilingual documentation` is "Partial", not "Not started": both READMEs and
    # twenty-two algorithm documents exist, and Phase 23 expands them rather than
    # creating them. A third state, and asserting it as either of the other two
    # would be the same collapsing the project refuses elsewhere.
    #
    # The "Not started" group is now **empty**. `MQL5 layer` was its only member
    # and it closed with the port; the loop is kept rather than deleted, because
    # an empty tuple asserts "no row claims to be unstarted" only for as long as
    # someone remembers to add to it.
    for not_started in ():
        assert not_started in rows, f"README.md has no {not_started!r} row"
        assert "Not started" in rows[not_started], (
            f"README.md reports {not_started!r} as {rows[not_started]!r}"
        )
    assert "Partial" in rows["Bilingual documentation"], (
        f"README.md reports bilingual documentation as "
        f"{rows['Bilingual documentation']!r}"
    )

    persian = _text(README_FA)
    for area in ("بک‌تست", "فیکسچرهای طلایی", "قرارداد عدم بازترسیم",
                 "برنامه‌های معاملاتی", "تصمیم‌ها"):
        assert area in persian, f"README_FA.md has no row for {area!r}"
    fa_rows = {
        cells[1].strip(): cells[2].strip()
        for line in persian.splitlines()
        if line.strip().startswith("|")
        for cells in [line.split("|")]
        if len(cells) > 3 and cells[1].strip()
    }
    assert "پیاده‌سازی شده" in fa_rows["آداپتور MT5"], (
        f"README_FA.md still reports the MT5 adapter as {fa_rows['آداپتور MT5']!r}"
    )
    # Same three states as the English table, checked against the Persian one so
    # the two documents cannot drift into saying different things about the same
    # phase.
    # Same split as the English table: the parity harness is built and unfilled,
    # which is neither done nor not-started, and the Persian row has to say so.
    assert "پاریتی MQL5" in fa_rows
    fa_parity = fa_rows["پاریتی MQL5"]
    assert "هیچ مقایسه‌ای انجام نشد" in fa_parity, (
        f"the parity row must say nothing was compared; it says {fa_parity!r}"
    )
    for shipped in ("آداپتور MT5", "رابط AI / LLM"):
        assert shipped in fa_rows, f"README_FA.md has no {shipped!r} row"
        assert "پیاده‌سازی شده" in fa_rows[shipped], (
            f"README_FA.md reports {shipped!r} as {fa_rows[shipped]!r}"
        )
    assert "لایهٔ MQL5" in fa_rows
    assert "شروع نشده" in fa_rows["لایهٔ MQL5"], (
        f"README_FA.md reports the MQL5 layer as {fa_rows['لایهٔ MQL5']!r}"
    )
    assert "ناقص" in fa_rows["مستندات دوزبانه"], (
        f"README_FA.md reports bilingual documentation as "
        f"{fa_rows['مستندات دوزبانه']!r}"
    )


def test_both_readmes_say_implementation_is_not_validation() -> None:
    """The single most important sentence in the project, in both languages.

    A status table saying "Backtesting: Implemented" next to a golden-fixture
    section is exactly the combination that reads as evidence. Both READMEs must
    carry the disclaimer, or a reader of either one is misled.
    """
    assert "not trading validation" in _text(README)
    persian = _text(README_FA)
    assert "اعتبارسنجی معاملاتی نیست" in persian


# --------------------------------------------------------------------------
# No document may describe a completed phase as pending
# --------------------------------------------------------------------------


def test_no_document_describes_a_completed_phase_as_pending_work() -> None:
    """Forward references to finished phases are the main staleness generator.

    An audit found eight, three of them under headings reading *Known
    limitations*, which is the worst place for one: a completed phase listed as a
    live gap invites someone to re-plan work that already shipped.

    The pattern is matched by exact construction rather than by tense, because an
    earlier attempt at the general heuristic flagged seventy legitimate lines on
    its first run. See `FORWARD_REFERENCE`.
    """
    offenders: list[str] = []
    for path in MARKDOWN:
        if path.name in FORWARD_CHECK_EXEMPT:
            continue
        for number, line in enumerate(_text(path).splitlines(), start=1):
            for match in FORWARD_REFERENCE.finditer(line):
                phase = int(next(g for g in match.groups() if g)) if any(
                    match.groups()
                ) else None
                if phase is not None and phase <= LAST_COMPLETE_PHASE:
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
                    break
                if phase is None:
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
                    break

    assert not offenders, (
        "these lines describe completed work as still to do:\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# Every path a document names must exist
# --------------------------------------------------------------------------


def test_every_repository_path_named_in_prose_exists() -> None:
    """A link to a file that is not there is a 404, and a wrong filename is worse
    than no link because it looks authoritative.

    Two were found by the audit and neither was ever fixed: `ROADMAP.md` still
    named `MEASURED_MOVE.md` after the file was renamed to `MEASURED_MOVES.md`, and
    `VALIDATION.md` named `H2_H2_L1_L2.md`, which never existed.
    """
    offenders: list[str] = []
    for path in MARKDOWN:
        if path.name in PATH_CHECK_EXEMPT:
            continue
        for number, line in enumerate(_text(path).splitlines(), start=1):
            for match in REPO_PATH.finditer(line):
                target = match.group(1)
                if any(target.startswith(p) for p in PENDING_PHASE_PATHS):
                    continue
                if not (REPO / target).exists():
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {target}")

    assert not offenders, (
        "these named paths do not exist:\n  " + "\n  ".join(sorted(set(offenders)))
    )


# --------------------------------------------------------------------------
# The docs manifest must match the filesystem
# --------------------------------------------------------------------------


def test_the_required_document_manifest_has_no_orphans_or_ghost_owners() -> None:
    """`check_docs_present.py` is the machine-readable statement of what owes a
    document, and it was twelve entries behind reality.

    An entry in `PENDING_DOCS` for a phase that has finished does not look like a
    bug: it looks like bookkeeping. Its effect is that `--phase 13` fails CI over
    documents that are sitting on disk, which is a failure that means nothing and
    so trains people to ignore the ones that do.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_docs_present", REPO / "scripts" / "check_docs_present.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for path, phase in module.REQUIRED_DOCS:
        assert (REPO / path).is_file(), f"required but missing: {path}"
        assert phase <= IN_PROGRESS_PHASE, (
            f"{path} is required but owned by Phase {phase}, which has not "
            f"started; a required document must be on disk now"
        )

    # Pending means pending. A path in PENDING_DOCS that is already on disk is the
    # exact bookkeeping slip this check exists to catch, in the other direction.
    for path, phase in module.PENDING_DOCS:
        assert phase > LAST_COMPLETE_PHASE, (
            f"{path} is pending but owned by completed Phase {phase}; move it into"
            " REQUIRED_DOCS or a --phase run will fail over a file that exists"
        )
        assert not (REPO / path).exists(), (
            f"{path} is listed as pending but exists; promote it to REQUIRED_DOCS"
        )


# --------------------------------------------------------------------------
# The dataset and the docs agree
# --------------------------------------------------------------------------


def test_every_algorithm_document_on_disk_is_claimed_by_the_manifest() -> None:
    """A document nobody's manifest knows about is a document nobody will keep
    current. `ROADMAP.md` lists 24 phases; the manifest and the filesystem should
    agree on the algorithm docs."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_docs_present2", REPO / "scripts" / "check_docs_present.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    claimed = {p for p, _ in module.REQUIRED_DOCS} | {p for p, _ in module.PENDING_DOCS}
    on_disk = {
        str(p.relative_to(REPO)).replace("\\", "/")
        for p in (REPO / "docs" / "algorithms").glob("*.md")
    }

    assert on_disk <= claimed, f"unclaimed documents: {sorted(on_disk - claimed)}"
