> **Committed 2026-09-04.** Verbatim copy of the Stage 1 read-only audit produced by the orchestration workspace; `scratchpad/...` paths in the text below refer to that workspace, not to this repository.

# HireNet — Task-Analysis Pipeline Architecture Audit
**Scope**: `start_analysis` → `RequirementAnalysisAgent` (multi-turn) → `extract_requirement` → `decompose_tasks` → `evaluate_resource_for_task` / `run_resource_decision` → `generate_jd_report` → persisted `agent_runs` + `royalty_ledger`.
**Date**: 2026-09-04 · **Mode**: read-only · **Repo**: `/Users/zhichaojiang/Documents/HireNet`
**Purpose**: task 1 of Stage 1 ("build a dedicated `TaskAnalysisAgent`"). Everything below is derived from code actually present; nothing is inferred from docs unless flagged.

---

## 0. Executive orientation

There are **two** entry paths into the same pipeline core:

| Path | Entry | Requirement source | Multi-turn? |
|---|---|---|---|
| Conversational | `POST /api/analyze/start` → `POST /api/analyze/reply` (0..N) → `POST /api/analyze/decide` | LLM-extracted from chat | yes |
| Quick / demo | `POST /api/analyze/quick` | client-supplied dict, **unvalidated** | no |

Both converge on the identical three-call core (`decompose_tasks` → `run_resource_decision` → `generate_jd_report`) but with **different session side effects** (see §6.4) — this asymmetry is a live bug, not a design choice.

A third, undocumented entry exists: `POST /api/mcp` with `tools/call name="hirenet_analyze_requirements"` constructs a throw-away `RequirementAnalysisAgent`, calls `.start()` once, and returns the raw text (`app/app.py:1160-1165`). It never decomposes or decides.

---

## 1. Sequence diagram — one full run

```mermaid
sequenceDiagram
    autonumber
    actor U as Employer (browser)
    participant EH as EmployerHome.jsx
    participant AC as AnalysisChat.jsx
    participant AR as AnalysisReport.jsx
    participant API as api.js
    participant F as Flask main blueprint<br/>(app/app.py)
    participant S as analysis_sessions<br/>(module global dict)
    participant RA as RequirementAnalysisAgent<br/>(agents.py:49)
    participant LLM as Zhipu GLM-4<br/>(OpenAI-compatible)
    participant DT as decompose_tasks<br/>(agents.py:118)
    participant RD as run_resource_decision<br/>(agents.py:382)
    participant EV as _llm_evaluate_resource<br/>(agents.py:168)
    participant JD as generate_jd_report<br/>(job_design.py:95)
    participant REC as build_job_design_recorder<br/>(asset_bootstrap.py:108)
    participant DB as SQLite<br/>agent_runs + royalty_ledger

    U->>EH: types business goal
    EH->>API: startAnalysis(message)
    API->>F: POST /api/analyze/start {message}
    F->>RA: RequirementAnalysisAgent()  (app.py:161)
    F->>RA: .start(initial_input)  (app.py:162)
    RA->>LLM: LLM#1 chat.completions.create(temp=0.3, system=REQUIREMENT_SYSTEM_PROMPT)
    LLM-->>RA: assistant text (question OR "[REQUIREMENT_COMPLETE]" + JSON)
    RA-->>F: response str
    F->>S: analysis_sessions[session_id] = {agent, initial_input, history, requirement:None}  (app.py:165-170)
    F->>RA: is_complete(response)  (app.py:172)
    alt marker present
        F->>RA: extract_requirement(response)  (app.py:176)
        RA-->>F: dict (bare json.loads, agents.py:87)
        Note over F: on ANY exception → is_complete=False, requirement stays None (app.py:178-179)
    end
    F-->>API: 200 {session_id, response, is_complete, requirement}
    API-->>EH: result
    EH->>AC: navigate /employer/analysis/:sessionId (state={initialMessage, firstReply})

    loop until is_complete (no server-side turn cap)
        U->>AC: answer
        AC->>API: replyAnalysis(session_id, message)
        API->>F: POST /api/analyze/reply
        F->>S: lookup session (404 if absent, app.py:196-197)
        F->>RA: .reply(message)  (app.py:201)
        RA->>LLM: LLM#2..#N (full history replayed, temp=0.3)
        LLM-->>RA: assistant text
        RA-->>F: response
        F-->>AC: 200 {session_id, response, is_complete, requirement}
    end

    AC->>API: runDecision(sessionId)  (AnalysisChat.jsx:58, fires on is_complete)
    API->>F: POST /api/analyze/decide {session_id}
    F->>S: requirement = sess["requirement"]  (app.py:239) → 400 if falsy (app.py:241-242)
    F->>DT: decompose_tasks(requirement)  (app.py:246)
    DT->>LLM: LLM#N+1 (temp=0.2, system=DECOMPOSITION_SYSTEM_PROMPT)
    LLM-->>DT: JSON text
    DT-->>F: {"tasks":[...]}  (bare json.loads, agents.py:141)
    F->>RD: run_resource_decision(tasks)  (app.py:250)
    RD->>RD: get_all_resources() → 3 agents + 3 humans (candidate_profile.py:108)
    loop per task (max 5 by prompt rule, agents.py:100)
        RD->>RD: _filter_resources_for_task → ≤3 resources (agents.py:231-269)
        loop per filtered resource (1..3)
            RD->>EV: evaluate_resource_for_task(resource, task)  (agents.py:404)
            EV->>LLM: LLM#M (temp=0.2, single user message, no system)
            LLM-->>EV: JSON text
            EV-->>RD: {can_complete, confidence, reason, estimated_time, strengths,<br/>resource_id, resource_name, resource_type}
        end
        RD->>RD: sort by confidence desc; threshold policy 0.7 / 0.6 / 0.5 (agents.py:415/422/434)
        RD->>RD: recommendation = {decision, resource, reason, cost_hint}
    end
    RD-->>F: {"decisions":[...]}
    F->>REC: _job_design_recorder()  (app.py:258 → app.py:133-145)
    F->>JD: generate_jd_report(decisions, requirement, original_description, on_design)
    loop per human/hybrid decision (job_design.py:107-110)
        JD->>JD: synthesise task dict (job_design.py:122-130) — DROPS real task fields
        JD->>LLM: LLM#K design_job (temp=0.3, system=JOB_DESIGN_SYSTEM_PROMPT)
        LLM-->>JD: JSON text → job_design (bare json.loads, job_design.py:89)
        Note over JD: exception → print + continue (job_design.py:134-136) — job silently dropped, NOT billed
        JD->>REC: on_design(task, jd)  (job_design.py:140)
        REC->>DB: record_agent_run(...)  (asset_bootstrap.py:132-142)
        DB-->>DB: 1 agent_runs row + 3 royalty_ledger rows in ONE txn<br/>(agent_run_recording.py:210-214)
    end
    JD-->>F: {needs_hiring, job_count, average_water_score, water_interpretation, job_designs}
    F->>F: _build_decision_summary(tasks, decisions, jd_report)  (app.py:262 → 280-318)
    F->>F: _publish_jobs(jd_report)  (app.py:265) — NO-OP: job_designs never carry job_id
    F-->>API: 200 {requirement, tasks, decisions, jd_report, summary}
    API-->>AC: result
    AC->>AR: navigate /employer/report/:sessionId (state=result)
    AR->>U: renders AgentTaskCard / HiringTaskCard / HybridTaskCard
```

**LLM call count for one conversational run**: `1 (start) + T (replies) + 1 (decompose) + Σ ≤3 per task (≤15) + H (job designs) ≈ 3 + T + 15 + H`. No batching, no caching, no concurrency, no budget cap.

---

## 2. Route table

Exact key names — Stage 1 must not change any of these.

