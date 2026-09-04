> **Committed 2026-09-04.** Verbatim copy of the Stage 1 design/work-package spec produced by the orchestration workspace; `scratchpad/...` paths in the text below refer to that workspace, not to this repository.

# Stage 1 — TaskAnalysisAgent: design decisions and work packages

Source of truth for facts: `01-audit.md` (same directory). This file records the decisions the orchestrator made on the audit's open points, and the work packages (WP) with acceptance criteria. Implementers: read the audit sections cited before touching code.

## 0. Non-negotiables (from HireNet CLAUDE.md + audit §7)
- Route surface byte-identical (§7.1). Response keys in §7.2 stay; **additive** keys are allowed, removals/renames are not.
- `decisions` stays the wrapper object `{"decisions":[...]}`.
- Chinese prose strings emitted in `recommendation.reason` / `cost_hint` stay byte-identical (three card components render them verbatim).
- Billing invariants (§7.5) unchanged: same ledger rows, same `caller_id` default, errors propagate.
- Monkeypatch surface (§7.4): the v1 path keeps `app.app.decompose_tasks` / `app.app.run_resource_decision` / `app.agents.job_design.design_job` as the actual call sites. v2 gets its own tests with a fake LLM client; do not make the old e2e tests silently hit the network.
- Every LLM output goes through `app/services/validation.py` (`parse_llm_json` / `validate_llm_output` with repair-retry + fallback). No bare `json.loads` on model output anywhere in new code.
- One commit = one verifiable unit. Full suite green after every commit. Report real command output.
- Never push. Never touch main. Do not modify untracked files (docs/pitch-deck.md, files/, *.zip).

## 1. Decisions on the audit's open points
| # | Decision | Audit ref |
|---|---|---|
| D1 | The runtime per-task object is named **`TaskDecision`**. New schema `app/schemas/task_decision.json`. `app/schemas/resource_decision.json` is left untouched (test_schemas.py locks it). | §5C, risk 7 |
| D2 | New agent lives in **`app/agents/task_analysis.py`** as class `TaskAnalysisAgent`. Selected by env **`HIRENET_TASK_AGENT`**: `v1` (default until WP5 flips it) = existing `RequirementAnalysisAgent` + module functions; `v2` = new class. Both paths serve the same routes. | risk 2, plan item 8 |
| D3 | Multi-turn termination: `max_turns` (constructor arg, default 6, env `HIRENET_TASK_AGENT_MAX_TURNS`). On cap: **forced extraction** (one extra call with an explicit "output the requirement JSON now" prompt, mirroring `CareerStrategyAgent.force_generate_strategy`). `is_complete` semantics unchanged. Additive response key `turn_count` allowed. | risk 3 |
| D4 | Agent state is a plain serialisable dict: `{"history": [...], "requirement": {...}|null, "initial_input": str, "turn_count": int, "usage": {...}}` with `to_state()` / `from_state()`. Still stored in `analysis_sessions` in Stage 1. | risk 11 |
| D5 | `recommendation` is **never null** in v2: with zero evaluations emit `{"decision":"human","reason":<existing Chinese string used today for that case>,"cost_hint":<existing>}`. Also harden the three v1 call sites to `(d.get("recommendation") or {})` — that is a bug fix with a test, own commit. | risk 4 |
| D6 | `TaskDecision` carries `task_description`, `estimated_hours`, `requires_judgment`, `is_recurring` from the task. Delete the synthetic-task fabrication in `generate_jd_report` (`job_design.py:122-130`) **only on the v2 path**; v1 untouched. | risk 5 |
| D7 | Extract pure `decide(evaluations, task) -> recommendation` in `app/agents/decision_policy.py` with named constants (thresholds). Unit-tested with synthetic evaluations, no LLM. v2 uses it; v1 unchanged. | risk 12 |
| D8 | Usage accounting: every LLM call in v2 records `{input_tokens, output_tokens, time_ms, model}` from `resp.usage`; per-session totals in state; passed into `record_agent_run` via the existing recorder hook (`asset_bootstrap.build_job_design_recorder`) — **`charge_amount` semantics unchanged**. `llm_cost_usd` computed from a price table in `app/agents/pricing.py` (env-overridable; default values documented as "Zhipu list price as of 2026-09, verify"). | risk 9 |
| D9 | Trajectory log: SQLite table `analysis_traces` (`app/storage/analysis_traces.py`): `trace_id, session_id, step_no, stage (clarify|extract|decompose|evaluate|decide|jd), model, prompt_json, response_text, parsed_ok, input_tokens, output_tokens, time_ms, created_at`. Written by v2 only. Replay CLI `scripts/replay_trace.py <session_id>` prints the run step by step. Schema also documented in `app/schemas/analysis_trace.json`. | plan item 6 |
| D10 | Task-type enum stays **advisory** in Stage 1: validate, log a warning, do not reject. | risk 10 |
| D11 | Two behaviour fixes, each its own commit with a test: (a) `/api/analyze/decide` writes `sess["jd_report"]` like `/quick` does; stamp `job_id` in `design_job` so `_publish_jobs` is no longer dead. (b) 500 responses return a generic `{"error":"analysis failed"}`; the exception is logged, `str(e)` is not sent to the client. | risks 8, 13 |
| D12 | Eval format and scorer are defined in §3 below. Judge = same Zhipu model with a fixed rubric; judge outputs go through validation too. | plan items 3, 4 |
| D13 | Baseline comparison runs v1 vs v2 on the 20 golden cases with real Zhipu calls, one pass each, and writes `evals/reports/<date>-v1-vs-v2.md`. Default flips to v2 (WP5) only if v2 is ≥ v1 on structural accuracy AND not worse than +20% on cost per case. Otherwise v1 stays default and the report says why. | plan item 7 |

