"""
HireNet Flask Application
"""
import os
import json
import math
import hashlib
import secrets
import decimal
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, Blueprint, request, jsonify, session, render_template, current_app, make_response, send_from_directory
from dotenv import load_dotenv

from app.agents.agents import RequirementAnalysisAgent, decompose_tasks, run_resource_decision, CareerStrategyAgent
from app.agents.job_design import generate_jd_report
from app.agents.task_analysis import TaskAnalysisAgent
from app.services.auth import login_required
from app.storage.analysis_traces import build_trace, insert_trace
from app.storage.db import init_db
from app.storage.pacts import (
    create_pact,
    get_pact,
    transition_pact,
    update_pact_fields,
)

main = Blueprint('main', __name__)

# In-memory session store for demo (use Redis in production)
analysis_sessions = {}
career_sessions = {}
# ─── Authorization mandate (pact) lifecycle store ────────────────────────────
#
# Stage 2 / WP-G: pacts live in SQLite (table `pacts`, DAO
# `app/storage/pacts.py`), NOT in a module-level dict. That means a pact
# survives a restart and can be created on one worker and settled on another,
# and it means the approved → settled / approved → settling claim is a
# conditional `UPDATE … WHERE status = ?` whose rowcount — not a
# process-local lock — is what stops two concurrent settles double-billing
# the creator. See the WP-G notes in app/storage/pacts.py.
#
# The other stores below are still in-memory demo state; wsgi.py documents
# the single-worker constraint they impose.

# Global published jobs — company analysis pushes here; candidate side reads from here
published_jobs = []

# User profile state: EXP, level, completed tasks
user_profile_state = {
    "exp": 300,
    "level": 2,
    "exp_to_next": 500,
    "completed_tasks": [],
    "skill_boosts": {},
    "profile_completeness": 78,
}
EXP_PER_LEVEL = 500


# ─── Demo identity system ─────────────────────────────────────────────────────
#
# ⚠️ DEMO ONLY — NOT REAL AUTH ⚠️
#
# Four hard-coded identities the demo can switch between via a header or cookie.
# Real per-user authentication is deferred to Phase 2. Until then, treat the
# identity here as the caller — any endpoint that needs caller_id / creator_id
# should resolve through get_current_identity() so identity-switching in the UI
# changes what the user sees (jobs they posted, royalties they earn).
DEMO_IDENTITIES = {
    "li_boss":    {"id": "li_boss",    "name": "李老板", "role": "enterprise", "avatar": "🏢"},
    "zhang_ai":   {"id": "zhang_ai",   "name": "张AI",   "role": "creator",    "avatar": "🤖"},
    "wang_dev":   {"id": "wang_dev",   "name": "王工",    "role": "jobseeker",  "avatar": "👤"},
    "zhao_design":{"id": "zhao_design","name": "赵设计", "role": "creator",    "avatar": "🎨"},
}


def get_current_identity(default_id: str | None = None) -> dict:
    """Resolve the current identity from the request.

    Lookup order:
      1. JWT Bearer token (real auth — server-derived, client cannot spoof)
      2. X-Demo-Identity request header (Demo dev mode)
      3. demo_identity cookie (Demo dev mode)
      4. ``default_id`` / PHASE1_CALLER_ID fallback

    JWT wins over header / cookie unconditionally — once a request carries a
    valid token, X-Demo-Identity is ignored even if present (closes the
    IDOR vector where a logged-in user could claim someone else's id by
    sending a forged header). The token's `sub` must resolve to a real row
    in the users table; otherwise we degrade to the Demo layers so a stale
    token cannot inject a phantom identity into the system.

    Callers in creator contexts should pass PHASE1_CREATOR_ID as the
    default so the historical IDOR-guarded behavior is preserved when
    nobody has logged in or switched identity.
    """
    # 1. JWT — highest priority, server-side authority
    from app.services.auth import get_jwt_user
    jwt_user = get_jwt_user()
    if jwt_user is not None:
        from app.storage.users import get_user
        row = get_user(current_app.config["DATABASE_PATH"], jwt_user["id"])
        if row is not None:
            avatar = DEMO_IDENTITIES.get(row["id"], {}).get("avatar", "👤")
            return {
                "id": row["id"],
                "name": row["name"],
                "role": row["role"],
                "avatar": avatar,
            }
        # JWT sub points at a missing user — fall through to demo layers
        # rather than fabricate an identity from the token alone.

    # 2-3. Demo header / cookie (dev mode)
    raw = request.headers.get("X-Demo-Identity") or request.cookies.get("demo_identity")
    if raw:
        raw = raw.strip()
        if raw in DEMO_IDENTITIES:
            return DEMO_IDENTITIES[raw]

    # 4. Phase 1 stub fallback
    fallback_id = default_id or current_app.config.get("PHASE1_CALLER_ID", "phase1_stub_employer")
    return {"id": fallback_id, "name": "Demo", "role": "enterprise", "avatar": "👤"}


def _job_design_recorder(usage: dict | None = None):
    """Build the on_design billing callback for the current app/request.

    Thin wrapper over the service-layer recorder so the routes stay thin: reads
    the bootstrapped asset id and resolves the caller from the current Demo
    identity (header/cookie). Real per-user auth lands in Phase 2.

    `usage` (D8) is the v2 pipeline's per-session totals; it only fills the
    telemetry columns of agent_runs (input_tokens / output_tokens /
    llm_cost_usd / time_ms). `charge_amount` and the split are untouched by it.
    Omitted on the v1 path, where nothing measures token usage — those columns
    stay NULL exactly as they are today.
    """
    from app.services.asset_bootstrap import build_job_design_recorder
    return build_job_design_recorder(
        current_app.config["DATABASE_PATH"],
        current_app.config["JOB_DESIGN_ASSET_ID"],
        get_current_identity()["id"],
        usage=usage,
    )


# ─── TaskAnalysisAgent v2 wiring (D2) ─────────────────────────────────────────
#
# `HIRENET_TASK_AGENT` picks which pipeline serves the four analysis routes:
#   v1 (default, and anything that is not exactly "v2") — RequirementAnalysisAgent
#       plus the module-level `decompose_tasks` / `run_resource_decision`
#       bindings imported above. Byte-identical to what shipped; the tests in
#       tests/test_analyze_routes_v1.py and tests/test_e2e_phase1.py pin it, and
#       audit §7.4 requires those two names to stay the actual call sites.
#   v2 — app/agents/task_analysis.TaskAnalysisAgent: one class for the whole
#       pipeline, every LLM output schema-validated, a turn cap, token
#       accounting, and one analysis_traces row per step.
#
# The flag is read PER REQUEST, not at import: a test (and an operator) has to
# be able to flip it without reimporting the app.

TASK_AGENT_ENV = "HIRENET_TASK_AGENT"


def _task_agent_version() -> str:
    """Which analysis pipeline serves this request: "v1" (default) or "v2"."""
    return "v2" if os.getenv(TASK_AGENT_ENV, "").strip().lower() == "v2" else "v1"


def _v2_trace_writer(session_id: str, sess: dict):
    """Return the agent's `on_llm_call` hook: one analysis_traces row per call.

    `step_no` lives in the session dict rather than on the agent, because the
    agent is rebuilt from its serialised state on every request (D4) — a
    counter held on the instance would restart at 0 on each turn and the replay
    would interleave nonsensically.

    Trace writes are best-effort by construction: TaskAnalysisAgent._emit
    catches whatever this raises and logs it. Losing telemetry must not lose
    the employer's analysis.
    """
    db_path = current_app.config["DATABASE_PATH"]

    def on_llm_call(record: dict) -> None:
        step_no = sess.get("trace_step", 0)
        sess["trace_step"] = step_no + 1
        insert_trace(db_path, build_trace(
            trace_id=secrets.token_hex(16),
            session_id=session_id,
            step_no=step_no,
            stage=record["stage"],
            model=record["model"],
            messages=record.get("messages") or [],
            response_text=record.get("response_text") or "",
            parsed_ok=record.get("parsed_ok", False),
            input_tokens=record.get("input_tokens"),
            output_tokens=record.get("output_tokens"),
            time_ms=record.get("time_ms"),
        ))

    return on_llm_call


def _write_decide_trace(session_id: str, sess: dict, decisions: dict) -> None:
    """Write the synthetic `decide` row that closes out a v2 run.

    `decide` is a pure function (app/agents/decision_policy.py) — no LLM, so no
    `on_llm_call` fires for it. Without this row a replay stops at the last
    `evaluate` step and the routing outcome, which is the whole point of the
    run, is the one thing missing. model="policy" says plainly that no model
    was involved; parsed_ok is True because a pure function cannot fail to parse.
    """
    step_no = sess.get("trace_step", 0)
    sess["trace_step"] = step_no + 1
    try:
        insert_trace(current_app.config["DATABASE_PATH"], build_trace(
            trace_id=secrets.token_hex(16),
            session_id=session_id,
            step_no=step_no,
            stage="decide",
            model="policy",
            messages=[],
            response_text=json.dumps(decisions, ensure_ascii=False),
            parsed_ok=True,
        ))
    except Exception:
        current_app.logger.exception("failed to write the decide trace row")


def _new_v2_session(session_id: str, initial_input: str, requirement=None) -> dict:
    """Create the session record for a v2 run.

    Keeps every key the other routes already read off `analysis_sessions`
    (`initial_input`, `requirement`, `jd_report`, `history`) and replaces the
    live agent object with `agent_state` — the serialised dict (D4). `agent` is
    kept as an explicit None so any code that does `sess["agent"]` still finds
    the key; nothing in the v2 path reads it.
    """
    return {
        "agent": None,
        "agent_version": "v2",
        "agent_state": None,
        "initial_input": initial_input,
        "history": [initial_input] if initial_input else [],
        "requirement": requirement,
        "trace_step": 0,
    }


def _v2_agent(session_id: str, sess: dict) -> TaskAnalysisAgent:
    """Rebuild the session's agent from its stored state, traces wired up."""
    hook = _v2_trace_writer(session_id, sess)
    state = sess.get("agent_state")
    if state is None:
        return TaskAnalysisAgent(on_llm_call=hook)
    return TaskAnalysisAgent.from_state(state, on_llm_call=hook)


def _v2_pipeline(session_id: str, sess: dict) -> tuple[list, dict, TaskAnalysisAgent]:
    """Decompose + route one requirement through TaskAnalysisAgent.

    Returns `(tasks, decisions, agent)`; `decisions` is the wrapper object
    `{"decisions": [...]}` the frontend and `_build_decision_summary` expect.
    """
    agent = _v2_agent(session_id, sess)
    tasks = agent.decompose()
    decisions = agent.decide_all()
    _write_decide_trace(session_id, sess, decisions)
    sess["agent_state"] = agent.to_state()
    return tasks, decisions, agent


# ─── Requirement Analysis API ─────────────────────────────────────────────────

@main.route("/api/analyze/start", methods=["POST"])
def start_analysis():
    """Start a new requirement analysis session"""
    data = request.get_json()
    initial_input = data.get("message", "").strip()

    if not initial_input:
        return jsonify({"error": "Message is required"}), 400

    session_id = secrets.token_hex(8)

    if _task_agent_version() == "v2":
        sess = _new_v2_session(session_id, initial_input)
        analysis_sessions[session_id] = sess
        agent = _v2_agent(session_id, sess)
        result = agent.start(initial_input)
        # The whole agent goes back into the store as a plain dict (D4): this
        # route never holds a live agent object across requests.
        sess["agent_state"] = agent.to_state()
        sess["requirement"] = result["requirement"]
        return jsonify({
            "session_id": session_id,
            "response": result["response"],
            "is_complete": result["is_complete"],
            "requirement": result["requirement"],
            # Additive key, allowed by §0 of the spec: without it a client has
            # no way to tell "still clarifying" from "hit the turn cap".
            "turn_count": result["turn_count"],
        })

    # Create new analysis session
    agent = RequirementAnalysisAgent()
    response = agent.start(initial_input)

    # Store session
    analysis_sessions[session_id] = {
        "agent": agent,
        "initial_input": initial_input,
        "history": [initial_input],
        "requirement": None,
    }

    is_complete = agent.is_complete(response)
    requirement = None
    if is_complete:
        try:
            requirement = agent.extract_requirement(response)
            analysis_sessions[session_id]["requirement"] = requirement
        except Exception:
            is_complete = False

    return jsonify({
        "session_id": session_id,
        "response": response,
        "is_complete": is_complete,
        "requirement": requirement,
    })


@main.route("/api/analyze/reply", methods=["POST"])
def reply_analysis():
    """Continue requirement analysis conversation"""
    data = request.get_json()
    session_id = data.get("session_id")
    message = data.get("message", "").strip()

    if session_id not in analysis_sessions:
        return jsonify({"error": "Session not found"}), 404

    sess = analysis_sessions[session_id]

    # Dispatch on what the SESSION was started with, not on the current flag:
    # a v1 session holds a live RequirementAnalysisAgent and a v2 session holds
    # a state dict, so flipping HIRENET_TASK_AGENT mid-conversation must not
    # change which pipeline continues an already-open session.
    if sess.get("agent_version") == "v2":
        agent = _v2_agent(session_id, sess)
        result = agent.reply(message)
        sess["agent_state"] = agent.to_state()
        sess["history"].append(message)
        sess["requirement"] = result["requirement"]
        return jsonify({
            "session_id": session_id,
            "response": result["response"],
            "is_complete": result["is_complete"],
            "requirement": result["requirement"],
            "turn_count": result["turn_count"],
        })

    agent = sess["agent"]
    response = agent.reply(message)
    sess["history"].append(message)

    is_complete = agent.is_complete(response)
    requirement = None
    if is_complete:
        try:
            requirement = agent.extract_requirement(response)
            sess["requirement"] = requirement
        except Exception:
            is_complete = False

    return jsonify({
        "session_id": session_id,
        "response": response,
        "is_complete": is_complete,
        "requirement": requirement,
    })


