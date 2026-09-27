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

When using the MT5 adapter (planned), treat broker credentials and terminal
access as sensitive. Adapter code must never log account credentials, and the
core package must never import terminal-specific modules.

## Not a security boundary

Signal output from this library is **not** financial advice and carries no
guarantee. See the disclaimer in [README.md](README.md).