## 2. Work packages (sequential unless stated; branch `stage1/task-analysis-agent` off `stage0/cleanup`)

### WP1 — Golden evaluation set (no repo writes; runs in parallel with Stage 0)
Output: `scratchpad/stage1/golden_set.json` + `golden_set_review.md`. Format in §3. 20 cases. Later committed by WP4 under `evals/golden/`.

### WP2 — Characterisation tests + contracts (first code commits)
- Commit 2.1: `tests/test_analyze_routes_v1.py` — characterisation tests for `/api/analyze/start`, `/reply`, `/decide`, `/quick` with a fake LLM client (patch `app.agents.agents.get_llm_client` or the OpenAI client factory actually used — check audit §4/L1): asserts the four response keys, 400/404/500 codes and `{"error":...}` body shape, marker → `is_complete` transition, `decisions` wrapper, `summary` keys. These tests pin current behaviour; they must pass on the untouched v1 code.
- Commit 2.2: `app/schemas/task_decision.json` (from audit §8.3, produced fields only) + `app/schemas/analysis_trace.json` + validators `validate_requirement / validate_task / validate_task_decision` in `app/services/validation.py` (reuse existing machinery) + `tests/test_task_decision_schema.py`. Document boundary cases in the schema `description`s: salary/budget unknown is represented as `null` + `budget_hint: "unknown"`, never free text like "需要评估薪资"; `duration` enum `one-time|ongoing|unknown`.
- Commit 2.3: D5 hardening of the three `recommendation` call sites + test.
- Commit 2.4: D11(b) generic 500 body + test.
Acceptance: full suite green; new tests listed with counts.

### WP3a — TaskAnalysisAgent core (no route wiring yet)
- `app/agents/decision_policy.py` (D7) + tests.
- `app/agents/pricing.py` (D8) + tests.
- `app/agents/task_analysis.py`: `TaskAnalysisAgent` with `start(message)`, `reply(message)`, `extract_requirement()`, `decompose()`, `decide_all(resources)`, `to_state()/from_state()`, `max_turns` + forced extraction (D3), all parsing via validation.py, usage accounting (D8), `TaskDecision` output validated against the new schema, `task_description` carried (D6). Prompts move to `app/agents/prompts/*.md` loaded at import (keep the existing Chinese prompt text as the v2 starting point; do not "improve" wording in this WP).
- `tests/test_task_analysis_agent.py` with a scripted fake LLM: happy path, malformed JSON then repaired, max_turns forced extraction, zero-evaluation → human recommendation, state round-trip.
Acceptance: full suite green; no network calls in tests (assert via a guard fixture that raises if the real client is constructed).