# ─── Task Decomposition + Resource Decision ───────────────────────────────────

@main.route("/api/analyze/decide", methods=["POST"])
def run_decision():
    """
    Run full pipeline:
    1. Decompose requirement into tasks
    2. For each task, evaluate all resources (agents + candidates)
    3. Make final decision: agent / human / hybrid
    4. If human needed, generate job design
    """
    data = request.get_json()
    session_id = data.get("session_id")

    if session_id not in analysis_sessions:
        return jsonify({"error": "Session not found"}), 404

    sess = analysis_sessions[session_id]
    requirement = sess.get("requirement")

    if not requirement:
        return jsonify({"error": "Requirement analysis not complete"}), 400

    try:
        if sess.get("agent_version") == "v2":
            # Steps 1+2 in one object; usage totals (D8) ride along to billing.
            tasks, decisions, agent = _v2_pipeline(session_id, sess)
            recorder = _job_design_recorder(usage=agent.usage_summary())
        else:
            # Step 1: Decompose tasks
            task_data = decompose_tasks(requirement)
            tasks = task_data.get("tasks", [])

            # Step 2: Resource decision for each task
            decisions = run_resource_decision(tasks)

            recorder = _job_design_recorder()

        # Step 3: Generate job designs if needed. Each successful design bills one
        # Job Design SkillAsset invocation to its creator via the U4 path.
        jd_report = generate_jd_report(
            decisions,
            requirement,
            original_description=sess.get("initial_input", ""),
            on_design=recorder,
        )
        # Stage 1 / D11a (audit risk 8): /quick has always written this
        # (app.py:1252) and /decide never did, so GET /api/jobs — which reads
        # `analysis_sessions[*]["jd_report"]` — showed JDs from the demo
        # shortcut and nothing from the real conversational flow. Route-level
        # fix: applies to the v1 and v2 paths alike.
        sess["jd_report"] = jd_report

        # Step 4: Build summary
        summary = _build_decision_summary(tasks, decisions, jd_report)

        # NO automatic publication here. Analysing a requirement is not the same
        # act as posting a job to the public board: publication goes through
        # `POST /api/jobs/publish`, which stamps `publisher_id` / `company` /
        # `published_at` and is the employer's explicit consent. The JD is in
        # the response and in `sess["jd_report"]`; the client publishes the ones
        # the employer chooses, by `job_id`.
        return jsonify({
            "requirement": requirement,
            "tasks": tasks,
            "decisions": decisions,
            "jd_report": jd_report,
            "summary": summary,
        })

    except Exception:
        # Log the exception server-side; do NOT put str(e) in the response.
        # These failures come out of the OpenAI SDK, so the message can carry
        # the API base URL, request ids, or a chunk of the prompt. The client
        # only needs the `{"error": ...}` shape the SPA already renders.
        current_app.logger.exception("run_decision failed")
        return jsonify({"error": "analysis failed"}), 500


def _build_decision_summary(tasks, decisions, jd_report) -> dict:
    """Build human-readable summary of the decision"""
    all_decisions = decisions.get("decisions", [])

    # `(d.get("recommendation") or {})`, not `d.get("recommendation", {})`:
    # run_resource_decision seeds the key with None and only overwrites it when
    # a task has at least one surviving evaluation (agents.py:396, :414). The
    # two-arg default fires on a MISSING key, not on a present None, so the old
    # form chained .get() off None -> AttributeError -> HTTP 500 for any task
    # nothing could be evaluated against.
    agent_count = sum(
        1 for d in all_decisions
        if (d.get("recommendation") or {}).get("decision") == "agent"
    )
    human_count = sum(
        1 for d in all_decisions
        if (d.get("recommendation") or {}).get("decision") == "human"
    )
    hybrid_count = sum(
        1 for d in all_decisions
        if (d.get("recommendation") or {}).get("decision") == "hybrid"
    )

    total = len(all_decisions)

    if human_count == 0 and hybrid_count == 0:
        verdict = "无需招聘，所有任务可由 Agent 完成"
        verdict_type = "agent_only"
    elif agent_count == 0:
        verdict = "建议招聘，当前 Agent 无法满足需求"
        verdict_type = "human_only"
    else:
        verdict = f"建议混合方案：{agent_count} 个任务用 Agent，{human_count + hybrid_count} 个任务需要人类"
        verdict_type = "hybrid"

    return {
        "verdict": verdict,
        "verdict_type": verdict_type,
        "task_count": total,
        "agent_tasks": agent_count,
        "human_tasks": human_count + hybrid_count,
        "needs_hiring": jd_report.get("needs_hiring", False),
        "job_count": jd_report.get("job_count", 0),
        "water_score": jd_report.get("average_water_score"),
    }


# `_publish_jobs` used to live here: it pushed every generated JD straight into
# `published_jobs` from /decide and /quick. Removed — publication is
# `POST /api/jobs/publish` and nothing else, so a JD reaches the public board
# only when someone decided to put it there.


# ─── Candidate Side ───────────────────────────────────────────────────────────

@main.route("/api/candidates", methods=["GET"])
def list_candidates():
    """List demo candidates with their profiles"""
    from app.agents.candidate_profile import DEMO_CANDIDATES, build_candidate_profile

    candidates = []
    for cid in DEMO_CANDIDATES:
        try:
            profile = build_candidate_profile(cid)
            candidates.append(profile)
        except Exception as e:
            candidates.append({"id": cid, "error": str(e)})

    return jsonify({"candidates": candidates})


@main.route("/api/match", methods=["POST"])
def match_candidates():
    """Match candidates against a job design"""
    data = request.get_json()
    job_design = data.get("job_design")
    session_id = data.get("session_id")

    if not job_design:
        return jsonify({"error": "job_design is required"}), 400

    from app.agents.candidate_profile import get_all_resources
    from app.agents.agents import evaluate_resource_for_task

    resources = get_all_resources()
    human_resources = [r for r in resources if r["type"] == "human"]

    task = {
        "id": "match",
        "name": job_design.get("job_title", ""),
        "description": "、".join(job_design.get("core_responsibilities", [])),
        "type": "general",
        "requires_judgment": True,
        "is_recurring": True,
        "estimated_hours": 160,  # monthly
    }

    matches = []
    for resource in human_resources:
        try:
            eval_result = evaluate_resource_for_task(resource, task)
        except Exception as e:
            print(f"Evaluation failed for {resource.get('id')}: {e}")
            eval_result = {"confidence": 0.5, "reason": "评估超时，使用默认分数", "strengths": []}
        matches.append({
            "candidate": resource,
            "evaluation": eval_result,
            "match_score": round(eval_result.get("confidence", 0) * 100),
        })

    matches.sort(key=lambda x: x["match_score"], reverse=True)

    return jsonify({"matches": matches})


# ─── Candidate Side (extended) ────────────────────────────────────────────────

@main.route("/api/candidates/<candidate_id>/profile", methods=["GET"])
def get_candidate_profile(candidate_id):
    """Get full profile for a single candidate"""
    from app.agents.candidate_profile import build_candidate_profile, DEMO_CANDIDATES
    if candidate_id not in DEMO_CANDIDATES:
        return jsonify({"error": "Unknown candidate"}), 404
    try:
        profile = build_candidate_profile(candidate_id)
        return jsonify({"profile": profile})
    except Exception as e:
        # Return static fallback if token not configured
        from app.agents.candidate_profile import DEMO_CANDIDATES
        meta = DEMO_CANDIDATES[candidate_id]
        return jsonify({"profile": {
            "id": candidate_id,
            "type": "human",
            "name": meta["name"],
            "role_hint": meta["role_hint"],
            "skills": [],
            "experience": [],
            "preferences": [],
            "bio": "",
            "capability_summary": "暂无详细信息",
        }})


@main.route("/api/jobs", methods=["GET"])
def list_jobs():
    """List available jobs for candidate-side matching.

    Three sources, in priority order: demo jobs, JDs generated by company-side
    analysis sessions, and JDs explicitly pushed through POST /api/jobs/publish
    (the JdModal "发布岗位" path). Dedup by job_id so a session-generated JD
    that was later republished isn't surfaced twice.
    """
    from app.agents.application_agent import get_demo_jobs

    extra_jobs = []
    for sess in analysis_sessions.values():
        jd_report = sess.get("jd_report")
        if jd_report and jd_report.get("job_designs"):
            extra_jobs.extend(jd_report["job_designs"])

    seen_ids: set = set()
    jobs: list = []
    for job in get_demo_jobs() + extra_jobs + list(published_jobs):
        jid = job.get("job_id")
        # Jobs without job_id keep the legacy "always include" behaviour so
        # demo data doesn't suddenly disappear if it ever lacks the field.
        if jid and jid in seen_ids:
            continue
        if jid:
            seen_ids.add(jid)
        jobs.append(job)
    return jsonify({"jobs": jobs})


@main.route("/api/candidate-match", methods=["POST"])
def candidate_match():
    """Match a candidate against all available jobs"""
    from app.agents.application_agent import get_demo_jobs
    from app.agents.candidate_profile import build_candidate_profile, DEMO_CANDIDATES
    from app.agents.agents import evaluate_resource_for_task

    data = request.get_json()
    candidate_id = data.get("candidate_id")

    if candidate_id not in DEMO_CANDIDATES:
        return jsonify({"error": "Unknown candidate"}), 404

    try:
        profile = build_candidate_profile(candidate_id)
    except Exception:
        meta = DEMO_CANDIDATES[candidate_id]
        profile = {"id": candidate_id, "type": "human", "name": meta["name"],
                   "role_hint": meta["role_hint"], "skills": [], "experience": [],
                   "capability_summary": meta["role_hint"]}

    jobs = get_demo_jobs()
    results = []
    for job in jobs:
        task = {
            "id": job.get("job_id", ""),
            "name": job.get("job_title", ""),
            "description": "、".join(job.get("core_responsibilities", [])),
            "type": "general",
            "requires_judgment": True,
            "is_recurring": True,
            "estimated_hours": 160,
        }
        try:
            eval_result = evaluate_resource_for_task(profile, task)
        except Exception as e:
            print(f"Evaluation failed for job {job.get('job_id')}: {e}")
            eval_result = {"confidence": 0.5, "reason": "评估超时，使用默认分数", "strengths": []}
        results.append({
            "job": job,
            "match_score": round(eval_result.get("confidence", 0) * 100),
            "reason": eval_result.get("reason", ""),
            "strengths": eval_result.get("strengths", []),
        })

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return jsonify({"candidate": profile, "matches": results})


@main.route("/api/my-match", methods=["GET"])
def my_match():
    """Match a generic user profile against all published jobs."""
    from app.agents.application_agent import get_demo_jobs
    from app.agents.agents import evaluate_resource_for_task

    profile = {"id": "current_user", "type": "human", "name": "求职者",
               "capabilities": [], "capability_summary": ""}

    all_jobs = get_demo_jobs() + published_jobs
    results = []
    for job in all_jobs:
        task = {
            "id": job.get("job_id", ""),
            "name": job.get("job_title", ""),
            "description": "、".join(job.get("core_responsibilities", [])),
            "type": "general",
            "requires_judgment": True,
            "is_recurring": True,
            "estimated_hours": 160,
        }
        try:
            eval_result = evaluate_resource_for_task(profile, task)
        except Exception:
            eval_result = {"confidence": 0.5, "reason": "评估超时，使用默认分数", "strengths": []}
        results.append({
            "job": job,
            "match_score": round(eval_result.get("confidence", 0) * 100),
            "reason": eval_result.get("reason", ""),
            "strengths": eval_result.get("strengths", []),
            "is_published": job in published_jobs,
        })

    results.sort(key=lambda x: x["match_score"], reverse=True)
    return jsonify({
        "profile": profile,
        "matches": results,
        "total_jobs": len(all_jobs),
        "published_jobs": len(published_jobs),
    })


@main.route("/api/apply", methods=["POST"])
def apply_to_job():
    """Generate cover letter and record application"""
    from app.agents.application_agent import generate_cover_letter, apply_to_job as _apply
    from app.agents.candidate_profile import build_candidate_profile, DEMO_CANDIDATES

    data = request.get_json()
    candidate_id = data.get("candidate_id")
    job_design = data.get("job_design")

    if not candidate_id or not job_design:
        return jsonify({"error": "candidate_id and job_design are required"}), 400

    if candidate_id not in DEMO_CANDIDATES:
        return jsonify({"error": "Unknown candidate"}), 404

    try:
        profile = build_candidate_profile(candidate_id)
    except Exception:
        meta = DEMO_CANDIDATES[candidate_id]
        profile = {"id": candidate_id, "type": "human", "name": meta["name"],
                   "role_hint": meta["role_hint"], "skills": [], "experience": [],
                   "capability_summary": ""}

    try:
        cover_letter_result = generate_cover_letter(profile, job_design)
    except Exception as e:
        return jsonify({"error": f"Cover letter generation failed: {e}"}), 500

    application = _apply(candidate_id, profile, job_design, cover_letter_result)

    # Store jd_report reference in analysis_sessions for job listing
    session_id = data.get("session_id")
    if session_id and session_id in analysis_sessions:
        sess = analysis_sessions[session_id]
        if "jd_report" not in sess:
            sess["jd_report"] = {"job_designs": [job_design]}

    return jsonify({"application": application, "cover_letter": cover_letter_result})


