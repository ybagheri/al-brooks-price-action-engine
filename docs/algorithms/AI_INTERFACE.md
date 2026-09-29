# AI / LLM Interface

A stable JSON serialization for a language model, and the reasoning about what a
model must never be handed.

`src/albrooks/serialization/json.py` · `examples/llm_analysis.py` ·
`tests/unit/test_phase22_serialization.py`

## 1. What this is

Two functions, and a decision between them.

| Function | What it is | When to use it |
|---|---|---|
| `canonical(result)` | the whole result, deterministic, nothing dropped | diffing, regression, a complete record |
| `brief(result, budget=…)` | the LLM-facing reduction, labelled and self-reporting | handing a reading to a model |
| `to_prompt(result, …)` | `brief()` plus instructions, as one text block | a chat completion |

All three produce **byte-identical output for the same analysis**, which is what
makes any of them regression-testable at all.

## 2. Why a reduction, stated as a measurement

`AnalysisResult.to_dict()` for a 60-bar series is **73,769 characters**, and
**88.9% of that is `bar_features`** — 28 numeric fields for every single bar. A
model handed that spends nearly all its attention on per-bar arithmetic it does
not need, and almost none on the decision, the plan, or the reasons.

The reduction is not a guess about what a model needs. It is measured:

| | chars | tokens (est.) |
|---|---|---|
| `canonical` | 73,769 | ~18,400 |
| `brief(budget=8000)` | 6,384 | **~1,600** |
| reduction | **91.3%** | **~16,800 saved** |

`examples/llm_analysis.py` prints this table, so the claim is checkable rather
than asserted.

## 3. Why an LLM is the riskiest consumer in this project

Everything else in the repository talks to a programmer who can read
`CONCEPT_TAXONOMY.md`. A model cannot, and it will produce a confident answer
from a correct payload.

The specific failure: handed `{"action": "BUY", "evidence_score": 0.85}`, a model
reads a probability — because that is what those shapes mean everywhere else. It
is not. `CONCEPT_TAXONOMY.md` §5 classifies **no** value here as `STATISTICAL`,
because nothing in this project has been validated against outcomes, and
`VALIDATION.md` §9 lists the four missing ingredients (real data, a labelled
sample with stated provenance, out-of-sample, and **a stated null**).

So the interface is built to make misreading *structurally hard* rather than
merely discouraged. Four mechanisms, each tested.

### 3.1 No score leaves as a bare number

Every quantity that could be misread is an object:

```json
"evidence": {
  "value": 1.0,
  "is_probability": false,
  "means": "mean of observed evidence-factor weights, balanced per source; a checklist average, not a likelihood"
}
```

The awkwardness is the design. There is no `0.85` sitting alone for a model to
pattern-match, and the sentence travels **at the point of use** rather than in a
preamble that gets skipped. `_scored()` is the only way to build one.

A test walks the whole payload and asserts that no number appears under a
score-like key unless its parent carries a label — so a section added later is
covered by construction.

### 3.2 The refusals are structural, not documentary

`FORBIDDEN_KEYS` refuses `confidence`, `probability`, `win_rate`, `winrate`,
`expectancy`, `profit_factor`, `sharpe`, `pnl`, `equity` and `balance` at **any
depth**, and `_assert_refusals()` runs on **every** `brief()` call — not only in
tests. A field cannot be added later without a caller meeting it.

The suite tests the guard for **every key in the list**, plus a nested, a
list-contained and a renamed variant, and then proves it fires against real
output by injecting a simulated future `confidence` field into `_decision()` and
watching `brief()` refuse. A guard that has never failed is indistinguishable from
a guard that cannot fail.

This is the same pattern `test_phase18_backtesting.py` uses on the backtest
module, and for the same reason.

### 3.3 The caveats cannot be dropped

`CAVEATS` ships in every brief with **no flag to suppress it**. A reader who does
not know these will read the numbers correctly and still be misled, so they belong
in the payload rather than in the prose around it. A test asserts the specific
misreadings are addressed — probability, unvalidated, not-a-recommendation,
closed-bar, not-advice — not merely that some caveats exist.

`PROVENANCE` adds `is_validated: false`, `is_a_recommendation: false`,
`is_financial_advice: false` and `closed_bar_only: true`, explicitly `False`
rather than absent, because absence is ambiguous and a reader is most likely to
check exactly these.

### 3.4 A reduction says so

Dropping 89% of a payload is a material change to what the reader is looking at.
`truncated` is present on **every** call, listing each dropped section with a
reason and an item count:

```json
"truncated": {
  "dropped": [{"section": "bar_features", "items": 60, "reason": "89% of the raw payload and the least load-bearing part of it; per-bar arithmetic a decision does not depend on"}],
  "char_budget": 8000,
  "char_used": 6384
}
```

An **empty** `dropped` list is still a claim — "nothing was dropped" — and is
tested as such, because omitting the section when empty would make a reader unable
to distinguish "nothing to drop" from "this implementation does not report
truncation".

## 4. What survives the budget, and what does not

**Kept whatever the budget**, because each answers a question about the *reading*
rather than about the market:

| Kept | Why |
|---|---|
| `caveats`, `produced_by` | the framing; a budget that removed them would be the worst possible failure |
| `decision` + `reason` | the answer, and *why* — the project's whole point |
| `trade_plan` | the geometry, with every level's basis |
| `market_state` | the context every gate is conditioned on |
| `warnings` | what the engine noticed and did **not** act on — the only record it was noticed |
| `swings` (recent) | where the structures are |

**Dropped in this order**, so the least load-bearing goes first:

| Order | Dropped | Why |
|---|---|---|
| 1 | `bar_features` | 89% of the payload, and per-bar arithmetic a decision does not depend on |
| 2 | `trends`, `channels` | derived from `market_state`, which is kept |
| 3 | `evidence` factors | the score itself is kept and labelled |
| 4 | `legs` | the recent structures are kept |
| 5 | `setups`, `measured_moves` | the chosen candidate's plan is kept |
| 6 | `detectors`, `unimplemented_layers` | visible elsewhere; usually empty |

**Sections are dropped whole.** A reduction that truncated a string or a number to
fit would produce a payload that is *wrong* rather than incomplete, and
incompleteness is at least detectable. A test asserts every dropped section is
absent from the output and that survivors are structurally whole.

## 5. Prices are not rounded

The fixture's stop is `106.68656533354194`. Rounding that to 2dp — the obvious
"make it readable" move — moves the stop through the level it was protecting.
So `float_digits` is **not** the default, and when used it records
`{"is_lossy": true}` in the output. Display rounding is available; arithmetic
rounding is not, and the two are not the same operation.

## 6. Prose is off by default

`explanation` is a list of English sentences. A model handed a paragraph will
quote the paragraph verbatim and at length; the **reason code** says the same
thing in one token and constrains it properly. `include_explanation=True` exists
for a caller who wants the sentences, off by default.

`vetoes` are kept even though they are structured, because each one names a
`config_key` — so a reader can see *which setting* to turn rather than only what
failed.

## 7. The instructions come after the data, deliberately

`to_prompt()` appends its instructions **after** the JSON block. A model reads the
data first and the framing second, so framing placed first would have to compete
for attention with 6,000 characters of numbers. Placed last, it is the final
thing in the context — the position recency favours.

The instructions are four refusals, not four instructions:

- asked for a percentage chance → say the project is unvalidated and the number is
  a factor average;
- `action` is a ranking under declared criteria, not advice;
- do not add a stop, target, size or entry that is not in the payload;
- if something is missing, say it is missing — `truncated` records what was dropped.

`include_instructions=False` exists for a caller with its own system prompt.

## 8. The token estimate is labelled as an estimate

There is no tokenizer here and no dependency may be added, so `estimate_tokens()`
uses `CHARS_PER_TOKEN = 4` — reasonable for English and JSON, poor for code or
Persian text. A caller who needs a real count must measure it. The alternative
would be a number here that looks like tokens and is not.

## 9. The schema version is separate from the parity contract

`SCHEMA_VERSION = "albrooks-llm/1"`, deliberately **not** shared with the parity
harness's `albrooks-parity/1`. That one is a two-implementation comparison
contract with per-field tolerance classes; this one is a single-implementation
payload for a reader. They will drift, and sharing a version string would make
"the fields moved" indistinguishable from "the market moved". A test asserts the
two are distinct.

## 10. What this interface will not do

| Refused | Why |
|---|---|
| Any field readable as a probability | `VALIDATION.md` §9 is what would change this, not a new key |
| `confidence`, `pnl`, `win_rate`, `expectancy`, `profit_factor` | claims about outcomes, refused mechanically at any depth |
| Suppressing the caveats | a reader who does not know them will still be misled |
| Silent truncation | a reduction that did not report itself would be a quiet lie |
| Rounding prices by default | can move a stop through the level it protects |
| Any model call in `examples/` | the testable part is the payload's shape; a call would add a key, a network and a mood |

There is also **no "summary" or "signal" field** on purpose. The engine's
decision is a ranking under declared criteria; anything a consumer would call
"the signal" would be an interpretation this project has not earned, and
`ROADMAP.md` records that the ranking is not an edge.

## 11. Usage

```python
from albrooks.core.bars import BarSeries
from albrooks.engine.analyzer import Analyzer
from albrooks.serialization.json import brief, canonical, to_prompt

result = Analyzer().analyze(BarSeries(bars), symbol="EURUSD", timeframe="M15")

canonical(result)                      # 73,769 chars, deterministic, complete
brief(result)                          # 6,384 chars, labelled, self-reporting
brief(result, budget=2000)             # smaller; `truncated` says what went
to_prompt(result)                      # the above, plus instructions
```

Determinism is what makes any of it regression-testable: the same analysis
produces byte-identical JSON, so a change in the payload is a diff rather than a
vibe. That is also why `tests/fixtures/golden/` stays a *hand-derived* suite —
a snapshot of a non-deterministic output fails on every run, which is the trap
`VALIDATION.md` §1 warns about.

## 12. Source

`src/albrooks/serialization/json.py` — the implementation
`tests/unit/test_phase22_serialization.py` — 43 tests
`examples/llm_analysis.py` — a runnable demonstration
`docs/architecture/CONCEPT_TAXONOMY.md` §5 — why no number here is statistical
`docs/algorithms/VALIDATION.md` §9 — what would have to change
