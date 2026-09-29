# Security Policy

## Scope

This project is a price-action **analysis** library. It reads market data and
produces analytical output. It does not execute trades, hold credentials, or
connect to brokers.

## Supported Versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

The project is pre-1.0 and has not had a security audit. Treat it accordingly.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately rather than opening a public
issue. Use GitHub's **"Report a vulnerability"** private advisory form on this
repository.

Include, if possible:

- affected version,
- a minimal reproduction (ideally synthetic bar data),
- the observed vs expected behaviour,
- any suggested remediation.

You can expect an acknowledgement within a week. Fixes for confirmed issues will
be released as a patch version and noted in [CHANGELOG.md](CHANGELOG.md).

## Trust boundaries

When using the MT5 adapter, treat broker credentials and terminal access as
sensitive. Adapter code must never log account credentials, and the core package
must never import terminal-specific modules.

### Credentials are the terminal's, not the library's

`MT5Feed.connect()` accepts a `login` and **no password**. That is deliberate: the
terminal stores credentials encrypted and the library never sees them. A
`password=` parameter would be a small addition and a real downgrade — it would put
broker credentials in this process's memory, in its argument vector, and in any
stack trace. `tests/unit/test_security_review.py` asserts the parameter's absence,
because an absence nobody checks is one a well-meaning feature request adds back.

### The adapter places no orders

No module under `src/` references an order or position API. This is checked over
the source text rather than with a mock: a mock proves only that one test does not
order, whereas the source check proves nothing in the package can.

## Security review

A review was carried out and its findings are recorded here, including the ones
that were clean — a review that reports only problems does not say which properties
were actually checked.

| # | Finding | Severity | State |
|---|---|---|---|
| 1 | **Path traversal in the parity harness.** A case file's `mql5_vector` was joined to a directory and read without checking where it landed, so a case could name any file on disk. | **Medium** | **Fixed** |
| 2 | No order or position API is reachable from `src/`. | — | Confirmed, now asserted |
| 3 | The runtime dependency surface is empty. | — | Confirmed, now asserted |
| 4 | The core never imports the terminal bindings. | — | Confirmed, now asserted |
| 5 | No credentials, keys or tokens anywhere in the repository. | — | Confirmed by scan |
| 6 | The live MT5 suite runs against a real broker account. | — | Confirmed read-only, now asserted |
| 7 | CI actions are pinned to a **major-version tag** (`actions/checkout@v4`) rather than a commit SHA. | **Low** | **Open** — see below |

### Why finding 1 mattered more than an arbitrary read

An arbitrary file read is the ordinary consequence. The consequence that mattered
is the second: the harness exists to answer *"did a real MQL5 run agree with
Python?"*, and it already refuses any vector whose `producer` is not `mql5`. A
path traversal hands the comparator a file that **does** say `"producer": "mql5"`
and was never produced by an MQL5 build — sidestepping the exact refusal the
harness was built around.

The input is a repository-tracked file, so this was not remotely exploitable. But
a pull request is an entirely ordinary way for a hostile case file to arrive, and a
harness that can be talked into a false `MATCH` by one has lost the property it
exists to provide. The fix resolves the path and requires it to be inside the
vectors directory, which also covers a symlink pointing out of it.

### Finding 7, and why it is left open

Pinning a third-party action to a tag rather than a commit SHA means trusting that
the tag is never moved. A compromised action repository could publish a new `v4`
and this workflow would run it. SHA pinning removes that trust.

It is left as recorded rather than fixed because the trade-off is a real
maintenance cost — every action bump becomes a two-step — and this repository's
risk profile does not obviously justify it. A reviewer who disagrees can change
three lines.

## Not a security boundary

Signal output from this library is **not** financial advice and carries no
guarantee. See the disclaimer in [README.md](README.md).