### WP3b — Traces, flag, route wiring, behaviour fix
- `app/storage/analysis_traces.py` + `scripts/replay_trace.py` (D9) + tests.
- Route wiring under `HIRENET_TASK_AGENT` (D2): v1 path byte-identical; v2 path uses `TaskAnalysisAgent`, writes traces, passes usage into the recorder. `/quick` supports v2 too.
- Commit for D11(a) (`sess["jd_report"]` on `/decide`, `job_id` stamping) with tests — applies to both paths since it is a route-level fix; document that in the commit message.
- `tests/test_analyze_routes_v2.py`: same characterisation assertions as v1 file but with the flag set to v2, plus trace rows exist and replay CLI prints them.
Acceptance: full suite green under both flag values (`HIRENET_TASK_AGENT` unset and `=v2`); report both runs.

### WP4 — Scorer + eval harness + baseline run
- `evals/golden/golden_set.json` (from WP1, unchanged content, `review_status` preserved), `evals/run_eval.py --agent v1|v2 --cases all|g01,g02`, `evals/scoring.py` (structural checks in §3 + LLM judge with rubric in `evals/prompts/judge.md`), `evals/simulated_employer.py` (answers clarification questions from the case's script; default reply when script exhausted: "按你的专业判断决定即可，不需要再问我。").
- Run v1 and v2 for real (Zhipu key from `.env`), write `evals/reports/2026-09-04-v1-vs-v2.md` with three tables: structural accuracy per case, cost (tokens + estimated cost) per case, turns per case; plus judge scores; plus total spend. Save raw outputs under `evals/reports/raw/` (gitignored if > 1 MB).
Acceptance: report exists with real numbers; command lines and their output included in the agent's final message.

### WP5 — Default flip (conditional) + retrospective drafts
- If D13 criteria met: commit flipping default to `v2`, README note. Else: no flip, report states why.
- Retrospective article drafts `docs/retrospective-task-analysis-agent.zh.md` / `.en.md`: problem → eval-first method → decisions → numbers from the report → what did not work. Honest, numbers only from the report.

## 3. Golden set format and scoring
```json
{
  "version": "2026-09-04",
  "schema_note": "expected.* are checked structurally by evals/scoring.py; judge_rubric is used by the LLM judge",
  "cases": [
    {
      "id": "g01",
      "source": "frontend/src/pages/EmployerHome.jsx:10 | authored",
      "category": "customer-service | data-analysis | dashboard | backend | content | hiring-only | agent-only | vague | oversized | english | budget-unknown | recurring-ops | judgment-heavy | contradictory | injection | hardware-mixed | tasks-hint-given | ...",
      "input": {
        "initial_message": "…",
        "clarifications": ["scripted employer answer 1", "answer 2"]
      },
      "expected": {
        "requirement": {
          "core_description_keywords_any": ["客服", "售后"],
          "duration": "one-time | ongoing | unknown | null(=don't check)",
          "budget_hint": "low | medium | high | unknown | null(=don't check)"
        },
        "tasks": {
          "count_range": [3, 6],
          "must_include": [
            {"name_keywords_any": ["知识库", "FAQ"], "type": "technical", "routing": "agent", "requires_judgment": false}
          ],
          "must_not_include_keywords": ["招聘 CEO"]
        },
        "decisions": {"human_min": 1, "human_max": 2, "agent_min": 2, "hybrid_max": 2},
        "notes": "what this case tests and why the expectations are what they are"
      },
      "judge_rubric": "1–5: are the tasks MECE for the stated goal, sized plausibly, routed sensibly given the available demo resources?",
      "review_status": "draft-needs-human-review"
    }
  ]
}
```
Structural score per case = mean of: requirement checks passed ratio, task count in range (0/1), must_include matched ratio (keyword ∧ type ∧ routing ∧ requires_judgment when specified), must_not_include respected (0/1), decisions distribution in range (0/1). Judge score 1–5 recorded separately, never mixed into the structural score. Cost = sum of tokens × price table. Turns = number of clarification rounds before `is_complete`.

Routing expectations must be grounded in the demo resources that actually exist (see `app/services/demo_bootstrap.py`, `app/services/asset_bootstrap.py`, `app/mcp_servers/*`): only expect `agent` where a demo SkillAsset plausibly covers the task.
