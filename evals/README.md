# `evals/` — the offline evaluation harness for the analysis pipeline

Stage 1 / WP4. This directory answers one question with numbers instead of
opinions: **is `TaskAnalysisAgent` (v2) actually better than the original
pipeline (v1), and what does it cost?**

Nothing in `app/` imports this package. The harness is a *consumer* of the app:
it boots a throwaway Flask app on a temp SQLite database, drives the four
`/api/analyze/*` routes exactly as a browser would, and scores what comes back.

```
evals/
  golden/golden_set.json    20 hand-authored cases (WP1), committed unchanged
  scoring.py                structural scorer — pure, deterministic, no network
  judge.py                  LLM judge (1–5), rubric in prompts/judge.md
  simulated_employer.py     scripted employer for the clarification loop
  llm_proxy.py              counting / retrying / budget-capping client wrapper
  run_eval.py               CLI — runs one agent version over the golden set
  report.py                 CLI — turns two raw dirs into the Markdown comparison
  reports/                  the committed comparison + raw/ per-case JSON
```

## Running it

`run_eval` makes **real, paid LLM calls** — it is the one place in Stage 1 that
is meant to. It reads `ZHIPU_API_KEY` / `ZHIPU_BASE_URL` / `ZHIPU_MODEL` from
`.env` (loaded by the harness itself before the app is imported) and refuses to
start if the key is missing. The key is never printed or written to a report.

```bash
# one version, all 20 cases, judge on
.venv/bin/python -m evals.run_eval --agent v1 --cases all --out evals/reports/raw/2026-09-04-v1
.venv/bin/python -m evals.run_eval --agent v2 --cases all --out evals/reports/raw/2026-09-04-v2

# the comparison
.venv/bin/python -m evals.report evals/reports/raw/2026-09-04-v1 evals/reports/raw/2026-09-04-v2 \
    --out evals/reports/2026-09-04-v1-vs-v2.md

# cheap smoke test: two cases, no judge
.venv/bin/python -m evals.run_eval --agent v2 --cases g18,g05 --no-judge \
    --budget-tokens 200000 --out /tmp/eval-smoke
```

Flags: `--agent v1|v2` (sets `HIRENET_TASK_AGENT` for the process),
`--cases all|g01,g02`, `--out DIR`, `--judge` / `--no-judge`,
`--budget-tokens N` (default 3,000,000, run-wide across pipeline **and** judge),
`--max-turns N` (default 8), `--golden PATH`.

Cases run **sequentially**. Parallelism would be faster and no cheaper, but
`app.app.analysis_sessions` is a module-level dict and the agent flag is
process-global; reproducibility is worth more here than wall time.

`pytest` never reaches the network. `tests/test_evals_scoring.py` covers the
scorer, the judge and the proxy with canned data, and imports neither
`run_eval` nor a real client.

## What one case does

1. fresh Flask app + fresh temp SQLite DB (same construction as
   `tests/conftest.py`, `MockSettlementProvider` injected so nothing dials a
   chain node);
2. `POST /api/analyze/start` with `input.initial_message`;
3. `POST /api/analyze/reply` with `SimulatedEmployer` answers until
   `is_complete` **or** the hard turn cap;
4. `POST /api/analyze/decide`;
5. structural score, optional judge score, and every number the proxy saw.

Any exception or non-200 is recorded as `error`, scores **0**, and the run
continues. The only thing that stops a run early is the token budget — and when
that happens the report lists what was not run and extrapolates nothing.

The simulated employer answers `input.clarifications` in order; once the script
is exhausted it keeps answering with the fixed line
`按你的专业判断决定即可，不需要再问我。`, and it stops after `--max-turns`
replies (default 8). v1 has no turn cap of its own — audit risk 3, the reason
D3 exists — so a v1 conversation can ask questions forever; the cap is what
makes such a run terminate, and it is then recorded `completed=False`.

## What the numbers mean

### Structural score (0–1) — the one that decides D13

Spec §3: the **mean of five components**, each computed against the case's
`expected` block.

| # | component | how it scores |
|---|---|---|
| 1 | `requirement` | ratio of asserted requirement fields that came out right (`core_description_keywords_any`, `duration`, `budget_hint`) |
| 2 | `task_count` | 0/1 — `len(tasks)` inside `count_range` (inclusive) |
| 3 | `must_include` | ratio of expected task entries that some real task satisfied |
| 4 | `must_not_include` | 0/1 — no forbidden keyword appeared |
| 5 | `decisions` | 0/1 — routing distribution inside every stated bound |

