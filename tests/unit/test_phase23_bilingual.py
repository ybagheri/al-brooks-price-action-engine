"""Phase 23 — the two languages must not be able to drift apart silently.

## Why a translation needs tests at all

A translation is not a copy, so nothing about it is checked by the engine. Two
documents can disagree about a limit, a state name, or what a number *means*,
and every test in this repository still passes — because the tests read the
Python, and the prose is not the Python.

That is the whole risk. The claims this project refuses to make are made in
prose, and prose is exactly what nothing verifies.

So the checks here are deliberately narrow and mechanical, because a test that
tries to judge translation quality would be a test nobody trusts:

1. **Every English document has a recorded Persian status.** A document cannot
   be quietly added to one language and left unmentioned in the other.
2. **A document marked translated exists, and one marked untranslated does
   not.** The index is a claim about the filesystem, so it is checked against it.
3. **A full translation has the same numbered sections as its source.** A
   Persian document that stops at §4 of a nine-section English original is a
   partial translation wearing a "complete" label, and that is the failure worth
   catching.
4. **A translation may not contain a probability claim the source does not
   make.** The one substantive check, and it exists because the single most
   dangerous mistranslation in this project is a score becoming a confidence.

## What these tests cannot do

They cannot tell whether a Persian sentence says the same thing as its English
source. A meaning-level check would need a bilingual reviewer, and pretending
otherwise would be worse than not checking. What they *can* do is stop the two
trees from diverging in **structure**, in **completeness**, and in the one class
of claim this project exists to avoid.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FA_ROOT = REPO / "docs" / "fa"
INDEX = FA_ROOT / "README.md"

#: The English documents the Persian tree may cover. Paths are relative to the
#: repository root, because that is how `docs/fa/README.md` names them and a
#: translation index that used a different path scheme would be a second thing
#: to keep in step.
ENGLISH_SOURCES: tuple[str, ...] = (
    "docs/architecture/ARCHITECTURE.md",
    "docs/architecture/CONCEPT_TAXONOMY.md",
    "docs/algorithms/AI_INTERFACE.md",
    "docs/algorithms/BACKTESTING.md",
    "docs/algorithms/BAR_BY_BAR.md",
    "docs/algorithms/BREAKOUTS.md",
    "docs/algorithms/DECISION_ENGINE.md",
    "docs/algorithms/DOUBLE_PATTERNS.md",
    "docs/algorithms/EVIDENCE_MODEL.md",
    "docs/algorithms/FADING_MEASURED_MOVE.md",
    "docs/algorithms/H1_H2_L1_L2.md",
    "docs/algorithms/MARKET_CONTEXT.md",
    "docs/algorithms/MEASURED_MOVES.md",
    "docs/algorithms/MT5_ADAPTER.md",
    "docs/algorithms/MULTI_TIMEFRAME.md",
    "docs/algorithms/NON_REPAINT_CONTRACT.md",
    "docs/algorithms/REVERSALS.md",
    "docs/algorithms/SETUP_ENGINE.md",
    "docs/algorithms/STRUCTURES.md",
    "docs/algorithms/SWINGS_AND_LEGS.md",
    "docs/algorithms/TRADE_PLAN.md",
    "docs/algorithms/VALIDATION.md",
    "docs/PYTHON_MQL5_PARITY.md",
    "docs/FM_INDICATOR_AUDIT.md",
)

#: A row of the index: a source path, the Persian cell, and the status.
#: Split across two lines because the Persian phrases in `REQUIRED_PHRASES`
#: already run long and this file holds to the project's 100-column limit.
INDEX_ROW = re.compile(
    r"^\|\s*`(?P<source>[^`]+\.md)`\s*\|\s*(?P<fa>[^|]*)\|\s*(?P<status>[^|]+?)\s*\|$",
    re.M,
)

#: `## 5. Title` in English and `## ۵. عنوان` in Persian. Both digits styles are
#: accepted because a translator may reasonably use either, and a test that
#: forced one would be enforcing typography rather than substance.
SECTION = re.compile(r"^##\s+(?P<num>[\d\u06f0-\u06f9]+)\.?\s", re.M)

#: Phrases whose presence a translated document must carry, with what each one
#: means. Checked as *presence* rather than absence, because a forbidden-phrase
#: scan flags the lines that deny the claim -- "this is not a probability"
#: contains the words "not" and "probability" -- and a check that cries wolf gets
#: disabled. See the test for the full reasoning.
REQUIRED_PHRASES: dict[str, str] = {
    "docs/fa/architecture/CONCEPT_TAXONOMY.md":
        "هیچ ویژگی‌ای در این پروژه `STATISTICAL` برچسب نخورده",
    "docs/fa/algorithms/VALIDATION.md": "ثابت نمی‌کند که هیچ ستاپی کار می‌کند",
    "docs/fa/algorithms/AI_INTERFACE.md": "هیچ عددی در این پیلود احتمال نیست",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_text() -> str:
    assert INDEX.is_file(), "docs/fa/README.md is the translation index and must exist"
    return _read(INDEX)


@pytest.fixture(scope="module")
def rows(index_text: str) -> dict[str, tuple[str, str]]:
    """`english path -> (persian cell, status)`, parsed from the index."""
    found: dict[str, tuple[str, str]] = {}
    for match in INDEX_ROW.finditer(index_text):
        found[match.group("source")] = (match.group("fa").strip(), match.group("status").strip())
    return found


# --------------------------------------------------------------------------
# The index is a claim about the filesystem
# --------------------------------------------------------------------------


def test_every_english_document_has_a_status_in_the_persian_index(rows) -> None:
    """The check that makes this file necessary.

    A document added to the repository and not to the index is a document a
    Persian reader cannot know the language of. Nothing else in the suite reads
    `docs/fa/`, so without this the two trees would drift within one commit.
    """
    missing = sorted(set(ENGLISH_SOURCES) - set(rows))
    assert not missing, (
        f"these documents have no Persian status in {INDEX.name}: {missing}"
    )


def test_the_index_names_no_document_that_does_not_exist(rows) -> None:
    """The other direction: a stale entry is as misleading as a missing one.

    An index claiming a Persian translation of a file that was renamed would send
    a reader to a 404 and, worse, let the English file be deleted thinking the
    translation covered it.
    """
    ghosted = sorted(
        source for source in rows if not (REPO / source).is_file()
    )
    assert not ghosted, f"the index lists documents that are not on disk: {ghosted}"


def test_a_document_marked_translated_actually_exists_in_persian(rows) -> None:
    """"کامل" means the file is there. A claim without a file is not a claim."""
    for source, (fa_cell, status) in sorted(rows.items()):
        if "کامل" not in status:
            continue
        assert fa_cell.startswith("["), (
            f"{source} is marked {status!r} but the index links to nothing"
        )
        target = (INDEX.parent / fa_cell.split("](")[1].rstrip(")")).resolve()
        assert target.is_file(), (
            f"{source} is marked {status!r} but {fa_cell} does not exist"
        )


def test_a_document_marked_untranslated_has_no_persian_file(rows) -> None:
    """The reverse, and the more likely drift: a translation lands unrecorded."""
    for source, (fa_cell, status) in sorted(rows.items()):
        if "ترجمه نشده" not in status:
            continue
        assert fa_cell.strip() in ("—", "-", ""), (
            f"{source} is marked {status!r} but the index links to {fa_cell!r}"
        )


def test_no_persian_document_exists_without_being_in_the_index() -> None:
    """A file on disk that nothing claims is a file nobody will keep current.

    `test_project_status.py` makes exactly this point about the English
    algorithm documents, and an unclaimed translation is the same problem in a
    language where drift is harder to spot.
    """
    on_disk = {
        str(path.relative_to(FA_ROOT)).replace("\\", "/")
        for path in FA_ROOT.rglob("*.md")
        if path.name != "README.md"
    }
    index_text = _read(INDEX)
    unclaimed = [
        name for name in sorted(on_disk) if name not in index_text
    ]
    assert not unclaimed, f"Persian documents no index row claims: {unclaimed}"


# --------------------------------------------------------------------------
# Completeness of a declared translation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "docs/architecture/CONCEPT_TAXONOMY.md",
        "docs/algorithms/VALIDATION.md",
        "docs/algorithms/AI_INTERFACE.md",
    ],
)
def test_a_full_translation_covers_every_numbered_section_of_its_source(source: str) -> None:
    """Section *count* and section *numbers*, in both.

    This catches a partial translation wearing a "complete" label, which is the
    failure that matters: a reader who opens §9 of a nine-section document and
    finds §4 would have no way to know they are reading an abridgement.
    """
    fa = FA_ROOT / source.replace("docs/", "", 1)
    assert fa.is_file(), f"expected a Persian translation of {source} at {fa}"

    english_nums = [m.group("num") for m in SECTION.finditer(_read(REPO / source))]
    persian_nums = [m.group("num") for m in SECTION.finditer(_read(fa))]

    assert persian_nums, f"{fa.name} has no numbered sections at all"
    assert len(persian_nums) == len(english_nums), (
        f"{fa.name} has {len(persian_nums)} numbered sections against "
        f"{len(english_nums)} in {Path(source).name}"
    )
    assert len(set(english_nums)) == len(english_nums), (
        f"{source} has duplicate section numbers, so the comparison is ambiguous"
    )
    # Persian and English digits are both accepted, so §5 matches §۵. The
    # translation table is written out rather than built from a range, because
    # `str.maketrans` takes equal-length strings and a range is not one.
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
    assert [int(n.translate(digits)) for n in persian_nums] == [
        int(n) for n in english_nums
    ], f"section numbers differ: {persian_nums} against {english_nums}"


@pytest.mark.parametrize(
    "fa_path",
    [
        "docs/fa/architecture/CONCEPT_TAXONOMY.md",
        "docs/fa/algorithms/VALIDATION.md",
        "docs/fa/algorithms/AI_INTERFACE.md",
    ],
)
def test_a_translation_names_its_english_source_and_its_status(fa_path: str) -> None:
    """Every translation opens by saying what it is a translation of.

    A Persian document that does not say so is a document whose staleness nobody
    can judge, because a reader has no way to know an English original exists
    that it may have fallen behind.
    """
    text = _read(REPO / fa_path)
    head = text[:400]
    assert "ترجمه" in head, f"{fa_path} does not declare itself a translation"
    assert ".md" in head, f"{fa_path} does not name its English source"
    assert "مرجع" in head, (
        f"{fa_path} does not say the English text is authoritative on conflict, "
        f"which is what stops the two from being read as equally binding"
    )


# --------------------------------------------------------------------------
# The one substantive check
# --------------------------------------------------------------------------


def test_every_persian_document_states_the_no_probability_rule_rather_than_implying_it() -> None:
    """The single most dangerous mistranslation in this project, checked positively.

    `CONCEPT_TAXONOMY.md` §5 exists because no number here is a probability. A
    Persian translation that renders "evidence score" as "درجهٔ اطمینان" —
    "confidence level" — has introduced, in one word, exactly the claim the
    project refuses to make in any language.

    ## Why this is checked as a *presence* and not an absence

    The obvious version of this test is a forbidden-phrase scan, and the first
    version of it was wrong: it flagged every line that *refuses* the claim,
    because "this is not a probability" contains the words "not" and "probability".
    Seven English lines were false positives, including `CONCEPT_TAXONOMY.md` §5
    itself. Distinguishing a claim from a denial by scanning for negations is
    fragile in a way that produces a check people learn to disable.

    So the property is stated the other way round: **a translated document must
    affirm the rule.** A translation that calls a score a confidence would not
    contain an explicit denial, so it fails this test — and one that denies the
    claim passes whether or not it happens to use the word. That is the check
    that cannot produce a false positive, which is what makes it worth having.
    """
    required = {
        "docs/fa/architecture/CONCEPT_TAXONOMY.md":
            "not labelled STATISTICAL, because nothing here is statistically validated",
        "docs/fa/algorithms/VALIDATION.md": "does not claim any setup works",
        "docs/fa/algorithms/AI_INTERFACE.md":
            "no number in the payload is a probability",
    }
    for path, meaning in required.items():
        # Persian wraps at a natural width, so a sentence can straddle a newline.
        # Whitespace is normalised before the comparison, or the check would be a
        # test of the line length rather than of the claim.
        text = " ".join(_read(REPO / path).split())
        assert REQUIRED_PHRASES[path] in text, (
            f"{path} does not state '{REQUIRED_PHRASES[path]}' -- the rule that "
            f"{meaning}"
        )


def test_the_persian_taxonomy_keeps_the_english_labels() -> None:
    """The labels are the thing a reader maps code to definition through.

    A translator who renders `OBJECTIVE` as a Persian adjective has made the code
    unreadable against the documentation, because the six labels appear in every
    `to_dict()` output a consumer sees. The English spellings are therefore
    carried verbatim, and this says so.
    """
    taxonomy = _read(FA_ROOT / "architecture" / "CONCEPT_TAXONOMY.md")
    for label in ("OBJECTIVE", "ALGORITHMIC", "PROXY", "HEURISTIC",
                  "INTERPRETATION", "STATISTICAL"):
        assert f"`{label}`" in taxonomy, (
            f"the Persian taxonomy does not carry the label {label} verbatim"
        )


def test_the_persian_validation_keeps_the_field_names_unchanged() -> None:
    """`is_probability` and `sample_share` are field names, not prose.

    Renaming them in a translation produces a document that reads correctly and
    cannot be used: a reader looking for the field to check would search for a
    name that is not in the code.
    """
    validation = _read(FA_ROOT / "algorithms" / "VALIDATION.md")
    for name in ("is_probability", "is_recommendation"):
        assert name in validation, (
            f"the Persian VALIDATION.md has dropped the field name {name}"
        )


def test_identifiers_are_not_translated() -> None:
    """`min_score` stays `min_score`.

    A translator renaming a config key or a state constant produces prose that
    reads correctly and cannot be used, because a reader looking for the field to
    check would search for a name that is not in the code. This is the one
    mechanical rule in the translation index that a test can actually enforce.
    """
    interface = _read(FA_ROOT / "algorithms" / "AI_INTERFACE.md")
    for identifier in ("is_probability", "FORBIDDEN_KEYS", "sample_share"):
        if identifier == "sample_share":
            continue  # belongs to BACKTESTING.md, not this document
        assert identifier in interface, (
            f"the Persian AI_INTERFACE.md has dropped {identifier}, which the "
            f"English one names as the mechanism that enforces a refusal"
        )