| # | Method | Path | Request JSON keys (type as used) | Response JSON keys | Status codes | Frontend caller | Test coverage |
|---|---|---|---|---|---|---|---|
| 1 | POST | `/api/analyze/start` (`app/app.py:150-186`) | `message` (str, `.strip()`ed, required-non-empty `app.py:154-157`) | `session_id` (str, 16-hex), `response` (str, raw LLM text), `is_complete` (bool), `requirement` (obj\|null) | 200; 400 `{"error":"Message is required"}`; **uncaught LLM exception → Flask 500 HTML** | `frontend/src/services/api.js:35-43` ← `pages/EmployerHome.jsx:29` | **none** |
| 2 | POST | `/api/analyze/reply` (`app.py:189-218`) | `session_id` (str), `message` (str) | same 4 keys as #1 | 200; 404 `{"error":"Session not found"}` (`app.py:196-197`); LLM exception → 500 HTML | `api.js:45-53` ← `pages/AnalysisChat.jsx:79` | **none** |
| 3 | POST | `/api/analyze/decide` (`app.py:223-277`) | `session_id` (str) | `requirement` (obj), `tasks` (list), `decisions` (obj `{decisions:[...]}`), `jd_report` (obj), `summary` (obj) | 200; 404 session; 400 `{"error":"Requirement analysis not complete"}` (`app.py:242`); 500 `{"error": str(e)}` (`app.py:277`) | `api.js:55-63` ← `pages/AnalysisChat.jsx:58` | **none** |
| 4 | POST | `/api/analyze/quick` (`app.py:1222-1267`) | `requirement` (obj, **any shape**), `original_description` (str, default `""`) | `session_id`, `requirement`, `tasks`, `decisions`, `jd_report`, `summary` | 200; 400 `{"error":"requirement is required"}` (`app.py:1231`); 500 `{"error": str(e)}` (`app.py:1267`) | **none** (no frontend caller) | `tests/test_e2e_phase1.py:122,153,180,239` (4 of 6 tests) |
| 5 | POST | `/api/mcp` (`app.py:1130-1218`) `tools/call` + `name:"hirenet_analyze_requirements"` | JSON-RPC `{method, params:{name, arguments:{description}}}` | `{jsonrpc, id, result:{content:[{type:"text", text}]}}` | 200; 400 with `error.code` -32602 / -32601 / -32603 | none | `tests/test_mcp_integration.py` (15 tests, but **none** exercise `hirenet_analyze_requirements`) |
| 6 | POST | `/api/jobs/publish` (`app.py:942-1030`) — downstream of the report's JD modal | `jd` (str, required), `job_id`, `company`, `job_title`, `required_skills` (list[str]), `nice_to_have_skills`, `core_responsibilities`, `work_type` (enum), `salary_range` (obj) | `success`, `job_id`, `job` | 200; 415; 400; 409 duplicate `job_id` | `api.js:154-188` ← `components/JdModal.jsx:37-46` | `tests/test_demo_identity_and_publish.py` (15 tests, publish subset) |
| 7 | GET | `/api/jobs` (`app.py:421-448`) — reads `analysis_sessions[*]["jd_report"]` | — | `jobs` (list) | 200 | `api.js:67-71` ← `pages/JobSeekerHome.jsx` | partial |

**Mismatch found**: `api.js:117-125` `matchCandidatesForJob()` POSTs `/api/match-candidates`, but the backend route is `/api/match` (`app.py:349`). No such route exists → permanent 404. Not on the Stage-1 critical path, but it is in the same file you will touch.

---

## 3. Function table — `agents.py` and its helpers

| Function / class | File:line | Responsibility | Inputs | Outputs | Side effects |
|---|---|---|---|---|---|
| `get_llm_client()` | `agents.py:15-19` | build OpenAI-compatible client | env `ZHIPU_API_KEY`, `ZHIPU_BASE_URL` | `OpenAI` | none; **constructs a NEW client per call site invocation** (`agents.py:120`, `:170`) |
| `get_model()` | `agents.py:22-23` | model id | env `ZHIPU_MODEL` (default `glm-4-plus`) | str | none |
| `RequirementAnalysisAgent.__init__` | `agents.py:50-52` | holds client + `self.history` | — | — | **instance state** (`history` list) |
| `.start(initial_input)` | `agents.py:54-60` | seed history w/ system+user, 1 LLM call | str | assistant str | mutates `self.history` |
| `.reply(user_message)` | `agents.py:62-65` | append user turn, 1 LLM call | str | assistant str | mutates `self.history` (unbounded) |
| `._call_llm()` | `agents.py:67-75` | the actual LLM call, temp 0.3 | `self.history` | str | appends assistant msg to history |
| `.is_complete(response)` | `agents.py:77-78` | **substring** check `"[REQUIREMENT_COMPLETE]" in response` | str | bool | none |
| `.extract_requirement(response)` | `agents.py:80-87` | split on marker, strip ``` fences, `json.loads` | str | dict | raises `ValueError` if marker absent, `JSONDecodeError` if bad JSON |
| `decompose_tasks(requirement)` | `agents.py:118-141` | 1 LLM call, parse to `{"tasks":[...]}` | requirement dict (all reads via `.get`, `:124-128`) | dict | none; raises on parse failure |
| `evaluate_resource_for_task(resource, task)` | `agents.py:163-165` | thin pass-through wrapper | resource dict, task dict | dict | none |
| `_llm_evaluate_resource(resource, task)` | `agents.py:168-228` | 1 LLM call + hand-rolled JSON recovery + inject resource identity | resource, task | eval dict | none; **hard-indexes** `resource['name'\|'type'\|'id']`, `task['name'\|'description'\|'type']` |
| `_filter_resources_for_task(task, resources)` | `agents.py:231-269` | hardcoded routing table task-type → ≤3 resource ids | task, resources | list[dict] | none; **hardcodes ids** `agent_content`/`agent_code`/`agent_data`/`candidate_b` |
| `run_resource_decision(tasks)` | `agents.py:382-451` | orchestrate filter+eval+sort+threshold policy+prose | list[task] | `{"decisions":[...]}` | none; reads `DEMO_AGENTS` global (`:420`); **hard-indexes** `task["id"\|"name"\|"type"]` |
| `get_all_resources()` | `candidate_profile.py:108-118` | merge 3 `DEMO_AGENTS` + 3 `MOCK_PROFILES` | — | list[dict] | none; swallows per-agent exceptions with `print` (`:114-115`) |
| `design_job(requirement, task, original_description)` | `job_design.py:45-92` | 1 LLM call → job design; stamps `task_id`/`task_name` | dicts | dict | none |
| `generate_jd_report(decisions, requirement, original_description, on_design)` | `job_design.py:95-154` | filter human/hybrid, synthesise task, call `design_job`, invoke billing, aggregate water score | dicts + callback | dict | **DB writes via `on_design`**; swallows design failures with `print`+`continue` (`:134-136`) |
| `_interpret_water_score(score)` | `job_design.py:157-167` | 5-band Chinese label | float | str | none |
| `_build_decision_summary(tasks, decisions, jd_report)` | `app.py:280-318` | count decisions, pick verdict text | lists/dicts | dict | none |
| `_publish_jobs(jd_report)` | `app.py:321-328` | append designs to global pool | dict | None | **mutates module global `published_jobs`**; no-op in practice (see §5.C4) |
| `_job_design_recorder()` | `app.py:133-145` | build billing callback from app config + current identity | request context | callable | reads `current_app.config`, resolves identity |
| `build_job_design_recorder(db_path, asset_id, caller_id)` | `asset_bootstrap.py:108-144` | closure billing 1 invocation per design | strs | callable | **DB read** at build time; **DB write** per call |
| `record_agent_run(...)` | `agent_run_recording.py:37-220` | compute split, validate against schema, write `agent_runs` + 3 `royalty_ledger` rows atomically | kwargs | `{run_id, royalty_splits, ledger_entry_ids}` | **DB write (single txn)**; schema-validates before persist (`:200-205`) |

**Module-global state in the path**: `analysis_sessions` (`app.py:23`), `career_sessions` (`app.py:24`), `published_jobs` (`app.py:53`), `pact_sessions` (`app.py:49`), `user_profile_state` (`app.py:56-63`), `DEMO_AGENTS`/`MOCK_PROFILES` (`candidate_profile.py:6-82`), `_applications` (`application_agent.py:15`).

---

## 4. LLM call table

| # | Call site | Model / provider | Prompt text location | Temp | Parsing | Fallback on parse failure | Accounting | Termination |
|---|---|---|---|---|---|---|---|---|
| L1 | `RequirementAnalysisAgent._call_llm` `agents.py:68-72` | `get_model()` = env `ZHIPU_MODEL`, default `"glm-4-plus"` (`agents.py:23`); base `ZHIPU_BASE_URL` default `https://open.bigmodel.cn/api/paas/v4` (`agents.py:18`) | `REQUIREMENT_SYSTEM_PROMPT` `agents.py:28-46` (inline module constant, Chinese) | 0.3 | none at call time; later `extract_requirement` `agents.py:84-87`: `split("[REQUIREMENT_COMPLETE]")[1]` → `.replace("```json","").replace("```","")` → **bare `json.loads`** | Route catches bare `except Exception` and sets `is_complete=False` (`app.py:178-179`, `:210-211`) → conversation continues forever; the malformed text is still returned in `response` and rendered to the user (`AnalysisChat.jsx:80`) | **none** | **Substring marker only** (`agents.py:78`). **No max-turn cap anywhere** — not in the agent, not in the route, not in the frontend |
| L2 | `decompose_tasks` `agents.py:130-137` | same | `DECOMPOSITION_SYSTEM_PROMPT` `agents.py:92-115` + f-string user prompt `agents.py:122-128` | 0.2 | `.replace("```json","").replace("```","")` → **bare `json.loads`** (`agents.py:140-141`) | **none** — exception propagates to route → 500 `{"error": str(e)}` (`app.py:275-277`, `:1265-1267`) | none | single call |
| L3 | `_llm_evaluate_resource` `agents.py:197-201` | same | inline f-string user prompt `agents.py:175-195`; **`RESOURCE_DECISION_ACTION_CONTROL` (`agents.py:146-160`) is defined but NEVER used** | 0.2 | fence-strip → `json.loads`; on `JSONDecodeError` a hand-rolled brace counter `agents.py:205-224` that **does not track string literals** (a `{`/`}` inside a JSON string breaks it). `app/services/validation.py:96-122` has a correct, string-aware version that is not used here | re-raises. `run_resource_decision` does **not** catch (`agents.py:404`) → 500. Other callers each substitute a different literal: `{"confidence":0.5,"reason":"评估超时，使用默认分数","strengths":[]}` (`app.py:378-379`, `:485-486`, `:524-525`) and `{"confidence":0.5,"reason":"评估超时","strengths":[]}` (`app.py:1195`) | none | 1 call per (task, resource) pair; ≤3 resources by `_filter_resources_for_task` `agents.py:269` |
| L4 | `design_job` `job_design.py:78-85` | `get_model()` re-declared locally at `job_design.py:16-17` (duplicate of `agents.py:22`) | `JOB_DESIGN_SYSTEM_PROMPT` `job_design.py:20-42` + f-string `job_design.py:56-76` | 0.3 | fence-strip → **bare `json.loads`** (`job_design.py:88-89`) | caught in `generate_jd_report` `job_design.py:134-136` → `print(...)` + `continue`. The job silently disappears from the report **and is not billed** | none | 1 call per human/hybrid task |
| L5 | `CareerStrategyAgent` `agents.py:302-379` (parallel pipeline, same patterns) | same | `CAREER_STRATEGY_SYSTEM_PROMPT` `agents.py:274-299`; force-prompt `agents.py:345-359` | 0.5 / 0.3 | marker `[STRATEGY_READY]`; brace-count extractor `agents.py:372-379` | `force_generate_strategy` is the escape hatch — **the requirement pipeline has no equivalent** | none | marker; `/api/career/generate` provides an explicit force route (`app.py:664-678`) |