**A component the case does not assert anything about is skipped** (`None`) and
left out of the mean, rather than scored 1.0 — awarding a free point for an
unstated expectation would make thin cases score higher than thorough ones.
`null` in `expected.requirement` means "do not check this field", never "must be
null".

**The two contracts** (from `golden_set_review.md`, ambiguity #9 — both
exercised by `g18`, both pinned by tests):

* **(a) An empty `must_include` list scores 1.0**, explicitly, not "skipped".
  g18's whole point is that no particular task has to exist, so the correct
  behaviour is an explicit pass that keeps the g18 row comparable with the rest.
  (`must_not_include_keywords` gets no such exception: an empty list there —
  g17 — is genuinely "nothing asserted", so it is skipped.)
* **(b) A `count_range` lower bound of 0 means zero tasks is a pass.** Falls out
  of the inclusive test, but it is easy to "fix" into a bug, so it has its own
  test.

Matching rules:

* keyword matching is a **case-insensitive substring** test (Chinese has no word
  boundaries; the one English case gets the same rule for symmetry);
* `must_include[].name_keywords_any` matches the **task name only** — otherwise
  a task that is merely *mentioned* would count as a task that *exists*;
* `must_not_include_keywords` matches **name + description**, because that check
  is about contamination (a hallucinated domain, an injected instruction
  bleeding through) and contamination lands in the prose;
* `routing` is `decisions[].recommendation.decision` joined on `task_id`. An
  entry that omits `type` / `routing` / `requires_judgment` has that constraint
  **skipped, not failed** — the golden set omits `routing` deliberately wherever
  no demo resource settles the question (review ambiguities #3, #4).

A passing `decisions` component means "no gross routing failure", not "the
routing was good": the ranges are deliberately wide (review ambiguity #10).

### Judge score (1–5) — recorded separately, never mixed in

Per-case rubric from `judge_rubric`, general rubric in `prompts/judge.md`.
Output is `{"score", "rationale"}`, parsed with
`app.services.validation.parse_llm_json` plus a jsonschema check, **repaired at
most once**, and otherwise recorded as `None`. An unreadable judge is never
given a default score — substituting a 3 would drag every mean toward the
middle.

> **Judge caveat (D12).** The judge is the same model family that produced the
> answers it is grading. It tends to like output that looks like its own, and it
> cannot catch a mistake it would also make. D12 accepts this for Stage 1 **only
> on the condition that a human spot-checks at least 20% of the judge scores**.
> Until that spot-check is done, no decision should rest on the judge column.
> The structural column needs no such caveat — it is arithmetic.

The golden set itself is still `draft-needs-human-review` on all 20 cases.
Expectations a reviewer later changes will change these numbers.

### Cost — tokens first, dollars as an estimate

**Tokens are the primary cost metric.** Every call's `resp.usage` is captured by
`CountingLLMProxy` and reported as input/output tokens per case and per run.

USD is a derived *estimate* via `app.agents.pricing.estimate_cost_usd`, which
prices calls at a flat list rate (glm-4-plus at ¥0.05/1K, converted at
¥7.15/USD). **Zhipu moved its flagship models to tiered pricing in 2026-08**, so
the real invoice will differ — treat the dollar column as an order of magnitude,
and note that an unknown model is priced as `None`, never guessed.

Pipeline tokens and judge tokens are reported separately. The judge is harness
overhead and does the same work for both versions, so the **D13 cost test uses
pipeline tokens only**.

### D13 verdict — computed, not argued

`evals/report.py` prints PASS/FAIL from the raw numbers:

```
PASS  ⇔  mean structural(v2) ≥ mean structural(v1)
         AND  pipeline tokens(v2) ≤ 1.2 × pipeline tokens(v1)
```

WP5 acts on that line: PASS ⇒ flip the `HIRENET_TASK_AGENT` default to v2;
FAIL ⇒ v1 stays default and the retrospective says why.

### Accounting cross-check (v2 only)

The report compares what the **app** billed against what the **proxy** counted.
`agent_runs.input_tokens/output_tokens` are written from
`TaskAnalysisAgent.usage_summary()` (D8) and cover the agent only; the proxy
also sees `design_job`, which runs outside the agent. So `delta` should equal
the `job_design` stage total exactly. It is the check that says the cost half of
D13 can be trusted. On the v1 path those columns are NULL by design — that gap
is what D8 exists to close.

## Output layout

`--out DIR` gets one `<case_id>.json` per case plus `summary.json`. A case file
carries the full transcript, the full `/decide` response, HTTP codes, turns,
every LLM call record, the score with per-check detail, the judge verdict, and
(v2) the `agent_runs` / `analysis_traces` cross-check material — enough to
re-derive every number in the report without re-running anything.
