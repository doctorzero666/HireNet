"""Stage 1 / WP4 — the offline evaluation harness for the analysis pipeline.

Nothing in `app/` imports this package. It is a *consumer* of the app: it boots
a throwaway Flask app against a temp SQLite database, drives the four
`/api/analyze/*` routes exactly as a browser would, and scores what comes back
against `evals/golden/golden_set.json`.

Modules:
    scoring            structural scorer (spec §3) — pure, no network
    judge              LLM judge (rubric in evals/prompts/judge.md)
    simulated_employer scripted employer for the clarification loop
    llm_proxy          counting/retrying/budget-enforcing LLM client wrapper
    run_eval           CLI: run one agent version over the golden set
    report             CLI: turn two raw dirs into the Markdown comparison

`run_eval` is the only module that makes real network calls, and only when a
human runs it from the command line. `pytest` must never reach the network:
tests/test_evals_scoring.py exercises scoring/judge with canned data.
"""