**Cross-cutting LLM facts**
- No `timeout=`, no `max_tokens=`, no retry, no exponential backoff on any of L1–L5 (grep: zero matches for `timeout`/`max_tokens` in `app/agents/`).
- `resp.usage` is never read anywhere in `app/` — so `input_tokens`, `output_tokens`, `llm_cost_usd`, `time_ms` on `agent_runs` (schema `app/schemas/agent_run.json:18-21`) are **always NULL**: `build_job_design_recorder` never passes them (`asset_bootstrap.py:132-142`).
- `app/services/validation.py` provides exactly the missing machinery (`parse_llm_json` `:125`, `validate_llm_output` with repair-retry + fallback `:165-218`) and is **used by zero agent code** — only by `skill_registration.py:6` and `agent_run_recording.py:30`, for DB rows.
- `.env.example` still documents `KIMI_*` / `OPENAI_*` (`.env.example:16-23`) and has **no `ZHIPU_*` entries**, while the live `.env` defines `ZHIPU_API_KEY` / `ZHIPU_BASE_URL` / `ZHIPU_MODEL`. Config drift.

---

## 5. Contract-fuzzy points

### A. `requirement`

| # | Issue | Evidence |
|---|---|---|
| A1 | Shape is defined **only in a Chinese prompt string**, never enforced in code. | `agents.py:37-46` |
| A2 | `app/schemas/requirement.json` exists and requires 6 fields, but **no production code path validates against it**. Only `tests/test_schemas.py:96-113` uses it. | `app/schemas/requirement.json:5`; grep shows `validate(..., "requirement")` only in tests |
| A3 | `team_context` is emitted by the prompt but is **optional** in the schema — silently absent in half the runs. | prompt `agents.py:43` vs schema `requirement.json:11` (not in `required` list `:5`) |
| A4 | `/api/analyze/quick` accepts **any dict** as `requirement`, no shape check whatsoever. | `app.py:1229-1233` |
| A5 | `duration` is an enum `one-time\|ongoing\|unknown` in prompt+schema, but tests pass free text `"3个月"` through the real endpoint and it is accepted. | prompt `agents.py:44`; schema `requirement.json:10`; tests `test_e2e_phase1.py:129`, `:182`, `:241` |
| A6 | `duration == "ongoing"` is a **magic string comparison** that decides `is_recurring` on the synthesised task. With `"3个月"` it silently evaluates False. | `job_design.py:128` |
| A7 | `budget_hint` is a categorical string (`low\|medium\|high\|unknown`), never a number and never a currency amount. It is consumed **only as prompt text**, never in any decision. | produced `agents.py:45`; consumed `job_design.py:66`; never read elsewhere |
| A8 | Every consumer reads with `.get(k, <default>)`, so a missing field degrades into the literal strings `'未知'` / `'unknown'` / `''` inside the next prompt — a silent quality failure, not an error. | `agents.py:124-128`; `job_design.py:59-66` |
| A9 | `urgency` is produced by the prompt and required by the schema but **read by nothing** — dead field. | produced `agents.py:44`; zero consumers (grep `urgency` → only prompt, schema, tests) |

### B. `task`

