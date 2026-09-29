"""Security review findings, enforced as tests.

## Why this file exists

A security review found one real issue and confirmed several non-issues. Findings
that are fixed belong in the code; findings that are *structural properties* --
"this never happens" -- belong in the suite, because a property nothing checks is
a property that erodes when someone adds a feature.

Each test below corresponds to a finding in `SECURITY.md`'s trust boundaries, and
each says what the finding was so a future reader can tell a checked property from
an assumption.

## What is deliberately NOT tested here

There is no test that the adapter cannot place an order. That is enforced by
absence -- no order API is called anywhere in `src/` -- and a test asserting an
absence is what `test_no_order_api_is_referenced_anywhere` does, mechanically,
against the source text rather than against a mock.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.parity.contract import PRODUCER_MQL5, dump, envelope
from tests.parity.runner import CASE_ERROR, MQL5_ABSENT, ParityCase, run_case

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "albrooks"
VECTORS = REPO / "tests" / "parity" / "mql5"


# --------------------------------------------------------------------------
# Finding 1 -- path traversal in the parity harness. FIXED.
# --------------------------------------------------------------------------


def _case(mql5_vector: str) -> ParityCase:
    return ParityCase(
        id="probe",
        intent="a synthetic case for the traversal check",
        spec="docs/PYTHON_MQL5_PARITY.md",
        config={},
        last_closed=0,
        bars=({"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0},),
        mql5_vector=mql5_vector,
        path=Path("synthetic"),
    )


@pytest.mark.parametrize(
    "name",
    [
        "../../../pyproject.toml",
        "../../../README.md",
        "../cases/parity_trend_001.json",
        "..\\..\\SOURCES.md",
        "/etc/passwd",
    ],
)
def test_a_sidecar_may_not_be_named_outside_the_vectors_directory(name: str) -> None:
    """A case file's `mql5_vector` cannot escape the vectors directory.

    ## What the finding was

    `run_case()` joined `vectors_dir / case.mql5_vector` and read whatever came
    out, so a case file could name any path on disk. Verified before the fix:
    `../../../README.md` and `../../../pyproject.toml` were both read and parsed.

    ## Why it mattered more than an ordinary traversal

    An arbitrary read is the ordinary consequence. The one that mattered is the
    second: the harness exists to answer *"did a real MQL5 run agree with
    Python?"*, and it already refuses any vector whose `producer` is not `mql5`.
    A traversal hands the comparator a file that **does** say
    `"producer": "mql5"` and was never produced by an MQL5 build — sidestepping
    the exact refusal the harness was built around.

    The input is a repository-tracked file, so this was not remotely
    exploitable. But a pull request is an entirely ordinary way for a hostile case
    file to arrive, and a harness that can be talked into a false `MATCH` by one
    has lost the property it exists to provide.
    """
    result = run_case(_case(name), VECTORS)
    assert result.status in (CASE_ERROR, MQL5_ABSENT)
    assert "resolves outside" in result.note, (
        f"{name!r} was not refused as a traversal: {result.status} / {result.note!r}"
    )


def test_a_legitimate_sidecar_name_still_resolves(tmp_path: Path) -> None:
    """The fix must not break the normal case.

    A containment check that also refused in-directory names would make the
    harness refuse every sidecar ever written, and a security fix that breaks the
    feature is not a fix.
    """
    vectors = tmp_path / "mql5"
    vectors.mkdir()
    payload = envelope("probe", {"last_closed_bar": 0}, PRODUCER_MQL5, "build 4700")
    (vectors / "probe.mql5.json").write_text(dump(payload), encoding="utf-8")

    result = run_case(_case("probe.mql5.json"), vectors)
    # Compared, not refused for its path. It disagrees on every missing field,
    # which is a different and correct outcome.
    assert "resolves outside" not in result.note
    assert result.status != CASE_ERROR or "resolves outside" not in result.note


def test_a_symlink_out_of_the_vectors_directory_is_also_refused(tmp_path: Path) -> None:
    """Resolving before comparing is what makes the check cover symlinks.

    A plain string check on `..` components would miss a symlink sitting *inside*
    the directory that points out of it. Comparing resolved paths closes that too,
    and this is the test that says so.
    """
    outside = tmp_path / "outside.json"
    outside.write_text(
        dump(envelope("probe", {}, PRODUCER_MQL5, "x")), encoding="utf-8"
    )
    vectors = tmp_path / "mql5"
    vectors.mkdir()
    link = vectors / "link.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        # Windows requires SeCreateSymbolicLinkPrivilege, so this skips for an
        # unprivileged user. Stated rather than left as a bare skip: a test that
        # has never run is not a guard, and pretending otherwise is the failure
        # mode this project keeps refusing elsewhere.
        #
        # The property still holds without this test, because the check resolves
        # *before* comparing, and resolving follows symlinks. The `..` cases above
        # exercise that same code path on every platform; only the symlink
        # entry-point into it is unverified here.
        pytest.skip(f"symlinks need an elevated privilege on this platform ({exc})")

    result = run_case(_case("link.json"), vectors)
    assert "resolves outside" in result.note


# --------------------------------------------------------------------------
# Finding 2 -- no order API is reachable. STRUCTURAL.
# --------------------------------------------------------------------------


def test_no_order_api_is_referenced_anywhere_in_src() -> None:
    """The adapter reads bars and nothing else, checked against the source text.

    `ROADMAP.md` and `SECURITY.md` both claim the project places no orders. That
    claim is about the whole package, so it is checked over the whole package
    rather than over a mock — a mock would only prove that one test does not order,
    which is a much weaker statement than "nothing in the library can".

    A mock-based version of this test is the obvious alternative and the wrong
    one: it passes whenever nobody happens to call the mocked method, and it keeps
    passing if someone later calls the real one from a path the test does not
    exercise.
    """
    forbidden = (
        "order_send", "orders_get", "positions_get", "deal_add",
        "OrderSend", "PositionSelect", "CTrade",
    )
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            if re.search(rf"\b{name}\b", text):
                offenders.append(f"{path.relative_to(REPO)}: {name}")
    assert not offenders, f"src/ references an order or position API: {offenders}"


def test_the_adapter_takes_no_password() -> None:
    """`MT5Feed.connect()` accepts a `login` and no password, on purpose.

    Credential handling is the terminal's job: it stores them encrypted and the
    library never sees them. A `password=` parameter would be a small addition
    and a real downgrade — it would put broker credentials in this process's
    memory, in this process's argument vector, and in any stack trace.

    Asserted because the parameter is *absent*, and an absence nobody checks is
    one that a well-meaning feature request adds back.
    """
    source = (SRC / "adapters" / "mt5" / "feed.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    connect = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "connect"
    )
    args = [a.arg for a in connect.args.args + connect.args.kwonlyargs]
    assert "login" in args
    for banned in ("password", "passwd", "secret", "token", "api_key"):
        assert banned not in args, (
            f"MT5Feed.connect() now takes {banned!r}; the terminal owns credential "
            f"storage and the library should not hold secrets at all"
        )


def test_the_core_never_imports_the_terminal_bindings() -> None:
    """The architecture rule, checked over source rather than trusted to CI.

    `scripts/check_no_mt5_dependency.py` runs in CI, but a reader of this file
    should not have to go and run it to learn that the core is platform-free. The
    check is here too, over the same tree, because "the CI job would catch it" is
    a weaker statement than "it is not like this".
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("adapters/mt5"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            if "MetaTrader5" in names:
                offenders.append(rel)
    assert not offenders, f"core modules import the terminal bindings: {sorted(set(offenders))}"


# --------------------------------------------------------------------------
# Finding 3 -- the runtime dependency surface is empty.
# --------------------------------------------------------------------------


def test_the_package_declares_no_runtime_dependencies() -> None:
    """A zero-dependency core is a supply-chain property, so it is asserted.

    Every runtime dependency is code this project does not control, running with
    the library's privileges, in every consumer's process. The count is the
    security property, so it is checked rather than described.
    """
    import tomllib

    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    assert project["dependencies"] == [], (
        f"the core now declares runtime dependencies {project['dependencies']}; "
        f"a zero-dependency core is a supply-chain property, not a preference"
    )
    # Development and optional extras are a different matter and are permitted.
    for extra in pyproject["project"].get("optional-dependencies", {}).values():
        assert all("@" not in dep or "://" in dep for dep in extra), (
            "an unpinned dependency was added to an extra"
        )


def test_the_live_terminal_suite_touches_no_ordering_api() -> None:
    """The live suite runs against a real broker account. It stays read-only.

    This is the finding with the largest potential blast radius: the Phase 21 live
    tests connect to an actual MT5 installation, so a future change that placed an
    order there would act on a real account. The suite is read-only today
    (`copy_rates_from_pos` and `symbol_info_tick` only), and this makes that a
    checked property of the file rather than a claim in its docstring.
    """
    source = (REPO / "tests" / "integration" / "test_phase21_live_mt5.py").read_text(
        encoding="utf-8"
    )
    for name in ("order_send", "positions_get", "orders_get", "CTrade", "trade_allowed"):
        assert not re.search(rf"\b{name}\b", source), (
            f"the live MT5 suite references {name}; it runs against a real terminal "
            f"and must stay strictly read-only"
        )
    # And the APIs it does use are the read-only ones.
    for allowed in ("copy_rates_from_pos", "symbol_info_tick", "terminal_info"):
        assert allowed in source