@main.route("/api/tracker", methods=["GET"])
def get_tracker():
    """Get all application records (Tracker Agent)"""
    from app.agents.application_agent import get_applications
    candidate_id = request.args.get("candidate_id")
    apps = get_applications(candidate_id)
    return jsonify({"applications": apps, "total": len(apps)})


# ─── Health check ─────────────────────────────────────────────────────────────

# ─── Career Strategy Agent API ────────────────────────────────────────────────

@main.route("/api/career/start", methods=["POST"])
def career_start():
    """开始一轮新的职业策略对话"""
    data = request.get_json()
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    session_id = secrets.token_hex(8)
    agent = CareerStrategyAgent()
    response = agent.start(message)

    is_complete = agent.is_complete(response)
    strategy = None
    display_response = response
    if is_complete:
        try:
            strategy = agent.extract_strategy(response)
            display_response = response.split("[STRATEGY_READY]")[0].strip()
        except Exception:
            is_complete = False

    career_sessions[session_id] = {"agent": agent, "strategy": strategy}

    return jsonify({
        "session_id": session_id,
        "response": display_response,
        "is_complete": is_complete,
        "strategy": strategy,
    })


@main.route("/api/career/reply", methods=["POST"])
def career_reply():
    """继续职业策略对话"""
    data = request.get_json()
    session_id = data.get("session_id")
    message = data.get("message", "").strip()

    if session_id not in career_sessions:
        return jsonify({"error": "Session not found"}), 404

    sess = career_sessions[session_id]
    agent = sess["agent"]
    response = agent.reply(message)

    is_complete = agent.is_complete(response)
    strategy = None
    display_response = response
    if is_complete:
        try:
            strategy = agent.extract_strategy(response)
            sess["strategy"] = strategy
            display_response = response.split("[STRATEGY_READY]")[0].strip()
        except Exception:
            is_complete = False

    return jsonify({
        "session_id": session_id,
        "response": display_response,
        "is_complete": is_complete,
        "strategy": strategy,
    })


# ─── Tracker Agent: task completion ──────────────────────────────────────────

@main.route("/api/career/generate", methods=["POST"])
def career_generate():
    """Force-generate strategy from conversation history (user-triggered)."""
    data = request.get_json()
    session_id = data.get("session_id")
    if session_id not in career_sessions:
        return jsonify({"error": "Session not found"}), 404
    agent = career_sessions[session_id]["agent"]
    try:
        strategy = agent.force_generate_strategy()
        career_sessions[session_id]["strategy"] = strategy
        return jsonify({"success": True, "strategy": strategy})
    except Exception:
        # Same rule as the analysis routes (D11b): the exception goes to the
        # log, never to the client. `str(e)` here leaked whatever the LLM SDK
        # put in the message — request ids, urls, and on a bad day the API key
        # in a request repr.
        current_app.logger.exception("career strategy generation failed")
        return jsonify({"error": "career strategy generation failed"}), 500


@main.route("/api/tracker/task-complete", methods=["POST"])
def complete_task():
    """Mark a career strategy task as complete; award EXP and update profile."""
    data = request.get_json()
    task_title    = data.get("task_title", "")
    task_direction = data.get("task_direction", "")
    related_skills = data.get("related_skills", [])
    exp_reward    = int(data.get("exp_reward", 50))

    state = user_profile_state
    state["exp"] += exp_reward

    leveled_up = False
    while state["exp"] >= state["exp_to_next"]:
        state["exp"] -= state["exp_to_next"]
        state["level"] += 1
        leveled_up = True

    # Candidate Profile Agent: boost skills
    for skill in related_skills:
        state["skill_boosts"][skill] = state["skill_boosts"].get(skill, 0) + 3

    # Increase completeness slightly per completed task
    state["profile_completeness"] = min(100, state["profile_completeness"] + 3)

    task_entry = {
        "title": task_title,
        "direction": task_direction,
        "skills": related_skills,
        "exp_gained": exp_reward,
        "completed_at": datetime.now().strftime("%H:%M"),
    }
    state["completed_tasks"].append(task_entry)

    return jsonify({
        "success": True,
        "exp_gained": exp_reward,
        "total_exp": state["exp"],
        "exp_to_next": state["exp_to_next"],
        "level": state["level"],
        "leveled_up": leveled_up,
        "timeline_entry": task_entry,
        "skill_boosts": state["skill_boosts"],
        "profile_completeness": state["profile_completeness"],
    })


@main.route("/api/profile/state", methods=["GET"])
def get_profile_state():
    """Get current user profile state (EXP, level, skill boosts)."""
    return jsonify(user_profile_state)


@main.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ─── Phase 2 / U6: JWT auth ───────────────────────────────────────────────────
#
# Minimal real auth. Login returns a 24h HS256 JWT; /api/auth/me round-trips
# it to confirm the server saw a valid token. Register is open in Demo —
# Phase 3+ should gate it (invite code / email verification). See
# app/services/auth.py for the cryptography (pbkdf2 hash, JWT helpers).
#
# All three routes treat the user table as authoritative — JWT carries only
# sub + role, the rest of the user record is fetched from DB on each request.


@main.route("/api/auth/login", methods=["POST"])
def auth_login():
    """Verify password, issue a JWT. 401 for wrong creds / unknown user."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    user_id = (body.get("user_id") or "").strip() if isinstance(body.get("user_id"), str) else ""
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    if not user_id or not password:
        return jsonify({"error": "user_id and password are required"}), 400

    from app.storage.users import get_user
    from app.services.auth import verify_password, create_token

    row = get_user(current_app.config["DATABASE_PATH"], user_id)
    # Run verify_password even when row is None so the timing of unknown-user
    # vs wrong-password responses can't be distinguished by an attacker.
    dummy_hash = "00" * 16 + "$" + "00" * 32
    stored_hash = row["password_hash"] if row else dummy_hash
    if not verify_password(password, stored_hash) or row is None:
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_token(row["id"], row["role"])
    return jsonify({
        "token": token,
        "user": {"id": row["id"], "name": row["name"], "role": row["role"]},
    })


@main.route("/api/auth/register", methods=["POST"])
def auth_register():
    """Create a new user + return a token. 400 on validation / duplicate id."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    user_id = (body.get("user_id") or "").strip() if isinstance(body.get("user_id"), str) else ""
    name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
    role = body.get("role") if isinstance(body.get("role"), str) else ""
    password = body.get("password") if isinstance(body.get("password"), str) else ""
    if not user_id or not name or not role or not password:
        return jsonify({"error": "user_id, name, role, password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    from app.storage.users import create_user, RESERVED_USER_IDS
    from app.services.auth import hash_password, create_token

    # Reject reserved Phase 1 stub ids up-front with a clear message rather
    # than the generic "already exists" the DB unique constraint would raise.
    # Closes the U6 IDOR where registering one of these ids would let the
    # attacker JWT-login as the owner of historical royalty rows.
    if user_id in RESERVED_USER_IDS:
        return jsonify({"error": f"user_id is reserved: {user_id}"}), 400

    try:
        user = create_user(
            current_app.config["DATABASE_PATH"],
            user_id, name, role, hash_password(password),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    token = create_token(user["id"], user["role"])
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "name": user["name"], "role": user["role"]},
    }), 201


@main.route("/api/auth/me", methods=["GET"])
@login_required
def auth_me():
    """Return the authenticated user. 401 without a valid Bearer token.

    login_required has already validated the token + set request.current_user.
    We re-fetch the row from DB so stale tokens that point at a deleted user
    don't return ghost data (we 401 instead).
    """
    from app.storage.users import get_user
    user_id = request.current_user["id"]
    row = get_user(current_app.config["DATABASE_PATH"], user_id)
    if row is None:
        return jsonify({"error": "User no longer exists"}), 401
    return jsonify({
        "user": {"id": row["id"], "name": row["name"], "role": row["role"]},
    })


# ─── Demo identity API ────────────────────────────────────────────────────────

@main.route("/api/demo/identities", methods=["GET"])
def list_demo_identities():
    """Return the 4 hard-coded Demo identities + the current selection."""
    return jsonify({
        "identities": list(DEMO_IDENTITIES.values()),
        "current": get_current_identity(),
    })


@main.route("/api/demo/identity", methods=["POST"])
def set_demo_identity():
    """Set the active Demo identity via a cookie. Body: {"identity_id": "..."}.

    Cookie path is "/" so subsequent requests (HTML routes, /api, /creator/...)
    all pick up the same identity. SameSite=Lax keeps top-level navigation
    working without leaking cross-site.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json(silent=True) or {}
    identity_id = (data.get("identity_id") or "").strip() if isinstance(data.get("identity_id"), str) else ""
    if identity_id not in DEMO_IDENTITIES:
        return jsonify({"error": f"Unknown identity_id: {identity_id}"}), 400

    identity = DEMO_IDENTITIES[identity_id]
    resp = make_response(jsonify({"success": True, "identity": identity}))
    resp.set_cookie(
        "demo_identity", identity_id,
        max_age=60 * 60 * 24 * 30, path="/", samesite="Lax",
    )
    return resp


@main.route("/api/demo/agent", methods=["GET"])
def get_demo_agent():
    """Demo 预设 Agent ("客服话术生成器") 元信息 — Pact modal 启动时拉取。

    返回 asset_id 让 modal 能把 royalty 落到正确的 creator (zhang_ai) 而不是
    fallback 的 JOB_DESIGN_ASSET_ID。

    404 当 DEMO_CS_AGENT_ASSET_ID 没配（TESTING 路径或 bootstrap 关掉时）—
    前端拿到 404 应该回退到现有硬编码 demo 数据，保持降级体验。

    wallet 字段刻意用 ANVIL_TO_ADDRESS（公开的本地测试地址，不是真资产）做占
    位，让 modal 的"收款方钱包"卡显示有意义的地址；线上部署前应改成创作者
    真实关联的钱包。
    """
    asset_id = current_app.config.get("DEMO_DA_AGENT_ASSET_ID")
    if not asset_id:
        return jsonify({"error": "Demo agent not bootstrapped"}), 404

    from app.storage.skill_assets import get_skill_asset
    from app.storage.users import get_user

    asset = get_skill_asset(current_app.config["DATABASE_PATH"], asset_id)
    if asset is None:
        return jsonify({"error": "Demo asset record missing"}), 404

    creator_id = asset["creator_id"]
    creator_row = get_user(current_app.config["DATABASE_PATH"], creator_id)
    creator_name = creator_row["name"] if creator_row else creator_id

    # Anvil 默认账户 1，公开的本地测试地址（见 .env 注释），仅作展示。
    wallet = os.getenv("ANVIL_TO_ADDRESS", "0x70997970C51812dc3A010C7d01b50e0d17dc79C8")

    return jsonify({
        "asset_id": asset_id,
        "name": asset["name"],
        "description": asset["description"],
        "creator_id": creator_id,
        "creator_name": creator_name,
        "price_per_hour": asset["price_amount"] / 100,  # USD 基点 → 美元
        "currency": asset["price_currency"],
        "default_hours": 1,
        "wallet": wallet,
    })


# ─── Demo: publish a JD to the global pool ────────────────────────────────────

_ALLOWED_WORK_TYPES = {"full-time", "part-time", "contract", "freelance"}


def _coerce_string_list(value, field_name: str) -> list[str]:
    """Validate a list-of-strings body field. Empty / None → []. Raises ValueError."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array of strings")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} entries must be strings")
        item = item.strip()
        if item:
            out.append(item)
    return out