| # | Issue | Evidence |
|---|---|---|
| B1 | Three incompatible `type` vocabularies coexist: schema/prompt enum (`technical\|creative\|analytical\|strategic\|operational`), the literal `"general"` used by the match routes, and `"engineering"` used by tests. | enum `agents.py:97`, `task.json:12`; `"general"` `app.py:369`, `:477`, `:519`, `:1188`; `"engineering"` `test_e2e_phase1.py:60`, `:68` |
| B2 | `_filter_resources_for_task` silently falls through to an `else` branch for any unknown type — an out-of-vocabulary type is not an error, it just gets a different (worse) resource shortlist. | `agents.py:260-261` |
| B3 | `run_resource_decision` **hard-indexes** `task["id"]`, `task["name"]`, `task["type"]` (KeyError→500) but uses `.get` for `requires_judgment` / `is_recurring`. Inconsistent strictness within one function. | `agents.py:392-394` vs `:240-241`, `:186` |
| B4 | `_llm_evaluate_resource` hard-indexes `task['description']`; the decomposition prompt does not guarantee it. | `agents.py:184` |
| B5 | `estimated_hours` has no server-side consumer at all; the frontend renders `task.estimated_hours ?? '—'`, so the field is `number \| undefined` and the rendered value is `number \| '—'`. | `AgentTaskCard.jsx:14`, `HiringTaskCard.jsx:10`, `HybridTaskCard.jsx:8`, `AnalysisReport.jsx:181` (`?? 2`) |
| B6 | `task_data.get("tasks", [])` silently yields `[]` when the LLM returns a differently-keyed object; the run then produces zero decisions and the summary reports the **wrong** verdict `"无需招聘，所有任务可由 Agent 完成"`. | `app.py:247`, `:1245`; verdict branch `app.py:299-301` |
| B7 | The prompt caps tasks at 5 (`最多输出5个任务`) — a **prompt-level** constraint with no code enforcement. | `agents.py:100` |
| B8 | `generate_jd_report` **rebuilds a synthetic task** from the decision record, discarding the real task's `description`, `estimated_hours`, `requires_judgment`, `is_recurring` and substituting `requires_judgment=True` and `estimated_hours=40` constants. | `job_design.py:122-130` |
| B9 | That synthetic task reads `task_decision.get("task_description", "")`, a key **`run_resource_decision` never writes** (`agents.py:391-397` writes only `task_id`/`task_name`/`task_type`) → in production the JD prompt always receives an empty task description. Only the test stub sets it. | producer gap `agents.py:391-397`; consumer `job_design.py:126`; test-only source `test_e2e_phase1.py:68` |

### C. `resource decision`

