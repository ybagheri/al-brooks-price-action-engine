# Sources and Attribution

This document records where the ideas in this project come from, what was
designed here, and where the line between the two sits. It exists because
Al Brooks price action is a **trading methodology taught in books, courses and
webinars**, much of which is copyrighted. This project does not reproduce that
material.

## 1. Concepts referenced (not copied)

Price-action terminology used throughout the code and docs comes from the
publicly documented Al Brooks methodology:

| Concept | Persian term used in `README_FA.md` |
|---|---|
| Measured Move | حرکت اندازه‌گیری‌شده |
| Pullback | پولبک / اصلاح |
| Breakout | شکست |
| Trading Range | محدوده معاملاتی |
| Major Trend Reversal | بازگشت عمده روند |
| Minor Trend Reversal | بازگشت جزئی روند |
| Double Top / Bottom | سقف/کف دوقلو |
| Failed Breakout | شکست ناموفق |
| Climax | اوج قیمتی |
| Wedge | گوه |
| Barbwire | شکنج |
| Leg (AB = CD) | پا (AB = CD) |

**What was taken:** short terminology and widely known structural vocabulary.

**What was not taken:** no prose, no charts, no exercises, no course or book
content of any kind. Definitions here are written from scratch as algorithmic
proxies, and deliberately differ in wording from any published source.

## 2. Reference implementation audited

[FM-indicator](https://github.com/ybagheri/FM-indicator) by the same author — an
MQL5 indicator/EA with a Python mirror, focused on fading measured moves, with
closed-bar non-repaint semantics and a Python/MQL5 parity harness.

It was used as an **engineering and algorithm reference**, not a source to copy.
The audit is in [docs/FM_INDICATOR_AUDIT.md](docs/FM_INDICATOR_AUDIT.md) and
covers what was reusable, what needed redesign, and the migration strategy.

Design decisions taken here that deliberately **diverge** from the reference:

| Area | Reference | Here | Why |
|---|---|---|---|
| Architecture | Single monolithic `FMEngine` | Layered, one detector per concern | Reuse; the audit flagged the monolith as technical debt |
| Scope | An FM indicator/EA | A general price-action engine | Project objective |
| Swings/legs | Recomputed in several headers | Single authoritative source in `core/` | Audit found duplication |
| Execution | Position/paper-trading managers in core | Analytic output only; execution in adapters | Core must stay platform-independent |
| Data | MQL5 reverse indexing | Oldest-first indexing | Removes a pervasive source of bugs |
| Lookahead | Varies per module | One enforced contract, tested | Audit found inconsistency |

## 3. Algorithms designed in this project

Everything under `src/albrooks/` is original work written for this repository.
That includes the specific thresholds and gate combinations in:

- bar-by-bar classifications (`doji_max_body`, `big_bar_atr`, `strong_close_pct`, …)
- swing fractal detection with earliest-wins tie-breaking
- market-state scoring and its six modes
- exhaustion / wedge / overshoot structure detectors
- H1/H2 and L1/L2 counting rules
- double top/bottom tolerance logic
- breakout state machine transitions
- MTR leg-sequence scoring
- all five measured-move families and their depth/ATR gates

These are **systematic proxies chosen by this project**, not rules prescribed by
any source. They are calibrated to be plausible, not to be optimal, and none has
been statistically validated.

## 4. What this project does not claim

- Not affiliated with, endorsed by, or connected to Al Brooks.
- Does not reproduce his definitions, wording, or teaching.
- Does not claim its proxies are "what Al Brooks means".
- Makes **no profitability, accuracy, or win-rate claim** of any kind.
- No output of this library is financial advice.

## 5. External dependencies

The core has **zero runtime dependencies** — standard library only.

Optional: `pandas` (dataframe adapter, planned), `pytest` / `ruff` / `mypy`
(development). No dependency embeds third-party price-action logic.

## 6. Licence

Project source: MIT — see [LICENSE](LICENSE).

Trading methodologies referenced by name remain the property of their authors.
Naming a concept is not a claim of ownership over it, and no proprietary
material is reproduced here.