@main.route("/api/jobs/publish", methods=["POST"])
def publish_job():
    """Append a JD to the global published_jobs pool.

    Body fields:
      - jd (str):   markdown / plain text JD draft. Stored as job_description.
      - job_id (str, optional): defaults to a generated demo_job_<hex> id.
      - company (str, optional): defaults to the current Demo identity's name.
      - job_title (str, optional): defaults to "Demo 岗位".
      - required_skills (list[str], optional): structured skills required for
        the role. Used by the cover-letter generator in /api/apply.
      - core_responsibilities (list[str], optional): structured duties. Used
        by the cover-letter generator and rendered by JobDetail.
      - work_type (str, optional): full-time / part-time / contract / freelance.
        Defaults to "full-time".
      - salary_range (dict, optional): {min, max, unit} mirroring the JD
        schema. Rendered by the candidate-side pages.

    Duplicate job_ids are rejected with 409 so a double-click doesn't create
    two listings.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    jd = (data.get("jd") or "").strip() if isinstance(data.get("jd"), str) else ""
    if not jd:
        return jsonify({"error": "jd is required"}), 400

    identity = get_current_identity()
    job_id = (data.get("job_id") or "").strip() if isinstance(data.get("job_id"), str) else ""
    if not job_id:
        job_id = "demo_job_" + secrets.token_hex(4)
    if any(j.get("job_id") == job_id for j in published_jobs):
        return jsonify({"error": f"job_id already published: {job_id}"}), 409

    company = (data.get("company") or "").strip() if isinstance(data.get("company"), str) else ""
    if not company:
        company = identity["name"]
    job_title = (data.get("job_title") or "").strip() if isinstance(data.get("job_title"), str) else ""
    if not job_title:
        job_title = "Demo 岗位"

    # Structured fields — feed the candidate-side apply flow. Without them,
    # generate_cover_letter falls through to empty lists (LLM gets no signal)
    # and JobDetail can't render the requirements / skills sections.
    try:
        required_skills = _coerce_string_list(data.get("required_skills"), "required_skills")
        core_responsibilities = _coerce_string_list(
            data.get("core_responsibilities"), "core_responsibilities"
        )
        nice_to_have_skills = _coerce_string_list(
            data.get("nice_to_have_skills"), "nice_to_have_skills"
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    work_type = data.get("work_type")
    if work_type is None:
        work_type = "full-time"
    elif not isinstance(work_type, str) or work_type not in _ALLOWED_WORK_TYPES:
        return jsonify({
            "error": f"work_type must be one of {sorted(_ALLOWED_WORK_TYPES)}",
        }), 400

    salary_range = data.get("salary_range")
    if salary_range is not None and not isinstance(salary_range, dict):
        return jsonify({"error": "salary_range must be an object"}), 400

    job = {
        "job_id": job_id,
        "job_title": job_title,
        "company": company,
        "job_description": jd,
        "publisher_id": identity["id"],
        "published_at": datetime.now(timezone.utc).isoformat(),
        "core_responsibilities": core_responsibilities,
        "required_skills": required_skills,
        "nice_to_have_skills": nice_to_have_skills,
        "work_type": work_type,
    }
    if salary_range is not None:
        job["salary_range"] = salary_range
    published_jobs.append(job)
    return jsonify({"success": True, "job_id": job_id, "job": job})


# ─── Demo: AI 分析求职者优势 ──────────────────────────────────────────────────

@main.route("/api/candidate/analyze", methods=["POST"])
def analyze_candidate():
    """Use GLM-4 to summarize 3-5 strengths from a candidate profile.

    Body: {"profile": {...}}. The profile is forwarded as JSON to the LLM with
    a short instruction. Returns {"strengths": [...], "raw": "<full text>"}.
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json(silent=True) or {}
    profile = data.get("profile")
    if not isinstance(profile, dict) or not profile:
        return jsonify({"error": "profile (object) is required"}), 400

    from app.agents.agents import get_llm_client, get_model
    client = get_llm_client()
    profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
    prompt = (
        "你是 HireNet 的求职顾问。下面是一位求职者的资料 JSON，"
        "请基于这份资料，用中文输出 3-5 条最有说服力的求职优势。\n"
        "要求：\n"
        "1. 每条以 '- ' 开头，控制在 30 字以内。\n"
        "2. 必须基于资料里的事实（技能 / 经历 / 偏好），不要编造。\n"
        "3. 只输出 bullet 列表，不要前言或总结。\n\n"
        f"资料：\n{profile_json}"
    )
    try:
        resp = client.chat.completions.create(
            model=get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return jsonify({"error": f"LLM call failed: {e}"}), 502

    strengths = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ", "• ")):
            strengths.append(line[2:].strip())
        elif line and line[0].isdigit() and line[1:3] in (". ", "、", ") "):
            strengths.append(line[2:].lstrip(") ").strip())
    if not strengths and text:
        strengths = [text]

    return jsonify({"strengths": strengths[:5], "raw": text})


# ─── MCP (Model Context Protocol) Endpoint ────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "hirenet_analyze_requirements",
        "description": "帮助企业澄清项目需求，输出结构化任务分解",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"}
            },
            "required": ["description"]
        }
    },
    {
        "name": "hirenet_match_candidates",
        "description": "根据岗位需求，从人才与 Agent 网络中匹配最合适的候选人或 Agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_title": {"type": "string"},
                "requirements": {"type": "string"}
            },
            "required": ["job_title"]
        }
    },
    {
        "name": "hirenet_career_strategy",
        "description": "职业策略顾问：分析求职者背景，给出个性化职业发展建议",
        "inputSchema": {
            "type": "object",
            "properties": {
                "background": {"type": "string"}
            },
            "required": ["background"]
        }
    },
    {
        "name": "hirenet_get_jobs",
        "description": "获取当前 HireNet 平台上可用的岗位列表",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
]