| # | Issue | Evidence |
|---|---|---|
| C1 | **Two unrelated objects share the name.** Runtime shape: `{task_id, task_name, task_type, evaluations[], recommendation{decision, resource, reason, cost_hint}}`. Schema shape: `{executor_type, payment_method, asset_ids, settlement_timing}`. Nothing produces or consumes the schema shape. | runtime `agents.py:391-448`; schema `app/schemas/resource_decision.json:6-11`; schema tested only at `test_schemas.py:140-159`, `:601+` |
| C2 | Agent-vs-human routing is encoded as **lowercase magic strings** `"agent"` / `"human"` / `"hybrid"` in the runtime object, vs **capitalised** `"Agent"/"Human"/"Hybrid"` in the schema. Consumed lowercase in 3 places. | produced `agents.py:417`, `:424`, `:437`, `:446`; consumed `app.py:286`, `:290`, `:294`; `job_design.py:109`; `AnalysisReport.jsx:72-77`, `:124`, `:134` |
| C3 | Decision thresholds are inline magic numbers with no named constants and no config: 0.7 (agent), 0.6 (human), 0.5 (hybrid). | `agents.py:415`, `:422`, `:434` |
| C4 | `cost_hint` is a free-text string that mixes three incompatible things: a USD price string `"$0.05"` from `DEMO_AGENTS`, the Chinese prose `"需要评估薪资"` / `"混合成本"`, and the literal `"未知"`. It is the **only** money field on the decision. | `agents.py:420` (via `candidate_profile.py:68`,`:74`,`:80`), `:427`, `:439`, `:447` |
| C5 | **Salary-negotiable ("面议") is not represented in data at all** — it is a UI fallback string when `cost_hint` is absent. The same slot is rendered as agent cost in one card and as 预估薪资 in another. | `JdModal.jsx:114` (`?? '面议'`); `HiringTaskCard.jsx:9`,`:76`; `AgentTaskCard.jsx:13`,`:83` |
| C6 | Budget/salary types drift across the stack: `salary_range` is `{min:number,max:number,unit:string}` in the JD (`job_design.py:37`), but the candidate pages accept `salary_range \| salary \| compensation \| salary_min \| salary_max`, object-or-string, and reduce them to a display string. | `JobSeekerHome.jsx:25-45`; `JobDetail.jsx:35-45` |
| C7 | `recommendation` can legitimately be `None` (`agents.py:396`, only overwritten inside `if top:` `:414`). `_build_decision_summary` does `d.get("recommendation", {}).get("decision")` — the default only applies when the **key is missing**, not when the value is `None` → `AttributeError` → 500. Same pattern in `generate_jd_report`. | `app.py:286`, `:290`, `:294`; `job_design.py:109` |
| C8 | `can_complete` is produced by the LLM on every evaluation and **read by nothing** — dead field. | produced `agents.py:190`; zero consumers |
| C9 | `confidence` is read as `.get("confidence", 0)` in the threshold checks but **hard-indexed** in the f-string `{top['confidence']:.0%}`. If the LLM returns a string (`"0.9"`), the `>=` comparison raises `TypeError` before that. No coercion anywhere. | `agents.py:409`, `:415`, `:419`, `:422`, `:426`, `:434` |
| C10 | `resource_type` is copied from `resource["type"]` (`"agent"`/`"human"`), so the human/agent split depends on a field of the demo fixture, not on any validated enum. | `agents.py:227`; `candidate_profile.py:24`,`:99` |
| C11 | `_filter_resources_for_task` hardcodes resource **ids** (`agent_content`, `agent_code`, `agent_data`, `candidate_b`). Adding or renaming a resource silently changes routing. | `agents.py:242-245` |
| C12 | `_publish_jobs` only appends designs with a `job_id`, but `design_job` stamps only `task_id`/`task_name` — **no `job_id` is ever produced by the pipeline**, so the function is a permanent no-op. | filter `app.py:326`; producer `job_design.py:90-91` |
| C13 | The `evaluations` array is returned to the client in full (including every LLM's `reason`, `strengths`, `estimated_time`) but the frontend reads only `recommendation`. Undocumented payload surface that Stage 1 must not accidentally drop. | `agents.py:395`, `:405`; `AnalysisReport.jsx:67-77` reads only `recommendation` |

### D. Session / identity

| # | Issue | Evidence |
|---|---|---|
| D1 | `analysis_sessions[session_id]` stores a **live Python object** (`RequirementAnalysisAgent`) — unserialisable, single-process only, never evicted, no TTL, no size cap. | `app.py:165-170` |
| D2 | Sessions are **not scoped to an identity**. Any caller with a `session_id` can drive `/reply` and `/decide`. `session_id` is 8 random bytes (`secrets.token_hex(8)`), which is fine entropy but there is no ownership check. | `app.py:160`, `:196`, `:235` |
| D3 | `/api/jobs` iterates **every** session's `jd_report` — cross-tenant read of other users' generated JDs. | `app.py:432-437` |
| D4 | `quick_analyze` writes `sess["jd_report"]` (`app.py:1252`); `run_decision` does **not** (`app.py:244-273`). So JDs from the real conversational flow never reach `/api/jobs`. | asymmetry between `app.py:1252` and `app.py:244-273` |
| D5 | `apply_to_job` back-fills `sess["jd_report"]` from a client-supplied `job_design` if the key is absent — a third writer of session state, from the candidate side. | `app.py:576-580` |
| D6 | Billing identity comes from `get_current_identity()["id"]` resolved at request time inside a route helper; the agents layer has no notion of caller. | `app.py:133-145`; `asset_bootstrap.py:136` |

---

## 6. Mixed-responsibility points

| # | Unit | Jobs it currently does (count) | File:line |
|---|---|---|---|
| M1 | `run_decision` route | (1) parse request, (2) session lookup + auth-less ownership, (3) orchestrate 3 LLM agents, (4) construct the **billing** callback, (5) build the summary, (6) mutate global `published_jobs`, (7) serialise, (8) blanket-map every exception to 500 with `str(e)` leaked to the client | `app.py:223-277` |
| M2 | `run_resource_decision` | (1) load resources, (2) pre-filter/route, (3) drive N LLM calls, (4) sort, (5) apply threshold **policy**, (6) generate Chinese **prose**, (7) look up cost from the `DEMO_AGENTS` fixture | `agents.py:382-451` |
| M3 | `generate_jd_report` | (1) filter decisions, (2) **fabricate** a task object, (3) LLM call, (4) invoke **DB billing**, (5) swallow failures, (6) aggregate a score, (7) interpret the score into UI copy | `job_design.py:95-154` |
| M4 | `RequirementAnalysisAgent` | (1) own the LLM client, (2) own conversation state, (3) detect the termination marker, (4) parse JSON out of prose | `agents.py:49-87` |
| M5 | `_llm_evaluate_resource` | (1) prompt-build, (2) LLM call, (3) JSON repair, (4) **identity injection** into the result | `agents.py:168-228` |
| M6 | `start_analysis` | (1) validate, (2) instantiate the agent, (3) call the LLM, (4) mint the session id, (5) write the global dict, (6) parse the requirement, (7) swallow the parse error into a boolean | `app.py:151-186` |
| M7 | `_job_design_recorder` | a route-layer function that reaches into `current_app.config` and identity resolution purely so the *agents* layer can bill — the coupling is inverted through a callback | `app.py:133-145` |

**State held outside any object**: `analysis_sessions` `app.py:23`, `career_sessions` `app.py:24`, `published_jobs` `app.py:53`, `user_profile_state` `app.py:56`, `pact_sessions` `app.py:49`, `_applications` `application_agent.py:15`. All process-local; `wsgi.py`/`app.py:26-48` explicitly documents the single-worker constraint this creates.

---

## 7. Compatibility contract for a new `TaskAnalysisAgent`

Anything below that changes will break a route, the SPA, or a test.

### 7.1 Route surface (must be byte-identical)
- Paths and methods exactly as in §2 rows 1–4. `/api/analyze/quick` **must stay**, even though no frontend calls it — 4 of the 6 e2e tests drive it.
- Status codes: `400` for empty `message` (#1), `404` for unknown `session_id` (#2, #3), `400` for missing requirement (#3), `400` for missing `requirement` body key (#4), `500` with body `{"error": <str>}` for pipeline failure (#3, #4).
- The **error body shape** is `{"error": "<message>"}` — `EmployerHome.jsx:34` / `AnalysisChat.jsx:64` display `e.message`, and `api.js:41,51,61` only throw on `!res.ok`, so any non-2xx must remain JSON, not HTML.

### 7.2 Response keys (exact)
- `/start`, `/reply`: `session_id`, `response`, `is_complete`, `requirement`. `EmployerHome.jsx:30` reads `result.session_id`; `AnalysisChat.jsx:34,43,80,81` read `firstReply.response`, `firstReply.is_complete`, `result.response`, `result.is_complete`.
- `/decide`: `requirement`, `tasks`, `decisions`, `jd_report`, `summary`. `/quick` additionally returns `session_id` first.
- `decisions` **must remain the wrapper object** `{"decisions":[...]}`. `AnalysisReport.jsx:66` tolerates both array and wrapper, but `_build_decision_summary` (`app.py:282`) and `generate_jd_report` (`job_design.py:108`) both call `.get("decisions", [])` — changing to a bare list breaks the backend, not the frontend.
- Per-decision keys the frontend reads: `task_id` (`AnalysisReport.jsx:67`), `recommendation.decision` (`:71-77`, `:123`), `recommendation.resource.resource_name` (`:167`; `AgentTaskCard.jsx:12`), `recommendation.reason` (`AgentTaskCard.jsx:71`, `HiringTaskCard.jsx:8`, `HybridTaskCard.jsx:6`), `recommendation.cost_hint` (`AgentTaskCard.jsx:13`, `HiringTaskCard.jsx:9`, `HybridTaskCard.jsx:7`, `JdModal.jsx:114`).
- Per-task keys the frontend reads: `id`, `name`, `description`, `estimated_hours` (`AnalysisReport.jsx:121-122,177-181`; the three card components).
- `summary` must stay an **object** with `verdict` (`AnalysisReport.jsx:80-83` also tolerates a plain string) plus `verdict_type`, `task_count`, `agent_tasks`, `human_tasks`, `needs_hiring`, `job_count`, `water_score` (`app.py:309-318`).
- `jd_report` keys asserted by tests: `needs_hiring` (bool), `job_count` (int) — `test_e2e_phase1.py:135-136`, `:185`. Frontend reads `jd_report.job_designs[]` with `task_id` / `job_title` / `required_skills` / `nice_to_have_skills` / `core_responsibilities` / `salary_range` / `work_type` (`JdModal.jsx:98-119`, `:37-46`).

### 7.3 Session semantics
- `session_id` is generated server-side and returned; must remain a plain string usable in a URL path (`/employer/analysis/:sessionId`, `/employer/report/:sessionId`).
- `/reply` and `/decide` must remain resolvable by `session_id` alone (no new required auth header) or `AnalysisChat.jsx` breaks.
- `sess["initial_input"]` feeds `original_description` for the water score (`app.py:257`) — a new agent must keep the original raw user text reachable at decide time.
- `sess["requirement"]` gating: `/decide` must still 400 when it is falsy (`app.py:241-242`).
- `sess["jd_report"]` is read by `/api/jobs` (`app.py:433-436`) and written by `/quick` (`app.py:1252`) and `/apply` (`app.py:576-580`) — keep the key name even if the store changes.

### 7.4 Monkeypatch surface (tests depend on it)
`tests/test_e2e_phase1.py:88-91` patches:
- `app.app.decompose_tasks` — so the **module-level import binding in `app/app.py:15` must survive**; if the new agent calls `agents.decompose_tasks` internally instead of the name imported into `app.app`, these tests silently stop stubbing and will hit the real LLM.
- `app.app.run_resource_decision` — same constraint.
- `app.agents.job_design.design_job` — called from inside `generate_jd_report`, so that call must stay an unqualified module-level lookup.

### 7.5 Billing invariants
- One `on_design(task, job_design)` invocation per **successfully generated** design, and only then (`job_design.py:139-140`). Tests assert 1 human task → 1 ledger row of 70 (`test_e2e_phase1.py:139-146`) and 2 human tasks → 2 rows totalling 140, 2 `agent_runs` at `charge_amount=100`, `royalty_splits.platform.amount == 30` (`:187-199`).
- `caller_id` must remain `PHASE1_CALLER_ID` (`phase1_stub_employer`) when no identity is set — `test_e2e_phase1.py:27`, `:192`.
- Billing errors must **propagate**, never be swallowed (`asset_bootstrap.py:116-118`, `job_design.py:103-105`).

---

## 8. Draft JSON Schemas (Draft 2020-12), derived only from observed fields

> Each field is annotated `[R]` observed-required (code hard-indexes it, or an existing schema lists it as required) or `[O]` observed-optional (every reader uses `.get`/`??`). `P:` = produced at, `C:` = consumed at.
> These drafts **document what exists**; they deliberately do not invent `budget`, `deadline`, `dependencies`, or a numeric salary on the decision — none of those exist in code today.

### 8.1 `Requirement`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hirenet.local/schemas/requirement.json",
  "title": "Requirement",
  "type": "object",
  "required": ["project_name", "core_description", "tasks_hint", "duration", "urgency", "budget_hint"],
  "properties": {
    "project_name":     { "type": "string", "minLength": 1 },
    "core_description": { "type": "string", "minLength": 1 },
    "tasks_hint":       { "type": "array", "items": { "type": "string" } },
    "duration":         { "type": "string", "enum": ["one-time", "ongoing", "unknown"] },
    "team_context":     { "type": "string" },
    "urgency":          { "type": "string", "enum": ["high", "medium", "low"] },
    "budget_hint":      { "type": "string", "enum": ["low", "medium", "high", "unknown"] }
  },
  "additionalProperties": true
}
```

| Field | R/O | Produced | Consumed |
|---|---|---|---|
| `project_name` | [R] by `requirement.json:5`; **[O] in practice** — every reader defaults | P: `agents.py:39` (prompt) → `agents.py:87` (`json.loads`) | C: `agents.py:124` (`.get(...,'未知')`), `job_design.py:62` |
| `core_description` | [R] | P: `agents.py:40` | C: `agents.py:125`, `job_design.py:59`, `:63` |
| `tasks_hint` | [R] by schema; [O] in code | P: `agents.py:41` | C: `agents.py:126` (`', '.join(...get(...,[]))`) |
| `duration` | [R] by schema; [O] in code; **enum violated in practice** | P: `agents.py:44` | C: `agents.py:127`, `job_design.py:64`, **`job_design.py:128` (`== "ongoing"` magic compare)** |
| `team_context` | [O] — in prompt, not in schema `required` | P: `agents.py:43` | C: `agents.py:128`, `job_design.py:65` |
| `urgency` | [R] by schema; **zero consumers** | P: `agents.py:44` | — (dead) |
| `budget_hint` | [R] by schema; [O] in code | P: `agents.py:45` | C: `job_design.py:66` (prompt text only) |

`additionalProperties: true` is **required for compatibility** — `/api/analyze/quick` passes arbitrary client dicts straight through (`app.py:1229`, `test_e2e_phase1.py:125-131`).

### 8.2 `Task`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hirenet.local/schemas/task.json",
  "title": "Task",
  "type": "object",
  "required": ["id", "name", "type"],
  "properties": {
    "id":                { "type": "string", "minLength": 1 },
    "name":              { "type": "string", "minLength": 1 },
    "description":       { "type": "string" },
    "type":              { "type": "string",
                           "enum": ["technical", "creative", "analytical", "strategic", "operational"] },
    "estimated_hours":   { "type": "number", "minimum": 0 },
    "requires_judgment": { "type": "boolean" },
    "is_recurring":      { "type": "boolean" }
  },
  "additionalProperties": true
}
```

| Field | R/O | Produced | Consumed |
|---|---|---|---|
| `id` | **[R]** — hard-indexed | P: `agents.py:106` (prompt) → `agents.py:141` | C: `agents.py:392` (`task["id"]`), `job_design.py:123`, `:90`, `asset_bootstrap.py:136`, `AnalysisReport.jsx:122`,`:184` |
| `name` | **[R]** — hard-indexed twice | P: `agents.py:107` | C: `agents.py:393`, `agents.py:183`, `job_design.py:69`, `AgentTaskCard.jsx:34` |
| `description` | **[R] by `_llm_evaluate_resource`, [O] elsewhere** — inconsistent | P: `agents.py:108` | C: `agents.py:184` (`task['description']`, hard), `job_design.py:70` (`.get`), `AnalysisReport.jsx:180` |
| `type` | **[R]** — hard-indexed | P: `agents.py:109` | C: `agents.py:394`, `agents.py:185`, `agents.py:239` (`.get(...,"")`), `job_design.py:71` |
| `estimated_hours` | [O] — no server consumer | P: `agents.py:110` | C: frontend only (`AgentTaskCard.jsx:14`, `HiringTaskCard.jsx:10`, `HybridTaskCard.jsx:8`, `AnalysisReport.jsx:181`) |
| `requires_judgment` | [O] | P: `agents.py:111` | C: `agents.py:186` (`.get`), `job_design.py:73` |
| `is_recurring` | [O] | P: `agents.py:112` | C: `agents.py:240` (`.get(...,False)`), `job_design.py:74` |

The `type` enum is **observed-violated**: `"general"` (`app.py:369`,`:477`,`:519`,`:1188`) and `"engineering"` (`test_e2e_phase1.py:60`) both flow through the same functions. A Stage-1 schema that enforces the 5-value enum will break `/api/match`, `/api/candidate-match`, `/api/my-match`, the MCP matcher, and `tests/test_e2e_phase1.py` unless those are migrated in the same change.

### 8.3 `ResourceDecision` (runtime shape — the one the API actually returns)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hirenet.local/schemas/resource_decision_runtime.json",
  "title": "ResourceDecisionRuntime",
  "type": "object",
  "required": ["task_id", "task_name", "task_type", "evaluations", "recommendation"],
  "properties": {
    "task_id":   { "type": "string" },
    "task_name": { "type": "string" },
    "task_type": { "type": "string" },
    "task_description": {
      "type": "string",
      "$comment": "read at job_design.py:126 but NEVER written by run_resource_decision (agents.py:391-397); test-only at test_e2e_phase1.py:68"
    },
    "evaluations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["resource_id", "resource_name", "resource_type"],
        "properties": {
          "can_complete":    { "type": "boolean", "$comment": "produced agents.py:190; zero consumers" },
          "confidence":      { "type": "number", "minimum": 0, "maximum": 1 },
          "reason":          { "type": "string" },
          "estimated_time":  { "type": "string" },
          "strengths":       { "type": "array", "items": { "type": "string" } },
          "resource_id":     { "type": "string" },
          "resource_name":   { "type": "string" },
          "resource_type":   { "type": "string", "enum": ["agent", "human"] }
        },
        "additionalProperties": true
      }
    },
    "recommendation": {
      "type": ["object", "null"],
      "required": ["decision", "resource", "reason", "cost_hint"],
      "properties": {
        "decision":  { "type": "string", "enum": ["agent", "human", "hybrid"] },
        "resource":  { "$comment": "the top evaluation object, verbatim" },
        "reason":    { "type": "string" },
        "cost_hint": {
          "type": "string",
          "$comment": "free text: '$0.05' | '需要评估薪资' | '混合成本' | '未知'. No currency, no amount, no negotiable flag."
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

Envelope (what the routes return): `{"decisions": [<ResourceDecisionRuntime>, ...]}` — `agents.py:451`.

| Field | R/O | Produced | Consumed |
|---|---|---|---|
| `task_id` | [R] | `agents.py:392` | `AnalysisReport.jsx:67`; `job_design.py:123` |
| `task_name` | [R] | `agents.py:393` | `job_design.py:124` |
| `task_type` | [R] | `agents.py:394` | `job_design.py:125` |
| `task_description` | **phantom** — consumed, never produced | — | `job_design.py:126` |
| `evaluations[]` | [R] (may be empty) | `agents.py:395`, `:405-406` | sorted `agents.py:408-410`; re-scanned `agents.py:431-432`; returned to client unused |
| `evaluations[].confidence` | [O] (defaulted to 0) but hard-indexed in prose | `agents.py:190` (LLM) | `agents.py:409`,`:415`,`:419`,`:422`,`:426`,`:434`; `app.py:381`,`:487`,`:526`,`:1198` |
| `evaluations[].resource_type` | [R] | `agents.py:227` | `agents.py:415`,`:422`,`:431-432` |
| `recommendation` | [R] but nullable | `agents.py:396`, `:414-447` | `app.py:286-295`; `job_design.py:109`; `AnalysisReport.jsx:71-77`,`:123` |
| `recommendation.cost_hint` | [R] when recommendation present | `agents.py:420`,`:427`,`:439`,`:447` | `AgentTaskCard.jsx:13`, `HiringTaskCard.jsx:9`, `HybridTaskCard.jsx:7`, `JdModal.jsx:114` |

**The existing `app/schemas/resource_decision.json` describes a completely different object** (`executor_type` / `payment_method` / `asset_ids` / `settlement_timing`). Stage 1 must decide explicitly whether to (a) rename the runtime object (e.g. `TaskDecision`) and keep `resource_decision.json` for the settlement dimension, or (b) reconcile them. Silently unifying them will break `test_schemas.py:140-159` and `:601-620`.

---

## 9. Golden-set seeds

### 9.1 Business-goal texts that feed `start_analysis` (real, in-repo)

| # | Text | File:line | Kind |
|---|---|---|---|
| 1 | 我想为电商平台搭建一套智能客服系统，覆盖售前咨询、售后处理和投诉响应。 | `frontend/src/pages/EmployerHome.jsx:10` | UI example chip (one click → `startAnalysis`) |
| 2 | 帮我分析最近三个季度的销售数据，找出增长机会和异常波动。 | `frontend/src/pages/EmployerHome.jsx:11` | UI example chip |
| 3 | 我需要一个实时业务数据看板，汇总销售额、客诉率和各渠道转化。 | `frontend/src/pages/EmployerHome.jsx:12` | UI example chip |
| 4 | 我需要为电商平台搭建智能客服系统... | `frontend/src/pages/EmployerHome.jsx:59` | textarea placeholder |
| 5 | 帮我为电商平台搭建智能客服系统 | `docs/demo-script.md:19` | demo script input |
| 6 | 为电商平台搭建智能客服系统 | `docs/demo-voiceover.md:23` | voiceover script input |
| 7 | 搭建一个智能客服系统 | `files/HireNet-答辩演讲稿.md:44` | pitch narrative |
| 8 | 我需要做个后端 | `tests/test_e2e_phase1.py:130` | `original_description` in the e2e test |

### 9.2 Pre-built `requirement` dicts (feed `/api/analyze/quick`)

| # | Value | File:line |
|---|---|---|
| 9 | `{"project_name":"内部工具","core_description":"搭建一个后端服务","duration":"3个月"}` | `tests/test_e2e_phase1.py:126-129` |
| 10 | `{"core_description":"搭建后端","duration":"ongoing"}` | `tests/test_e2e_phase1.py:155` |
| 11 | `{"core_description":"搭建系统","duration":"3个月"}` | `tests/test_e2e_phase1.py:182` |
| 12 | `{"core_description":"搭建后端","duration":"3个月"}` | `tests/test_e2e_phase1.py:241` |
| 13 | `VALID_REQUIREMENT` (English, schema-complete): project_name "HireNet MVP", core_description "Build a talent marketplace with AI agents", tasks_hint ["backend API","frontend UI"], duration one-time, urgency high, budget_hint medium | `tests/test_schemas.py:18-25` |

### 9.3 "Expected decomposition" data that already exists

**Almost none.** Exhaustive list:

| Source | Content | File:line | Usable as ground truth? |
|---|---|---|---|
| `ARCHITECTURE.md` | `Build an AI product landing page → copywriting → UI design → frontend development → deployment` | `ARCHITECTURE.md:593-597` | **Yes** — the only input→expected-tasks pair in the repo. Prose, not a fixture; no types/hours. |
| `test_e2e_phase1.py` stub | `{"tasks":[{"id":"t1","name":"搭建后端","type":"engineering"}]}` | `test_e2e_phase1.py:59-60` | No — a canned stub to bypass the LLM, not an expectation. Also violates the type enum. |
| `test_schemas.py` `VALID_TASK` | `{"id":"t1","name":"Build REST API","description":"Implement Flask REST endpoints","type":"technical","estimated_hours":16,"requires_judgment":false,"is_recurring":false}` | `test_schemas.py:27-35` | Shape-only fixture; not tied to any input requirement. |
| `docs/demo-voiceover.md:33` / `files/HireNet-答辩演讲稿.md:55` | narrative claim "一个需求拆成 5 个任务，4 个 Agent 能干、1 个建议招人" | — | A **target distribution**, not a labelled case. |
| `application_agent.py` `DEMO_JOBS` | 3 fully-structured job designs (全栈工程师 / AI 产品经理 / 数据分析师) with `core_responsibilities`, `required_skills`, `salary_range`, `water_score` | `application_agent.py:19-73` | Output-side reference for the JD stage; not decomposition ground truth. |

**Conclusion for the 20-case eval set**: there are 8 realistic input texts (§9.1) plus 5 requirement dicts (§9.2), and exactly **one** input→expected-decomposition pair (`ARCHITECTURE.md:593-597`). Everything else must be authored fresh. The three `EmployerHome.jsx` chips are the highest-value seeds because they are what a demo audience actually clicks, and they span three of the five task types (operational/technical, analytical, technical).

---

## 10. Existing test coverage of this path

| File | Tests collected | What it asserts about this path | What it does NOT cover |
|---|---|---|---|
| `tests/test_e2e_phase1.py` | 6 | 4 tests POST `/api/analyze/quick` (`:122`, `:153`, `:180`, `:239`). Asserts `200`, `jd_report.needs_hiring is True`, `jd_report.job_count == 1\|2`, and then the **billing** consequences: 1 or 2 `royalty_ledger` creator rows of 70, `currency == "USD"`, `status == "accrued"`, `chain is None`, `agent_runs.charge_amount == 100`, `royalty_splits.platform.amount == 30`, `summarize_creator_earnings` totals. Stubs only `app.app.decompose_tasks`, `app.app.run_resource_decision`, `app.agents.job_design.design_job` (`:88-91`). | The **shape** of `tasks`, `decisions`, `summary` — never inspected. `/api/analyze/start`, `/reply`, `/decide` — **zero requests**. `RequirementAnalysisAgent`, `is_complete`, `extract_requirement`, `_filter_resources_for_task`, `_llm_evaluate_resource`, `run_resource_decision`'s real logic, `_build_decision_summary`, `_publish_jobs` — **zero direct coverage**. |
| `tests/test_schemas.py` | 89 | `TestRequirementSchema` (`:96-113`, 4 tests): valid passes, missing `urgency` blocked, bad `duration` enum blocked, bad `budget_hint` enum blocked. `TestTaskSchema` (`:118-135`, 4): valid passes, missing `id` blocked, bad `type` enum blocked, negative `estimated_hours` blocked. `TestResourceDecisionSchema` (`:140-159`, 4) + `TestResourceDecisionConditionalAssetIds` (`:601+`, 4). Plus `parse_llm_json` (10) and `validate_llm_output` (10) behaviour. | These validate the **schema files in isolation**. No test connects a schema to a pipeline function — the agents never call `validate`, so all 12 requirement/task/decision schema tests are green while production emits unvalidated LLM output. |
| `tests/test_smoke.py` | 6 | SPA routes and `/api/health` return 200. | nothing pipeline-specific |
| `tests/test_demo_identity_and_publish.py` | 15 | `/api/jobs/publish` validation and `/api/candidate/analyze` bullet parsing (`:206`, `:241`, `:253`). | the analyze pipeline itself |
| `tests/test_mcp_integration.py` | 15 | MCP tool-name routing, URL scheme rejection, pact-settle MCP invocation. | `hirenet_analyze_requirements` and `hirenet_match_candidates` handlers (`app.py:1160-1181`) are untested |

**Suite health note**: `.venv/bin/python -m pytest --collect-only -q tests/` currently **aborts collection** — `tests/test_mcp_server_demo.py:7` → `app/mcp_servers/customer_service.py:14` → `ModuleNotFoundError: No module named 'flask_cors'`. 591 tests collect, 1 error, `Interrupted`. Per-file collection works. Fix or deselect that file before you rely on a green baseline for the refactor.

**Coverage verdict**: the pipeline is covered **only through its billing side effect, and only via the one entry point the product does not use**. The conversational path that ships to users has zero automated tests.

---

## 11. Risks & recommendations, ranked

| Rank | Risk | Why it bites Stage 1 | Recommendation |
|---|---|---|---|
| 1 | **No test covers `/start` `/reply` `/decide`.** A refactor of `RequirementAnalysisAgent` cannot be verified. | The only safety net (`test_e2e_phase1.py`) stubs out the two functions you are about to rewrite and never touches the conversational route. | **Before touching `agents.py`**, add characterisation tests for `/api/analyze/start` and `/reply` with a fake LLM client (patch `agents.get_llm_client`), asserting the 4 response keys, the 404, and the marker→`is_complete` transition. Then refactor. |
| 2 | **Monkeypatch binding fragility.** Tests patch `app.app.decompose_tasks` / `app.app.run_resource_decision` (`test_e2e_phase1.py:88-89`). | If `TaskAnalysisAgent` calls `agents.decompose_tasks` internally, the stub stops applying and 4 e2e tests silently hit the real Zhipu API (or fail with no API key). | Either keep the module-level names imported in `app/app.py:15` as the call sites, or update the tests in the same commit and assert the stub was actually used (call counter). |
| 3 | **No termination cap on the multi-turn loop** (`agents.py:78` marker only). | A model that never emits `[REQUIREMENT_COMPLETE]` loops forever; the browser has no cap either (`AnalysisChat.jsx`). Also unbounded `self.history` growth → cost growth per turn. | Give `TaskAnalysisAgent` an explicit `max_turns` (mirror `CareerStrategyAgent.force_generate_strategy` `agents.py:340-379`), and a forced-extraction fallback. Return a new response key only if you are prepared to keep `is_complete` semantics unchanged. |
| 4 | **`recommendation: None` → `AttributeError` → 500** in `_build_decision_summary` and `generate_jd_report`. | `.get("recommendation", {})` does not defend against a present-but-`None` value (`app.py:286`,`:290`,`:294`; `job_design.py:109`). | Make `recommendation` non-nullable in the new agent (emit an explicit `{"decision":"human", ...}` when no evaluations), or fix the three call sites to `(d.get("recommendation") or {})`. |
| 5 | **`task_description` is consumed but never produced** (`job_design.py:126` vs `agents.py:391-397`). | Every real JD is generated from an empty task description; the "去水" water score is comparing against nothing. This is a silent quality bug that a refactor is the natural moment to fix. | Have the new agent carry `task_description` (and `estimated_hours`, `requires_judgment`, `is_recurring`) onto the decision record, and delete the synthetic-task fabrication at `job_design.py:122-130`. |
| 6 | **Bare `json.loads` on three LLM boundaries** while a battle-tested `validate_llm_output` with repair-retry + fallback sits unused. | `agents.py:87`, `:141`, `job_design.py:89`; the ad-hoc brace counter at `agents.py:205-224` is string-unaware and will mis-parse any JSON containing `{` or `}` inside a value. | Route all three through `app/services/validation.py:parse_llm_json` / `validate_llm_output(raw, "task", llm_fn=..., fallback=...)`. This is the single highest-leverage change and it is additive. |
| 7 | **Two objects named "resource decision"** (`agents.py:391-448` vs `app/schemas/resource_decision.json`). | Stage 1 will produce a third name if this is not settled first; `test_schemas.py:140-159` locks the schema shape. | Decide and write it down: rename the runtime object to `TaskDecision`, add `app/schemas/task_decision.json`, leave `resource_decision.json` alone. |
| 8 | **`_publish_jobs` is dead** (`app.py:321-328` filters on a `job_id` that `job_design.py:90-91` never sets), and `/decide` never writes `sess["jd_report"]` while `/quick` does (`app.py:1252`). | JDs from the real user flow never reach `/api/jobs`. Fixing it changes observable behaviour of `/api/jobs`, so do it deliberately, with a test. | Stamp a `job_id` in `design_job`, and add `sess["jd_report"] = jd_report` to `run_decision` — but treat both as behaviour changes with their own tests, not refactor collateral. |
| 9 | **Zero token/cost/latency accounting** despite `agent_runs` having the columns (`agent_run.json:18-21`, always NULL). | Stage 1 is the moment to thread `resp.usage` through — retrofitting later means touching every LLM call again. | Have `TaskAnalysisAgent` return a `usage` record per call and pass `input_tokens`/`output_tokens`/`time_ms` into `record_agent_run` via `build_job_design_recorder` (`asset_bootstrap.py:132-142`). Do not change `charge_amount` semantics. |
| 10 | **Three task-type vocabularies** (`technical/creative/…`, `"general"`, `"engineering"`). | Enforcing the enum in the new agent breaks 4 routes and 1 test file. | Keep the enum advisory in Stage 1 (validate-and-log, do not reject); migrate `"general"` call sites (`app.py:369`,`:477`,`:519`,`:1188`) in a separate change. |
| 11 | **Module-global session store holding a live agent object** (`app.py:23`, `:165-170`); single-worker-only, no eviction, no ownership check, cross-tenant read at `app.py:432-437`. | A `TaskAnalysisAgent` that is a plain object is *harder* to persist later than one that serialises its state. | Design the new class so its entire state is a serialisable dict (`{history, requirement, initial_input, turn_count}`) with `from_state()` / `to_state()`, even if Stage 1 still stores it in the same dict. That is the cheap change that unblocks Redis/SQLite later. |
| 12 | **Threshold policy + Chinese UI prose + demo-fixture cost lookup all inside `run_resource_decision`** (`agents.py:415-447`, `:420`). | Untestable without an LLM; unchangeable without touching prose. | Extract a pure `decide(evaluations) -> recommendation` function with named constants; unit-test it with synthetic evaluations (no LLM). Keep the emitted Chinese strings byte-identical — they are rendered verbatim by three card components. |
| 13 | **`str(e)` leaked to the client on 500** (`app.py:277`, `:1267`). | Can leak the API base URL or prompt content from an OpenAI SDK error. | Log the exception (already done via `current_app.logger.exception`) and return a generic message. Keep the `{"error": ...}` key. |
| 14 | Broken suite collection (`flask_cors` missing) and a dead frontend endpoint (`/api/match-candidates`, `api.js:118`). | Noise that will be blamed on the refactor. | Fix or document both before starting, in a separate commit. |

---

## Appendix — quick reference of every file:line cited

`app/app.py`: 15, 20, 23-24, 49-53, 56-63, 76-81, 84-130, 133-145, 150-186, 189-218, 223-277, 280-318, 321-328, 349-389, 421-448, 452-499, 501-541, 543-582, 942-1030, 1084-1128, 1130-1218, 1222-1267, 1895-2005
`app/agents/agents.py`: 15-23, 28-46, 49-87, 92-115, 118-141, 146-160, 163-165, 168-228, 231-269, 274-379, 382-451
`app/agents/job_design.py`: 11-17, 20-42, 45-92, 95-154, 157-167
`app/agents/candidate_profile.py`: 6-19, 21-61, 63-82, 85-118
`app/agents/application_agent.py`: 15, 19-73, 80-86
`app/services/validation.py`: 46-60, 63-66, 96-122, 125-151, 154-162, 165-218
`app/services/agent_run_recording.py`: 37-220 (esp. 104-131, 200-205, 210-214)
`app/services/asset_bootstrap.py`: 22-50, 53-105, 108-144
`app/schemas/`: `requirement.json:5-13`, `task.json:5-16`, `resource_decision.json:6-19`, `job_design.json:5-42`, `agent_run.json:6-32`
`frontend/src/services/api.js`: 35-63, 67-71, 117-125, 154-188
`frontend/src/pages/EmployerHome.jsx`: 9-13, 29-36, 59
`frontend/src/pages/AnalysisChat.jsx`: 27-45, 50-69, 71-87
`frontend/src/pages/AnalysisReport.jsx`: 64-83, 121-145, 160-205
`frontend/src/components/`: `AgentTaskCard.jsx:11-14,69-83`, `HiringTaskCard.jsx:7-10,68,76`, `HybridTaskCard.jsx:5-8`, `JdModal.jsx:37-46,98-119,114`
`tests/test_e2e_phase1.py`: 27-29, 47-56, 59-82, 85-91, 98-112, 115-146, 149-165, 168-199, 202-255
`tests/test_schemas.py`: 18-25, 27-35, 37-42, 96-113, 118-135, 140-159, 335-375, 379-451, 601-620
`tests/conftest.py`: 10-27
`ARCHITECTURE.md`: 565-616 (esp. 593-597)
`docs/demo-script.md:19`, `docs/demo-voiceover.md:23,33`, `files/HireNet-答辩演讲稿.md:44,55`