@main.route("/api/mcp", methods=["POST"])
def mcp_endpoint():
    """JSON-RPC 2.0 MCP endpoint."""
    body = request.get_json(silent=True) or {}
    rpc_id = body.get("id", 1)
    method = body.get("method", "")
    params = body.get("params", {})

    # Extract Bearer token if provided
    auth_header = request.headers.get("Authorization", "")
    bearer_token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else None

    def ok(result):
        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    def err(code, message):
        return jsonify({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}), 400

    if method == "tools/list":
        return ok({"tools": MCP_TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            if tool_name == "hirenet_get_jobs":
                from app.agents.application_agent import get_demo_jobs
                jobs = get_demo_jobs()
                text = json.dumps(jobs, ensure_ascii=False, indent=2)

            elif tool_name == "hirenet_analyze_requirements":
                description = arguments.get("description", "")
                if not description:
                    return err(-32602, "description is required")
                agent = RequirementAnalysisAgent()
                response = agent.start(description)
                text = response

            elif tool_name == "hirenet_match_candidates":
                from app.agents.candidate_profile import get_all_resources
                from app.agents.agents import evaluate_resource_for_task
                job_title = arguments.get("job_title", "")
                requirements = arguments.get("requirements", "")
                resources = get_all_resources()
                human_resources = [r for r in resources if r["type"] == "human"]
                task = {
                    "id": "mcp_match",
                    "name": job_title,
                    "description": requirements,
                    "type": "general",
                    "requires_judgment": True,
                    "is_recurring": True,
                    "estimated_hours": 160,
                }
                matches = []
                for resource in human_resources:
                    try:
                        eval_result = evaluate_resource_for_task(resource, task)
                    except Exception:
                        eval_result = {"confidence": 0.5, "reason": "评估超时", "strengths": []}
                    matches.append({
                        "candidate": resource,
                        "match_score": round(eval_result.get("confidence", 0) * 100),
                        "reason": eval_result.get("reason", ""),
                    })
                matches.sort(key=lambda x: x["match_score"], reverse=True)
                text = json.dumps(matches, ensure_ascii=False, indent=2)

            elif tool_name == "hirenet_career_strategy":
                background = arguments.get("background", "")
                if not background:
                    return err(-32602, "background is required")
                agent = CareerStrategyAgent()
                agent.start(background)
                strategy = agent.force_generate_strategy()
                text = json.dumps(strategy, ensure_ascii=False, indent=2)

            else:
                return err(-32601, f"Unknown tool: {tool_name}")

            return ok({"content": [{"type": "text", "text": text}]})

        except Exception as e:
            current_app.logger.exception("mcp tool execution failed: %s", tool_name)
            return err(-32603, f"Tool execution error: {e}")

    return err(-32601, f"Method not found: {method}")


# ─── Serve frontend ───────────────────────────────────────────────────────────

@main.route("/api/analyze/quick", methods=["POST"])
def quick_analyze():
    """
    Quick demo mode: takes a pre-built requirement dict directly,
    skips multi-turn conversation, runs the full decide pipeline.
    """
    data = request.get_json()
    requirement = data.get("requirement")
    original_description = data.get("original_description", "")

    if not requirement:
        return jsonify({"error": "requirement is required"}), 400

    session_id = secrets.token_hex(8)
    use_v2 = _task_agent_version() == "v2"
    if use_v2:
        sess = _new_v2_session(session_id, original_description, requirement=requirement)
        # /quick skips the conversation entirely: the client already knows the
        # requirement, so it is seeded straight into the agent state and the
        # clarification loop never runs. `history` stays empty — there was no
        # conversation to replay.
        sess["history"] = []
        sess["agent_state"] = {
            "initial_input": original_description,
            "requirement": requirement,
        }
        analysis_sessions[session_id] = sess
    else:
        analysis_sessions[session_id] = {
            "agent": None,
            "initial_input": original_description,
            "history": [],
            "requirement": requirement,
        }

    try:
        if use_v2:
            tasks, decisions, agent = _v2_pipeline(session_id, analysis_sessions[session_id])
            recorder = _job_design_recorder(usage=agent.usage_summary())
        else:
            task_data = decompose_tasks(requirement)
            tasks = task_data.get("tasks", [])
            decisions = run_resource_decision(tasks)
            recorder = _job_design_recorder()
        jd_report = generate_jd_report(
            decisions, requirement, original_description=original_description,
            on_design=recorder,
        )
        # store jd_report in session for job listing
        analysis_sessions[session_id]["jd_report"] = jd_report
        summary = _build_decision_summary(tasks, decisions, jd_report)
        # Same rule as /decide: no automatic publication. See the comment there.
        return jsonify({
            "session_id": session_id,
            "requirement": requirement,
            "tasks": tasks,
            "decisions": decisions,
            "jd_report": jd_report,
            "summary": summary,
        })
    except Exception:
        # Same reasoning as run_decision: log it, return a generic body.
        current_app.logger.exception("quick_analyze failed")
        return jsonify({"error": "analysis failed"}), 500


# ─── Phase 2 / U1: royalty inspection + settlement ────────────────────────────

@main.route("/api/royalty/split", methods=["GET"])
def royalty_split():
    """Return the 3-way royalty_splits JSON and the charged total for one run.

    Source of truth is agent_runs.royalty_splits (already JSON-decoded by
    get_agent_run). Missing run_id → 400; unknown run_id → 404.

    TODO Phase 2 / U2 (auth): no caller identity check yet. Anyone who can hit
    this endpoint can read any run's split. Same gap as the rest of the Phase 1
    /Phase 2 U1 surface — real auth lands when per-user identity arrives.
    Until then this endpoint MUST NOT be exposed outside the dev network.
    """
    run_id = request.args.get("run_id", "").strip()
    if not run_id:
        return jsonify({"error": "run_id query parameter is required"}), 400

    from app.storage.agent_runs import get_agent_run
    run = get_agent_run(current_app.config["DATABASE_PATH"], run_id)
    if run is None:
        return jsonify({"error": f"Unknown run_id: {run_id}"}), 404

    return jsonify({
        "run_id": run["run_id"],
        "royalty_splits": run["royalty_splits"],
        "charge_amount": run["charge_amount"],
        "charge_currency": run["charge_currency"],
        "charge_chain": run["charge_chain"],
        "settlement_status": run["settlement_status"],
    })


@main.route("/api/royalty/list", methods=["GET"])
def royalty_list():
    """List royalty ledger rows for a session.

    Phase 2 / U1 has no session→runs mapping yet (analysis_sessions does not
    track agent_runs), so this endpoint returns an empty array when there is
    no mapping. Shape stays stable so frontend code can be wired now.

    TODO Phase 2 / U2 (auth): no caller identity check. Once sessions are
    tracked + per-user auth lands, gate on session ownership before returning
    entries.
    """
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return jsonify({"error": "session_id query parameter is required"}), 400

    # TODO Phase 2 / U2: track agent_runs per analysis_session and join them
    # here. For now sessions don't own runs, so the list is empty.
    return jsonify({"session_id": session_id, "entries": []})


@main.route("/api/royalty/settle", methods=["POST"])
def royalty_settle():
    """Walk a run through accrued → settling → settled (or failed). Idempotent.

    Phase 3 / U1 expanded this from a single ledger flip to a state machine
    backed by a swappable SettlementProvider. The Mock provider succeeds
    synchronously, so a normal request still ends in 'settled' with a
    settled_count of 3 (creator/platform/tax rows) — the existing Phase 2/U1
    tests stay green. The new bits, surfaced in the response body:

      - settlement_status: one of accrued/settling/settled/failed.
      - tx_hash: provider's tx identifier (e.g. "mock-<hex>" for Mock).

    State transitions handled here:
      - accrued  → claim → provider.settle() → confirm → settled (success)
      - accrued  → claim → provider.settle() → fail    → failed  (502)
      - failed   → claim → provider.settle() → …               (retriable)
      - settling → 409 Conflict (another request owns the claim)
      - settled  → 200 no-op, preserve existing tx_hash

    Body: {"run_id": "<uuid>"}.

    TODO Phase 2 / U2 (auth — HIGH): no caller identity check yet. MUST be
    gated behind real per-user auth + caller-owns-run check before exposing
    beyond the dev network. Flagged by security review 2026-06-10.
    """
    # Reject non-JSON requests up front. request.get_json(silent=True) would
    # otherwise quietly return {} for e.g. a form-encoded body, bypassing the
    # 'run_id required' check.
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    run_id = (payload.get("run_id") or "").strip() if isinstance(payload.get("run_id"), str) else ""
    if not run_id:
        return jsonify({"error": "run_id is required in JSON body"}), 400

    from app.storage.agent_runs import (
        get_agent_run,
        claim_settlement,
        confirm_settlement,
        fail_settlement,
        record_settlement_submission,
    )
    from app.services.settlement import SettlementStatus

    db_path = current_app.config["DATABASE_PATH"]
    run = get_agent_run(db_path, run_id)
    if run is None:
        return jsonify({"error": f"Unknown run_id: {run_id}"}), 404

    current_status = run["settlement_status"]

    # settled is terminal: short-circuit so a double-click can't re-submit the
    # same payment. settled_count=0 matches the historical "idempotent" shape.
    if current_status == "settled":
        return jsonify({
            "run_id": run_id,
            "settled_count": 0,
            "status": "settled",
            "settlement_status": "settled",
            "tx_hash": run.get("tx_hash"),
            "settlement_method": run.get("settlement_method"),
        })

    # settling means another request is actively talking to the provider.
    # Bouncing here keeps us strictly single-submission per run.
    if current_status == "settling":
        return jsonify({
            "error": "Settlement already in progress for this run",
            "run_id": run_id,
            "settlement_status": "settling",
        }), 409

    provider = current_app.config["SETTLEMENT_PROVIDER"]
    provider_name = getattr(provider, "name", provider.__class__.__name__)

    # Stage 2 / WP-R (review F1). The mirror of the guard in royalty_status
    # below, and the AUTHORITATIVE one for this route: it runs BEFORE the
    # claim, so a refused request changes nothing at all.
    #
    # Invariant it protects: a run paid on the x402 rail may only be advanced
    # by the x402 provider. An x402 run whose chain tx reverted is walked back
    # to 'failed' with all three ledger rows 'accrued' (fail_settlement), and
    # 'failed' is a claimable source state. Without this guard a POST under the
    # default mock provider would claim it, get a synthetic success out of
    # MockSettlementProvider.settle(), and confirm_settlement's accrued branch
    # would mark ALL THREE rows 'settled' — including the two
    # 'x402-fee-receivable' rows that are owed BY the creator and that no
    # transfer ever paid — while overwriting settlement_method x402 → mock and
    # the tx_hash of the reverted payment. Money the platform never received
    # would read as collected.
    #
    # 409 (not the 200-with-state body royalty_status answers with): this is a
    # POST asking us to move money, and the caller must be able to tell "did
    # nothing" from the 200 a completed settle returns. The informational keys
    # of the status body are carried along so the refusal is still readable.
    if run.get("settlement_method") == "x402" and provider_name != "x402":
        current_app.logger.warning(
            "refusing to settle run %s: it was paid via x402 but the configured "
            "settlement provider is %r, which cannot know anything about that "
            "payment. Set HIRENET_SETTLEMENT_PROVIDER=x402 to confirm it on-chain.",
            run_id, provider_name,
        )
        return jsonify({
            "error": (
                "run was pre-settled via x402; only the x402 settlement "
                f"provider may advance it (configured provider: {provider_name})"
            ),
            "run_id": run_id,
            "settlement_status": current_status,
            "settlement_method": run.get("settlement_method"),
            "tx_hash": run.get("tx_hash"),
        }), 409

    # Claim the run (accrued/failed → settling). If someone raced us between
    # the SELECT above and the UPDATE here, claim returns False and we 409 —
    # the racing thread now owns the in-flight settle.
    if not claim_settlement(db_path, run_id):
        return jsonify({
            "error": "Could not claim settlement (race lost)",
            "run_id": run_id,
        }), 409

    # Provider is intentionally given the creator-side view of the payment —
    # multi-payee splits are a ledger-layer fact (creator + platform + tax),
    # not a provider concern. U2 will need to revisit this if a rail wants
    # native multi-recipient txs.
    creator_split = run["royalty_splits"].get("creator", {})
    payee_id = creator_split.get("creator_id") or run["caller_id"]

    settle_kwargs = dict(
        payee_id=payee_id,
        amount=run["charge_amount"],
        currency=run["charge_currency"],
        chain=run.get("charge_chain"),
    )

    # Sepolia-only: look up the billed Agent's on-chain wallet so the ETH
    # transfer lands on a real recipient instead of self.from_address (the
    # pre-wallet-integration self-transfer demo). We sniff provider.name to
    # avoid wiring a new kwarg through the mock/anvil providers — they don't
    # move real funds, so a recipient address is irrelevant to them and adding
    # a no-op kwarg would just churn their signatures.
    if provider_name == "sepolia":
        asset_ids = run.get("asset_ids") or []
        if asset_ids:
            from app.storage.skill_assets import get_skill_asset
            asset = get_skill_asset(db_path, asset_ids[0])
            if asset is not None:
                settle_kwargs["to_address"] = asset.get("wallet_address")
        # If asset_ids is empty OR wallet_address is None, settle_kwargs
        # has no to_address key → Sepolia falls back to SEPOLIA_TO_ADDRESS
        # (env default) → self.from_address. Either of the last two paths
        # preserves the old self-transfer behavior so the demo doesn't
        # 502 on a legacy row that pre-dates this column.

    try:
        result = provider.settle(**settle_kwargs)
    except Exception as exc:
        current_app.logger.exception("settlement provider raised")
        fail_settlement(db_path, run_id, str(exc))
        return jsonify({
            "error": f"Settlement provider raised: {exc}",
            "run_id": run_id,
            "settlement_status": "failed",
        }), 502

    if not result.success:
        current_app.logger.warning(
            "settlement failed for run_id=%s: %s", run_id, result.error
        )
        fail_settlement(db_path, run_id, result.error)
        return jsonify({
            "error": result.error or "Settlement failed",
            "run_id": run_id,
            "settlement_status": "failed",
        }), 502

    # Branch on the provider's reported next state. Synchronous providers
    # (Mock) report SETTLED → flip agent_runs + ledger rows now. An
    # asynchronous on-chain provider reports SETTLING → persist tx_hash but
    # leave the row at 'settling' so a later check_status() can advance it to
    # SETTLED only after the chain actually confirms. Without this branch a
    # transfer the provider merely *accepted* would be misreported as paid.
    if result.next_status == SettlementStatus.SETTLED:
        # Sync confirm: agent_runs + ledger rows flip in a single transaction
        # so the creator/platform/tax invariant cannot be partially applied.
        settled_count = confirm_settlement(
            db_path, run_id, tx_hash=result.tx_hash or "", method=provider_name,
        )
        return jsonify({
            "run_id": run_id,
            "settled_count": settled_count,
            "status": "settled",  # legacy shape — kept so old tests still pass
            "settlement_status": "settled",
            "tx_hash": result.tx_hash,
            "settlement_method": provider_name,
        })

    if result.next_status == SettlementStatus.SETTLING:
        # Async submit: record the tx_hash + method so GET /royalty/status
        # can later call provider.check_status(tx_hash). Ledger rows stay
        # 'accrued' until the chain confirms.
        record_settlement_submission(
            db_path, run_id, tx_hash=result.tx_hash or "", method=provider_name,
        )

        # Anvil instant-mines on every tx, so the receipt is essentially
        # available the moment send_raw_transaction returns. Block briefly
        # here so the demo flow returns 'settled' rather than parking the
        # run in 'settling' and forcing the UI to poll /royalty/status.
        # A genuinely async provider (chain confirmation in minutes) is
        # left alone, exactly as before.
        if provider_name == "anvil":
            for _ in range(10):
                try:
                    chain_status = provider.check_status(result.tx_hash or "")
                except Exception:
                    current_app.logger.exception(
                        "anvil check_status raised post-settle for run_id=%s", run_id
                    )
                    chain_status = SettlementStatus.SETTLING
                if chain_status == SettlementStatus.SETTLED:
                    settled_count = confirm_settlement(
                        db_path, run_id, tx_hash=result.tx_hash or "", method=provider_name,
                    )
                    return jsonify({
                        "run_id": run_id,
                        "settled_count": settled_count,
                        "status": "settled",
                        "settlement_status": "settled",
                        "tx_hash": result.tx_hash,
                        "settlement_method": provider_name,
                    })
                if chain_status == SettlementStatus.FAILED:
                    fail_settlement(db_path, run_id, "chain reported failure")
                    return jsonify({
                        "error": "chain reported failure",
                        "run_id": run_id,
                        "settlement_status": "failed",
                        "tx_hash": result.tx_hash,
                    }), 502
                time.sleep(0.05)
            # Fell through ~0.5s without a terminal receipt — leave the row
            # at 'settling' and let the UI poll /royalty/status to advance it.

        return jsonify({
            "run_id": run_id,
            "settled_count": 0,
            "status": "settling",
            "settlement_status": "settling",
            "tx_hash": result.tx_hash,
            "settlement_method": provider_name,
        })

    # Defensive: a provider returning anything else (FAILED, ACCRUED) on a
    # success=True result is a bug in that provider. Treat as failed so the
    # operator gets a loud signal instead of a stuck 'settling' row.
    current_app.logger.error(
        "settlement provider %s returned unexpected next_status=%s",
        provider_name, result.next_status,
    )
    fail_settlement(db_path, run_id, f"unexpected next_status: {result.next_status}")
    return jsonify({
        "error": f"Provider returned unexpected next_status: {result.next_status.value}",
        "run_id": run_id,
        "settlement_status": "failed",
    }), 502


@main.route("/api/royalty/status/<run_id>", methods=["GET"])
def royalty_status(run_id):
    """Return current settlement state for a run.

    Phase 3 / U2 added opportunistic polling: when the row is in 'settling'
    and carries a tx_hash, we call provider.check_status(tx_hash) and
    advance the state machine if the chain has reached a terminal state.
    This is the only path that flips settling → settled for async
    providers; without it, a transfer submitted to an asynchronous on-chain
    provider would stay 'settling' forever even after on-chain
    confirmation. Mock provider rows are never
    in 'settling' (settle() returns SETTLED synchronously) so this branch
    is a no-op for them.

    Path param run_id; unknown run_id → 404.
    """
    from app.storage.agent_runs import (
        get_agent_run,
        confirm_settlement,
        fail_settlement,
    )
    from app.services.settlement import SettlementStatus

    db_path = current_app.config["DATABASE_PATH"]
    run = get_agent_run(db_path, run_id)
    if run is None:
        return jsonify({"error": f"Unknown run_id: {run_id}"}), 404

    # Opportunistic advance: only poll the provider when we have something
    # to poll WITH (tx_hash present) and a state worth advancing FROM
    # (settling). check_status is wrapped in a broad try/except so a flaky
    # rail can never 500 a status read — the caller can always retry the
    # GET, and the row stays at its last-known state.
    if run["settlement_status"] == "settling" and run.get("tx_hash"):
        provider = current_app.config["SETTLEMENT_PROVIDER"]
        provider_name = getattr(provider, "name", provider.__class__.__name__)
        # Stage 2 / WP-D guard. An x402 run is born 'settling' at record time
        # (the caller already paid), so unlike every other rail its rows reach
        # this branch without the platform ever having called settle(). If the
        # configured provider is NOT x402 it has no idea what that tx hash
        # means — MockSettlementProvider.check_status returns SETTLED for any
        # string — and advancing on its word would mark a creator paid on the
        # strength of a mock. Leave the row alone and say why.
        if run.get("settlement_method") == "x402" and provider_name != "x402":
            current_app.logger.warning(
                "run %s was pre-settled via x402 but the configured settlement "
                "provider is %r; not advancing. Set HIRENET_SETTLEMENT_PROVIDER=x402 "
                "to confirm this run on-chain.",
                run_id, provider_name,
            )
            return _royalty_status_response(run)
        try:
            chain_status = provider.check_status(run["tx_hash"])
        except Exception:
            current_app.logger.exception(
                "check_status raised for run_id=%s", run_id
            )
            chain_status = SettlementStatus.SETTLING

        if chain_status == SettlementStatus.SETTLED:
            confirm_settlement(
                db_path, run_id, tx_hash=run["tx_hash"], method=provider_name,
            )
            run = get_agent_run(db_path, run_id)
        elif chain_status == SettlementStatus.FAILED:
            fail_settlement(db_path, run_id, "chain reported failure")
            run = get_agent_run(db_path, run_id)
        # else SETTLING → no change; row remains as-is.

    return _royalty_status_response(run)


def _royalty_status_response(run: dict):
    """The GET /api/royalty/status/<run_id> body.

    Extracted in Stage 2 / WP-D so the new "pre-settled run, wrong provider"
    early return above renders the identical body. Keys are unchanged; the
    only addition is `explorer_url`, present ONLY for x402 runs that have a
    tx hash, so no existing consumer sees a new key.
    """
    body = {
        "run_id": run["run_id"],
        "settlement_status": run["settlement_status"],
        "settlement_method": run.get("settlement_method"),
        "tx_hash": run.get("tx_hash"),
        "charge_amount": run["charge_amount"],
        "charge_currency": run["charge_currency"],
        "charge_chain": run.get("charge_chain"),
    }
    if run.get("settlement_method") == "x402" and run.get("tx_hash"):
        # Module-level helper, not provider.explorer_url: the link is a
        # property of the tx hash and the configured explorer, and must render
        # even when the app is running some other provider (see the guard
        # above, which is exactly that situation).
        from app.services.x402_settlement import explorer_url

        body["explorer_url"] = explorer_url(run["tx_hash"])
    return jsonify(body)


# ─── Task D: authorization mandate (pact) lifecycle (demo) ───────────────────
#
# Wallet-agnostic authorization flow:  create → pending → approved → settled
#                                                  └──→ rejected
#
# The enterprise authorizes a spend up front; the platform only settles against
# an approved mandate. Demo-only in the sense that `approve` is an
# unauthenticated UI click and there is no wallet-side signature; the store
# itself is real (Stage 2 / WP-G: table `pacts`, DAO app/storage/pacts.py).
#
# Settlement triggers the existing U4 path (record_agent_run) so the same
# royalty_ledger row a Job Design invocation would write also lands here.
#
# ── AP2 mandate vocabulary (naming only — NOT the AP2 machinery) ─────────────
#
# The pact object carries five fields whose *names and meanings* deliberately
# mirror Google's Agent Payments Protocol (AP2) mandate vocabulary, so an
# auditor reading a HireNet pact recognises the same concepts:
#
#   intent       ← IntentMandate.natural_language_description
#                  Human-readable statement of what is being authorized.
#   amount_cap   ← IntentMandate spend-ceiling semantics
#                  The ceiling this pact may settle for. Same unit as the
#                  existing `amount` field (dollar units — settle converts it
#                  to integer basis points via Decimal).
#   expires_at   ← IntentMandate.intent_expiry / CartContents.cart_expiry
#                  Wall-clock TTL; approve/settle past it are refused (409).
#   payee        ← CartContents.merchant_name / PaymentMandateContents.merchant_agent
#                  The creator wallet_address resolved from asset_id; None
#                  when the bound SkillAsset has not registered a wallet.
#   content_hash ← CartMandate's cart_hash (integrity link)
#                  sha256 of the canonical JSON of the pact's material fields,
#                  computed at create and re-checked at settle.
#
# What this is NOT — do not let the vocabulary oversell the implementation:
#   - There is NO cryptographic signature anywhere in this flow. `approve` is
#     an unauthenticated-in-demo UI action; that is exactly why the audit
#     fields are named `approved_by` / `approval_method="ui"` and NOT AP2's
#     `user_authorization` / `merchant_authorization`, which AP2 reserves for
#     base64url JWT / verifiable-presentation values.
#   - `content_hash` is a plain unsigned digest. It detects accidental
#     tampering and bugs (the settled pact is the pact that was authorized);
#     it provides NO non-repudiation between mutually-distrusting parties,
#     unlike AP2's cart_hash bound inside a merchant-signed JWT.
#   - Statuses stay pending/approved/rejected/settled. AP2's open/closed
#     mandate distinction is about pre-authorization scope, not workflow
#     state, and forcing it here would misdescribe what happens.

# Default mandate TTL when the client does not supply `expires_at`.
PACT_DEFAULT_TTL_HOURS = 24

# Fields hashed into `content_hash`. Kept as an explicit tuple so a future
# field addition is a deliberate act (adding one silently would invalidate
# every in-flight pact's hash at settle time).
PACT_HASHED_FIELDS = (
    "pact_id",
    "task_id",
    "asset_id",
    "amount_cap",
    "currency",
    "payee",
    "expires_at",
)


def _pact_content_hash(pact: dict) -> str:
    """sha256 hex of the canonical JSON of the pact's material fields.

    Canonical = ``sort_keys=True, separators=(",", ":")`` so the digest is
    byte-stable for identical inputs regardless of dict insertion order.
    Unsigned: an integrity check, not a signature (see section comment).
    """
    material = {field: pact.get(field) for field in PACT_HASHED_FIELDS}
    canonical = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_iso_utc(value):
    """Parse an ISO 8601 string to an aware UTC datetime, or None if unusable.

    Naive timestamps are read as UTC — every timestamp this module writes is
    produced by ``datetime.now(timezone.utc).isoformat()``, so a naive value
    can only come from a client and UTC is the documented contract.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pact_is_expired(pact: dict, now: datetime | None = None) -> bool:
    """True when the pact's `expires_at` is in the past.

    A missing or unparseable `expires_at` is treated as "no TTL" rather than
    "expired" — refusing to settle a pact because of a malformed timestamp
    would be a worse failure mode than the check simply not applying.
    """
    expires = _parse_iso_utc(pact.get("expires_at"))
    if expires is None:
        return False
    return (now or datetime.now(timezone.utc)) >= expires


def _pact_or_404(pact_id: str):
    """Look up a pact or return a JSON 404 tuple.

    Reads the row every time rather than caching: another worker (or another
    thread) may have moved this pact since the last request, and a stale copy
    is exactly what the conditional transitions below exist to rule out.
    """
    pact = get_pact(current_app.config["DATABASE_PATH"], pact_id)
    if pact is None:
        return None, (jsonify({"error": f"Pact not found: {pact_id}"}), 404)
    return pact, None


def _pact_status_conflict(pact_id: str, verb: str):
    """The 400 a refused status transition returns.

    Re-reads the row so the reported status is the one that actually blocked
    the transition — with a conditional UPDATE the losing caller never saw it,
    and reporting the status it read *before* the UPDATE would name a state
    the pact has already left.
    """
    pact = get_pact(current_app.config["DATABASE_PATH"], pact_id)
    current = pact["status"] if pact else "gone"
    return jsonify({
        "error": f"Pact must be {verb}, current: {current}"
    }), 400


@main.route("/api/pact/create", methods=["POST"])
def pact_create():
    """Create a new pact in pending state.

    Validates required fields and amount up-front so a malformed pact can
    never reach `pact_settle`, where `record_agent_run` would explode with a
    500. Optional `asset_id` binds the pact to a registered SkillAsset; when
    omitted, pact_create fills it with the bootstrapped Job Design asset so
    the pact carries a concrete asset_id from creation (required for the
    Anvil settlement path to resolve price_chain — without this default,
    settle landed a row with charge_chain=None and the Anvil branch was
    skipped, leaving tx_hash None). When supplied, the asset must already
    exist in the skill_assets table — otherwise the pact would settle to
    an unknown asset and silently mis-attribute royalties.
    """
    # Reject non-JSON requests up front. request.get_json(silent=True) would
    # otherwise quietly return {} for e.g. a form-encoded body, bypassing the
    # 'task_id / agent_name / amount required' checks.
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    # Required identifiers — strip + truthiness check rejects None, "", "   "
    task_id = (data.get("task_id") or "").strip() if isinstance(data.get("task_id"), str) else ""
    agent_name = (data.get("agent_name") or "").strip() if isinstance(data.get("agent_name"), str) else ""
    if not task_id or not agent_name:
        return jsonify({"error": "task_id and agent_name are required"}), 400

    # Amount must be a positive number. Float() accepts ints, floats, and
    # numeric strings; bools are rejected so True/False can't pass as 1/0.
    raw_amount = data.get("amount")
    if isinstance(raw_amount, bool) or raw_amount is None:
        return jsonify({"error": "amount must be a valid number"}), 400
    try:
        amount_value = float(raw_amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a valid number"}), 400
    if not math.isfinite(amount_value):
        return jsonify({"error": "amount must be a finite number"}), 400
    if amount_value <= 0:
        return jsonify({"error": "amount must be positive"}), 400
    # Sub-cent amounts (e.g. 0.001) survive the `> 0` guard but settle's
    # `int(round(Decimal * 100))` collapses them to 0 cents → silent zero-bill.
    # Mirror settle's Decimal conversion here so the check matches reality.
    if decimal.Decimal(str(amount_value)) * 100 < 1:
        return jsonify({"error": "amount too small, minimum 0.01"}), 400

    # currency: `data.get("currency", "USD")` returns None when the key is
    # present with a null value; the `or` collapses that and empty strings
    # back to "USD" so settle never sees a falsy currency.
    currency = (data.get("currency") or "USD")
    if isinstance(currency, str):
        currency = currency.strip() or "USD"
    else:
        return jsonify({"error": "currency must be a string"}), 400

    # Optional asset_id: when provided, must resolve to a real SkillAsset so
    # the pact's royalties land on its registered creator instead of the
    # Phase 1 stub. When omitted, default to the bootstrapped Job Design
    # asset here (not at settle time) so the pact carries a concrete
    # asset_id from creation — Anvil's settlement path reads price_chain
    # off the bound asset, and a null asset_id left the row charge_chain
    # blank, which short-circuited the Anvil branch and left tx_hash None.
    from app.storage.skill_assets import get_skill_asset
    asset_id = data.get("asset_id")
    if asset_id is not None:
        if not isinstance(asset_id, str) or not asset_id.strip():
            return jsonify({"error": "asset_id must be a non-empty string"}), 400
        asset_id = asset_id.strip()
        asset = get_skill_asset(current_app.config["DATABASE_PATH"], asset_id)
        if asset is None:
            return jsonify({"error": f"Unknown asset_id: {asset_id}"}), 400
    else:
        asset_id = current_app.config.get("JOB_DESIGN_ASSET_ID")
        asset = (
            get_skill_asset(current_app.config["DATABASE_PATH"], asset_id)
            if asset_id else None
        )

    # ── AP2-shaped mandate fields (see the section comment above) ────────────
    # All five are additive and all five have a default, so a client that
    # knows nothing about them still gets a complete mandate.

    # intent: the client's own natural-language description wins; otherwise
    # synthesise one from the identifiers we already validated.
    raw_intent = data.get("intent")
    if raw_intent is None:
        intent = f"Run {agent_name} for task {task_id}"
    elif isinstance(raw_intent, str):
        intent = raw_intent.strip() or f"Run {agent_name} for task {task_id}"
    else:
        return jsonify({"error": "intent must be a string"}), 400

    # amount_cap: same unit as `amount` (dollar units), defaults to `amount`.
    # Deliberately NOT required to be >= amount at create time — settle is
    # where the ceiling is enforced (409), which keeps "authorize less than
    # you were quoted" a settle-time refusal rather than a create-time one.
    raw_cap = data.get("amount_cap")
    if raw_cap is None:
        amount_cap = amount_value
    else:
        if isinstance(raw_cap, bool):
            return jsonify({"error": "amount_cap must be a valid number"}), 400
        try:
            amount_cap = float(raw_cap)
        except (TypeError, ValueError):
            return jsonify({"error": "amount_cap must be a valid number"}), 400
        if not math.isfinite(amount_cap):
            return jsonify({"error": "amount_cap must be a finite number"}), 400
        if amount_cap <= 0:
            return jsonify({"error": "amount_cap must be positive"}), 400

    # expires_at: ISO 8601 UTC, defaults to now + PACT_DEFAULT_TTL_HOURS.
    raw_expires = data.get("expires_at")
    if raw_expires is None:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=PACT_DEFAULT_TTL_HOURS)
        ).isoformat()
    else:
        if _parse_iso_utc(raw_expires) is None:
            return jsonify({
                "error": "expires_at must be an ISO 8601 datetime string"
            }), 400
        expires_at = raw_expires.strip()

    # payee: the creator's on-chain recipient, resolved from the bound asset.
    # None when the asset has no registered wallet — never invent one, a
    # fabricated payee would be worse than an absent one at audit time.
    payee = asset.get("wallet_address") if asset else None

    pact_id = "pact-" + secrets.token_hex(6)
    pact = {
        "pact_id": pact_id,
        "status": "pending",
        "task_id": task_id,
        "agent_name": agent_name,
        "creator_id": data.get("creator_id"),
        "asset_id": asset_id,
        "amount": amount_value,
        "currency": currency,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None,
        # AP2-shaped mandate fields
        "intent": intent,
        "amount_cap": amount_cap,
        "expires_at": expires_at,
        "payee": payee,
        "approved_by": None,
        "approval_method": None,
    }
    # Computed last: the digest covers the fields as finally stored.
    pact["content_hash"] = _pact_content_hash(pact)
    # create_pact returns the row as read back, so this response is byte for
    # byte what GET /api/pact/status/<id> will return, and any storage
    # round-trip that changed a value would surface here rather than as a
    # content_hash mismatch at settle time.
    stored = create_pact(current_app.config["DATABASE_PATH"], pact)
    return jsonify(stored), 201


@main.route("/api/pact/status/<pact_id>", methods=["GET"])
def pact_status(pact_id):
    """Return the current pact state."""
    pact, err = _pact_or_404(pact_id)
    if err:
        return err
    return jsonify(pact)


@main.route("/api/pact/approve/<pact_id>", methods=["POST"])
def pact_approve(pact_id):
    """Move a pending pact to approved (simulates wallet-side approval)."""
    pact, err = _pact_or_404(pact_id)
    if err:
        return err
    if pact["status"] != "pending":
        return jsonify({
            "error": f"Pact must be pending to approve, current: {pact['status']}"
        }), 400
    # Mandate TTL. Checked after the state check so an already-approved or
    # rejected pact keeps reporting the state-machine error it always has.
    if _pact_is_expired(pact):
        return jsonify({"error": "pact expired"}), 409
    # Conditional on `pending`, so two concurrent approvals cannot both write
    # an approved_by: the loser gets the same 400 a late approval always got.
    # The audit pair is written in the same statement as the flip — a pact is
    # never approved without a record of who approved it and how. Deliberately
    # not called `user_authorization`: this is a UI click, there is no
    # signature behind it (see the AP2 vocabulary note at the top).
    moved = transition_pact(
        current_app.config["DATABASE_PATH"], pact_id, "pending", "approved",
        approved_at=datetime.now(timezone.utc).isoformat(),
        approved_by=get_current_identity()["id"],
        approval_method="ui",
    )
    if not moved:
        return _pact_status_conflict(pact_id, "pending to approve")
    return jsonify(get_pact(current_app.config["DATABASE_PATH"], pact_id))


@main.route("/api/pact/reject/<pact_id>", methods=["POST"])
def pact_reject(pact_id):
    """Move a pending pact to rejected. Terminal state."""
    pact, err = _pact_or_404(pact_id)
    if err:
        return err
    if pact["status"] != "pending":
        return jsonify({
            "error": f"Pact must be pending to reject, current: {pact['status']}"
        }), 400
    if not transition_pact(
        current_app.config["DATABASE_PATH"], pact_id, "pending", "rejected"
    ):
        return _pact_status_conflict(pact_id, "pending to reject")
    return jsonify(get_pact(current_app.config["DATABASE_PATH"], pact_id))


# ─── Stage 2 / WP-E: settling by PAYING FOR the invocation (spec S8) ──────────
#
# When the app's configured settlement provider is the x402 one, settle does NOT
# write an accrued ledger row and then invoke the tool. It invokes the SkillAsset
# THROUGH the x402 paywall — that invocation IS the payment (our payer signs an
# EIP-3009 USDC authorization, the facilitator broadcasts it) — and only then
# records the run, pre-settled, with the transaction hash the facilitator
# returned.
#
# Why the order has to flip:
#   * legacy rails (mock / anvil / sepolia): the platform pays AFTER the fact,
#     so the ledger row is the instruction to pay and must exist first.
#   * x402: the money moves before we get a result back, so a row written first
#     would assert a payment that has not happened, and a refused payment would
#     leave the creator "billed" for something nobody paid for.
#
# Failure posture — the part worth reading twice:
#   * nothing was paid  → nothing is recorded, the pact goes back to `approved`,
#     the caller may retry.
#   * something WAS paid but we could not record it → the pact stays `settling`,
#     a state settle() refuses to act on, so a retry cannot sign a SECOND
#     authorization against the same mandate. The tx hash is stashed on the pact
#     and logged; turning it into a ledger row is then a manual operator step.
#
# There is deliberately NO path that writes an accrued row when the payment did
# not happen — that would silently switch rails in the middle of a settle.

# The x402 settlement provider's `name` (app/services/x402_settlement.py).
X402_PROVIDER_NAME = "x402"

# mcp_client folds x402 payer exceptions into
# `{"status": "error", "error": "<ExceptionClassName>: <message>"}` and keeps the
# class name on purpose (see app/services/mcp_client.py). That name is the only
# thing that survives the seam, so it is the documented way to tell "the quote
# was above the ceiling, nothing was signed" apart from every other failure.
_SPEND_CAP_ERROR_MARKER = "SpendCapExceeded"


def _settlement_provider_name() -> str:
    """The configured provider's name ('mock' / 'anvil' / 'sepolia' / 'x402').

    Read off the provider INSTANCE, never by re-reading
    HIRENET_SETTLEMENT_PROVIDER here: create_app resolves that env var once, and
    tests inject a pre-built provider through config["SETTLEMENT_PROVIDER"], so
    re-reading the env could disagree with the object the app actually holds.
    Same accessor as /api/royalty/settle and the royalty status poll.
    """
    provider = current_app.config.get("SETTLEMENT_PROVIDER")
    if provider is None:
        return ""
    return getattr(provider, "name", provider.__class__.__name__)


def _x402_explorer_url(tx_hash: str | None) -> str | None:
    """Block-explorer link for a settled x402 tx; None when there is no hash.

    Prefers the configured provider's own helper so the link comes from the
    same object that will later confirm the tx on-chain; falls back to the
    module-level helper (identical output) if the provider does not expose one.
    """
    if not tx_hash:
        return None
    provider = current_app.config.get("SETTLEMENT_PROVIDER")
    helper = getattr(provider, "explorer_url", None)
    if callable(helper):
        return helper(tx_hash)
    from app.services.x402_settlement import explorer_url

    return explorer_url(tx_hash)


def _pact_settle_x402(pact: dict, asset: dict | None, asset_id: str,
                      charge_chain: str | None):
    """Settle a pact on the x402 rail: pay, then record. See the block above.

    Called by `pact_settle` only, and only after the shared prologue has run the
    mandate checks (expiry, integrity, amount <= cap) and resolved the asset,
    its currency and its price_chain. Returns whatever the route returns.
    """
    from app.services.agent_run_recording import USDC_ATOMIC_PER_CENT, record_agent_run
    from app.services.mcp_client import call_mcp_tool, pick_tool_for_task
    from app.services.x402_gate import usd_to_atomic
    from app.services.x402_payer import max_amount_per_payment

    # The invocation IS the payment, so an asset with nowhere to invoke cannot
    # settle on this rail at all. Refused before the pact is claimed, so there
    # is nothing to undo and the pact stays `approved`.
    endpoint_url = (asset or {}).get("endpoint_url")
    if not endpoint_url:
        return jsonify({
            "error": (
                f"asset {asset_id} has no endpoint_url; an x402 settlement pays "
                "by invoking the SkillAsset and there is nothing to invoke"
            )
        }), 502

    # The ceiling handed to the payer, in USDC atomic units. TWO ceilings apply
    # and we take the tighter of them:
    #   * the mandate's own amount_cap — what the enterprise actually authorized;
    #   * X402_MAX_AMOUNT_PER_PAYMENT — the operator's wallet-level brake.
    # A mandate may lower the brake, never raise it. Both are enforced at the
    # signing point (x402_payer.enforce_spend_cap), so a quote above the ceiling
    # is refused before anything is signed.
    cap_dollars = pact.get("amount_cap")
    if cap_dollars is None:
        cap_dollars = pact.get("amount")
    try:
        cap_atomic = usd_to_atomic(cap_dollars)
    except (TypeError, ValueError):
        return jsonify({"error": "amount_cap must be a valid number"}), 400
    try:
        cap_atomic = min(cap_atomic, max_amount_per_payment())
    except ValueError as exc:
        # Malformed X402_MAX_AMOUNT_PER_PAYMENT. A loud 500 rather than quietly
        # signing under the mandate's cap alone: the operator's brake is not
        # something to guess at.
        current_app.logger.error("x402 payer is misconfigured: %s", exc)
        return jsonify({"error": f"x402 payer is misconfigured: {exc}"}), 500

    # Atomic claim: approved → settling. `settling` is neither terminal nor
    # `settled`; it means "an invocation for this mandate is in flight". A
    # concurrent settle sees it and bounces with the same 400 the legacy path
    # gives — that is what stops two threads signing two authorizations. The
    # claim is a single conditional UPDATE, so it holds across processes too.
    db_path = current_app.config["DATABASE_PATH"]
    pact_id = pact["pact_id"]
    if not transition_pact(db_path, pact_id, "approved", "settling"):
        return _pact_status_conflict(pact_id, "approved to settle")

    mcp_fn = current_app.config.get("MCP_CLIENT", call_mcp_tool)
    tool_name = pick_tool_for_task(
        pact.get("task_id"),
        pact.get("agent_name"),
        (asset or {}).get("name"),
    )
    try:
        result = mcp_fn(
            endpoint_url,
            tool_name,
            {"task_id": pact.get("task_id")},
            # Only this rail passes max_amount; the legacy call keeps its
            # 3-argument shape so existing injected fakes are untouched.
            max_amount=cap_atomic,
        )
    except Exception as exc:  # noqa: BLE001 - MCP_CLIENT is an injection seam
        # call_mcp_tool never raises, but an injected client might. A raise means
        # we never saw a PAYMENT-RESPONSE, so nothing is known to have been paid:
        # release the claim and let the caller retry.
        current_app.logger.exception(
            "x402 invocation raised for pact %s", pact_id
        )
        transition_pact(db_path, pact_id, "settling", "approved")
        return jsonify({
            "error": f"invocation failed: {exc.__class__.__name__}: {exc}"
        }), 502

    result = result or {}
    payment = result.get("payment") or {}

    # ── Signed, transmitted, outcome unknown (Stage 2 / WP-R, review F2) ─────
    # Checked BEFORE the settle_success reset below, because it is the one
    # not-a-success that must NOT go back to `approved`. mcp_client returns
    # status "unknown" only when x402_payer signed an authorization, put it on
    # the wire, and never got a decodable answer about it (no PAYMENT-RESPONSE,
    # an unreadable one, a transport error on the paid retry, or success=true
    # with an empty transaction hash). The authorization may still be settled
    # out of band by the facilitator, so:
    #   * the pact STAYS at `settling` — the claim is what stops a retry from
    #     signing a second authorization with a fresh nonce and paying twice;
    #   * the nonce/payee/amount go on the row so an operator can look the
    #     authorization up on-chain and close it out by hand.
    # There is deliberately no automatic recovery: only a human (or a future
    # on-chain reconciler) can decide whether that money moved.
    if result.get("status") == "unknown":
        pending = result.get("payment_pending") or {}
        error_text = result.get("error") or "payment outcome unknown"
        current_app.logger.error(
            "x402 pact %s signed an authorization (nonce %s, payee %s, %s atomic "
            "units) and never learned its outcome; the pact stays 'settling' and "
            "needs manual reconciliation: %s",
            pact_id, pending.get("nonce"), pending.get("payee"),
            pending.get("amount_atomic"), error_text,
        )
        update_pact_fields(
            db_path, pact_id,
            last_error=error_text,
            payment_pending=pending,
            mcp_result=result,
        )
        return jsonify({
            "error": "payment outcome unknown; manual reconciliation required",
            "pact_id": pact_id,
        }), 502

    # `settle_success is True` is the only thing that means money moved. Note
    # this is checked BEFORE result["status"]: a tool that failed AFTER the
    # facilitator settled still has to be recorded, because dropping a tx hash
    # is how a real payment becomes unexplained missing USDC.
    if payment.get("settle_success") is not True:
        transition_pact(db_path, pact_id, "settling", "approved")
        error_text = result.get("error") or (
            "the SkillAsset endpoint did not ask to be paid (no 402); nothing "
            "was settled on the x402 rail"
        )
        if _SPEND_CAP_ERROR_MARKER in error_text:
            # The quoted price was over the mandate's ceiling; nothing signed.
            return jsonify({"error": "amount exceeds cap"}), 409
        # 502: the failure is upstream of us — the resource server, the payer's
        # signing step, or the facilitator. Nothing was recorded and the mandate
        # is still approved, so the caller can fix the cause and retry.
        return jsonify({"error": error_text}), 502

    tx_hash = payment.get("tx_hash")

    # ── From here on the creator HAS been paid ───────────────────────────────
    # Every remaining failure keeps the pact at `settling` (never back to
    # `approved`) so a retry cannot sign a second authorization for a mandate
    # that has already been paid.
    raw_atomic = payment.get("amount_atomic")
    try:
        amount_atomic = int(str(raw_atomic).strip())
    except (TypeError, ValueError):
        amount_atomic = None
    if (amount_atomic is None or amount_atomic < 0
            or amount_atomic % USDC_ATOMIC_PER_CENT != 0):
        # The gate only ever quotes `price_amount * 10_000`, so a quote that is
        # not a non-negative whole number of cents is a gate/payer bug, not a
        # user error.
        # Refuse to invent a rounded charge_amount; the payment stays visible on
        # the pact and in the log so it can be reconciled by hand.
        current_app.logger.error(
            "x402 payment for pact %s settled tx %s for %r atomic USDC units, "
            "which is not a non-negative whole number of cents (%d atomic "
            "units per cent); no agent_run / royalty row was written",
            pact_id, tx_hash, raw_atomic, USDC_ATOMIC_PER_CENT,
        )
        # The pact stays `settling` (claimed, unfinished) and keeps the hash of
        # the payment that DID happen, so the operator has something to
        # reconcile against and a retry cannot sign a second authorization.
        update_pact_fields(
            db_path, pact_id,
            tx_hash=tx_hash,
            explorer_url=_x402_explorer_url(tx_hash),
            mcp_result=result,
        )
        return jsonify({
            "error": (
                f"paid {raw_atomic!r} atomic USDC units, which is not a "
                "non-negative whole number of cents; the run was NOT recorded "
                "(see server log)"
            ),
            "tx_hash": tx_hash,
        }), 500

    # atomic units → cents. record_agent_run re-asserts this same invariant
    # against `presettled` and refuses the write if the two ever disagree.
    charge_amount_cents = amount_atomic // USDC_ATOMIC_PER_CENT

    try:
        result_row = record_agent_run(
            current_app.config["DATABASE_PATH"],
            agent_name=pact["agent_name"],
            caller_id=get_current_identity()["id"],
            task_id=pact["task_id"],
            asset_id=asset_id,
            charge_amount=charge_amount_cents,  # atomic USDC units → cents
            charge_currency=pact["currency"],
            charge_chain=charge_chain,
            success=True,
            # WP-D: writes the run + creator split as settlement_method="x402",
            # settlement_status="settling" (paid, chain confirmation pending),
            # and the platform / tax shares as "x402-fee-receivable".
            presettled=payment,
        )
    except Exception as e:
        current_app.logger.exception(
            "x402 payment for pact %s settled tx %s but the run could not be "
            "recorded; the pact stays 'settling' so no second authorization can "
            "be signed for it",
            pact_id, tx_hash,
        )
        update_pact_fields(
            db_path, pact_id,
            tx_hash=tx_hash,
            explorer_url=_x402_explorer_url(tx_hash),
            mcp_result=result,
        )
        return jsonify({
            "error": f"Failed to record: {str(e)}", "tx_hash": tx_hash,
        }), 500

    # settling → settled, with everything the settle produced written in the
    # same statement: there is no window where the pact reads `settled` but
    # carries no run_id or tx_hash.
    #
    # settled_amount is what was actually PAID, in dollar units. Additive:
    # `amount` keeps saying what the pact was created for, which is not the same
    # number whenever the asset's list price differs from the requested amount.
    finished = transition_pact(
        db_path, pact_id, "settling", "settled",
        run_id=result_row["run_id"],
        royalty_splits=result_row["royalty_splits"],
        tx_hash=tx_hash,
        explorer_url=_x402_explorer_url(tx_hash),
        settled_amount=float(decimal.Decimal(charge_amount_cents) / 100),
        mcp_result=result,
    )
    if not finished:
        # Unreachable while we hold the claim: only this request can move a
        # pact out of `settling`. If it ever happens something mutated the row
        # out of band, and the run has already been recorded — say so instead
        # of returning a body that claims a state the row does not have.
        current_app.logger.error(
            "x402 pact %s was recorded as run %s (tx %s) but is no longer "
            "'settling'; the pact row was changed out of band",
            pact_id, result_row["run_id"], tx_hash,
        )
        return jsonify({
            "error": (
                "the run was recorded but the pact could not be marked "
                "settled (see server log)"
            ),
            "tx_hash": tx_hash,
        }), 500
    return jsonify(get_pact(db_path, pact_id))


@main.route("/api/pact/settle/<pact_id>", methods=["POST"])
def pact_settle(pact_id):
    """Move approved → settled and record one agent_run + royalty_ledger row.

    Concurrency: two simultaneous POSTs to this endpoint must not both bill
    the creator. `transition_pact` makes "verify status == approved AND flip
    to settled" a single conditional UPDATE — the second request gets
    rowcount 0, re-reads status == "settled" and bounces with 400 before
    reaching record_agent_run. Being a row-level claim rather than a
    process-local lock, it holds across workers as well as threads.

    On record_agent_run failure (e.g. currency mismatch), a second conditional
    transition rolls the status back to "approved" so the caller can retry.
    The expensive DB write itself runs after the claim, so a slow settle
    doesn't block unrelated pacts.

    Currency / split rule come from the bound asset (pact.asset_id when
    supplied at create time, else the Phase 1 Job Design fallback).
    charge_amount is converted from dollar units (pact.amount) to integer
    basis points via Decimal — record_agent_run rejects floats / negatives.

    Two rails (Stage 2 / WP-E). Everything above the "Rail selection" comment
    below is shared; then:
      * provider is x402 → `_pact_settle_x402` pays for the invocation and
        records the run afterwards, pre-settled with a real tx hash;
      * any other provider → the legacy post-hoc path below, unchanged.
    """
    pact, err = _pact_or_404(pact_id)
    if err:
        return err

    # ── Mandate checks (AP2-shaped; see the section comment above) ───────────
    # Run before any state transition or DB write so a refused mandate leaves
    # the pact exactly as it was. Integrity is checked before the cap so a
    # tampered pact is reported as tampered rather than as merely over-budget.
    if _pact_is_expired(pact):
        return jsonify({"error": "pact expired"}), 409
    if pact.get("content_hash") is not None and \
            _pact_content_hash(pact) != pact["content_hash"]:
        return jsonify({"error": "pact integrity check failed"}), 409
    amount_cap = pact.get("amount_cap")
    if amount_cap is not None and pact.get("amount") is not None:
        try:
            over_cap = decimal.Decimal(str(pact["amount"])) > decimal.Decimal(str(amount_cap))
        except (ValueError, TypeError, decimal.InvalidOperation):
            return jsonify({"error": "amount must be a valid number"}), 400
        if over_cap:
            return jsonify({"error": "amount exceeds cap"}), 409

    asset_id = pact.get("asset_id") or current_app.config.get("JOB_DESIGN_ASSET_ID")
    if not asset_id:
        return jsonify({"error": "No asset_id available for billing"}), 400

    # Pull the asset's price_chain so the resulting royalty row lands in the
    # right chain bucket. Without this, record_agent_run defaults charge_chain
    # to None and any chain-specific revenue is mis-attributed.
    from app.storage.skill_assets import get_skill_asset
    asset = get_skill_asset(current_app.config["DATABASE_PATH"], asset_id)
    charge_chain = asset.get("price_chain") if asset else None

    if pact.get("amount") is None:
        return jsonify({"error": "Pact amount is required for settlement"}), 400

    # Pre-flight currency check: record_agent_run also rejects mismatches, but
    # only after the status flip — by then a ValueError surfaces as 500 and we
    # have to roll back. Catching it here keeps the failure a clean 400 and
    # leaves the pact in 'approved' so the caller can retry with the right
    # currency.
    if asset and pact["currency"] != asset["price_currency"]:
        return jsonify({
            "error": (
                f"Pact currency {pact['currency']!r} does not match asset "
                f"currency {asset['price_currency']!r}"
            )
        }), 400

    # Decimal conversion guards against float underflow (0.29 * 100 → 28.999…)
    # and string concatenation ("60" * 100 → "6060…"). str() coerces any
    # numeric / string input through Decimal's parser. ROUND_HALF_UP avoids
    # Python's default banker's rounding, where Decimal('0.5') → 0 silently
    # eats a cent.
    try:
        charge_amount_cents = int(
            (decimal.Decimal(str(pact["amount"])) * 100).to_integral_value(
                rounding=decimal.ROUND_HALF_UP
            )
        )
    except (ValueError, TypeError, decimal.InvalidOperation):
        return jsonify({"error": "amount must be a valid number"}), 400

    # ── Rail selection (Stage 2 / WP-E) ──────────────────────────────────────
    # The x402 provider settles by PAYING FOR the invocation, which inverts the
    # order of everything below — see the section comment above
    # `_pact_settle_x402`. Every other provider keeps the legacy post-hoc path
    # unchanged. Everything up to here (mandate checks, asset + currency
    # resolution, the amount validation just above) is shared by both rails.
    if _settlement_provider_name() == X402_PROVIDER_NAME:
        return _pact_settle_x402(pact, asset, asset_id, charge_chain)

    # Atomic claim: one conditional UPDATE, so only one caller sees
    # status=="approved" and flips it to "settled". Any concurrent caller —
    # including one in another worker process — gets rowcount 0, observes
    # "settled" and exits with 400 before duplicating the agent_run/royalty
    # rows.
    db_path = current_app.config["DATABASE_PATH"]
    if not transition_pact(db_path, pact_id, "approved", "settled"):
        return _pact_status_conflict(pact_id, "approved to settle")

    try:
        from app.services.agent_run_recording import record_agent_run
        result = record_agent_run(
            current_app.config["DATABASE_PATH"],
            agent_name=pact["agent_name"],
            caller_id=get_current_identity()["id"],
            task_id=pact["task_id"],
            asset_id=asset_id,
            charge_amount=charge_amount_cents,  # dollars → cents
            charge_currency=pact["currency"],
            charge_chain=charge_chain,
            success=True,
        )
    except Exception as e:
        # Roll back the optimistic claim so the caller can retry. Conditional
        # on `settled` so the rollback can only ever undo OUR claim, never a
        # state some other caller has since moved the pact into.
        transition_pact(db_path, pact_id, "settled", "approved")
        return jsonify({"error": f"Failed to record: {str(e)}"}), 500

    # Persisted before the invocation below: if the process dies mid-MCP the
    # settled pact still points at the run that billed it.
    update_pact_fields(
        db_path, pact_id,
        run_id=result["run_id"],
        royalty_splits=result["royalty_splits"],
    )

    # ── MCP execution (post-billing) ─────────────────────────────────────
    # The royalty/agent_run rows are already committed; what follows is
    # the "actual agent invocation". The MCP client never raises (it folds
    # every failure into status="error"), so a misconfigured endpoint
    # cannot roll back the just-recorded settlement.
    if asset and asset.get("endpoint_url"):
        from app.services.mcp_client import call_mcp_tool, pick_tool_for_task
        mcp_fn = current_app.config.get("MCP_CLIENT", call_mcp_tool)
        tool_name = pick_tool_for_task(
            pact.get("task_id"),
            pact.get("agent_name"),
            asset.get("name") if asset else None,
        )
        mcp_result = mcp_fn(
            asset["endpoint_url"],
            tool_name,
            {"task_id": pact.get("task_id")},
        )
    else:
        mcp_result = None

    # Written even when None: `mcp_result: null` has always been part of the
    # settle response for an asset with no endpoint_url. The DAO stores it as
    # the JSON text 'null', which is how "set to None" stays distinguishable
    # from "never written" (an unsettled pact has no mcp_result key at all).
    update_pact_fields(db_path, pact_id, mcp_result=mcp_result)

    return jsonify(get_pact(db_path, pact_id))


def create_app(config: dict | None = None):
    load_dotenv()
    app = Flask(__name__)
    app.secret_key = os.getenv("APP_SECRET_KEY", secrets.token_hex(32))

    default_db = os.path.join(os.path.expanduser("~"), ".hirenet", "hirenet.db")
    app.config["DATABASE_PATH"] = os.getenv("HIRENET_DB_PATH", default_db)
    # Phase 1 stub: single hard-coded creator identity used for all registrations.
    # Real per-user authentication is deferred to Phase 2.
    app.config["PHASE1_CREATOR_ID"] = os.getenv("HIRENET_PHASE1_CREATOR_ID", "phase1_stub_creator")
    # Phase 1 stub: caller (employer) identity comes from server config, not the request.
    # Symmetric with PHASE1_CREATOR_ID; real per-user auth is deferred to Phase 2.
    app.config["PHASE1_CALLER_ID"] = os.getenv("HIRENET_PHASE1_CALLER_ID", "phase1_stub_employer")
    if config:
        app.config.update(config)

    # Serve frontend static files (built React app). Registered on the `app`
    # object (not the module-level `main` blueprint) because create_app runs
    # once per test, and Flask raises AssertionError if you add routes to a
    # blueprint after the first register_blueprint. `app` is rebuilt each call,
    # so app-level decorators stay legal across many create_app invocations.
    #
    # Path resolution: absolute path computed once at app creation, so gunicorn's
    # working directory does not matter. On Railway (nixpacks), the repo lands at
    # /app and this file at /app/app/app.py — so frontend_dir resolves to
    # /app/frontend/dist. If that directory or index.html is missing (e.g.
    # nixpacks build step didn't run, or dist wasn't committed), every SPA route
    # would otherwise return a silent 404 from send_from_directory. Print a
    # loud warning at boot so Railway logs surface the real cause.
    frontend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    )
    app.config["FRONTEND_DIR"] = frontend_dir
    if not os.path.isfile(os.path.join(frontend_dir, "index.html")):
        print(
            f"[hirenet] WARNING: frontend dist missing at {frontend_dir} — "
            "SPA routes will 404. Check railway.toml buildCommand or that "
            "frontend/dist is committed.",
            flush=True,
        )

    @app.route("/assets/<path:filename>")
    def frontend_assets(filename):
        return send_from_directory(
            os.path.join(current_app.config["FRONTEND_DIR"], "assets"),
            filename,
        )

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        dist = current_app.config["FRONTEND_DIR"]
        if path and os.path.isfile(os.path.join(dist, path)):
            return send_from_directory(dist, path)
        return send_from_directory(dist, "index.html")

    init_db(app)
    app.register_blueprint(main)

    from app.routes.skills import skills_bp
    app.register_blueprint(skills_bp)

    from app.routes.earnings import earnings_bp
    app.register_blueprint(earnings_bp)

    # Codex P1: /api/audit/run/<run_id> currently has @login_required but no
    # per-caller IDOR check (any authenticated user can read any run's audit
    # trail). Until that's closed in the broader Phase 2 IDOR cleanup, only
    # register the blueprint when the harness is explicitly dev-shaped —
    # TESTING=True for pytest fixtures, app.debug for the local Flask dev
    # server. A production gunicorn boot has neither flag, so the endpoint
    # returns 404 (not registered) instead of leaking cross-user audit data
    # behind nothing but a valid JWT.
    if app.config.get("TESTING") or app.debug:
        from app.routes.audit import audit_bp
        app.register_blueprint(audit_bp)

    # U6: register the Job Design Agent as the first SkillAsset (idempotent across
    # restarts), so a real employer task that uses it can be billed to its creator.
    from app.services.asset_bootstrap import bootstrap_job_design_asset
    app.config["JOB_DESIGN_ASSET_ID"] = bootstrap_job_design_asset(
        app.config["DATABASE_PATH"], app.config["PHASE1_CREATOR_ID"]
    )

    # Demo preset: zhang_ai 的"客服话术生成器"Agent + 两条历史调用（li_boss 主调）。
    # 仅在非测试启动时跑 — 526 个 pytest 走 TESTING=True 路径，不见此数据。
    # TIER 1 §2/§3 说明详见 app/services/demo_bootstrap.py。
    if not app.config.get("TESTING"):
        from app.services.demo_bootstrap import (
            bootstrap_demo_data_analyst_asset, bootstrap_demo_extra_assets, bootstrap_demo_runs,
        )
        da_asset_id = bootstrap_demo_data_analyst_asset(app.config["DATABASE_PATH"])
        app.config["DEMO_DA_AGENT_ASSET_ID"] = da_asset_id
        bootstrap_demo_runs(app.config["DATABASE_PATH"], da_asset_id)
        # 额外预设（数据分析助手 / SEO Agent）—— 只为 Agent 世界提供更多卡片，
        # 不绑历史调用，不影响 ExecutionPage tx_hash 演示。
        bootstrap_demo_extra_assets(app.config["DATABASE_PATH"])

    # Phase 3: pick the settlement provider per env var. Tests inject a
    # pre-built provider via config={"SETTLEMENT_PROVIDER": <fake>} — we honour
    # that override so a failing-mock fixture can drive the failed/retry path
    # without monkeypatching at module scope. Default is `mock` so a bare
    # `python wsgi.py` boots without external dependencies; opt into anvil /
    # sepolia by setting HIRENET_SETTLEMENT_PROVIDER explicitly in .env.
    if "SETTLEMENT_PROVIDER" not in app.config:
        from app.services.settlement import get_provider
        provider_name = os.getenv("HIRENET_SETTLEMENT_PROVIDER", "mock")
        app.config["SETTLEMENT_PROVIDER"] = get_provider(provider_name)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("APP_PORT", 3000)))
    print(f"HireNet running on http://localhost:{port}")
    create_app().run(debug=False, host="0.0.0.0", port=port, threaded=True)
