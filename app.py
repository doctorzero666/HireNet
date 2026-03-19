"""
HireNet Flask Application
Handles OAuth2 flow + API endpoints for the frontend
"""
import os
import json
import secrets
import requests
from datetime import datetime
from flask import Flask, request, jsonify, session, redirect, render_template_string, render_template
from dotenv import load_dotenv

load_dotenv()

from agents import RequirementAnalysisAgent, decompose_tasks, run_resource_decision, CareerStrategyAgent
from job_design import generate_jd_report

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", secrets.token_hex(32))

CLIENT_ID = os.getenv("SECONDME_CLIENT_ID")
CLIENT_SECRET = os.getenv("SECONDME_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:3000/api/auth/callback")
TOKEN_URL = os.getenv("SECONDME_TOKEN_URL")
AUTH_URL = os.getenv("SECONDME_AUTH_URL", "https://go.second.me/oauth/")

# In-memory session store for demo (use Redis in production)
analysis_sessions = {}
career_sessions = {}

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


# ─── OAuth2 Flow ──────────────────────────────────────────────────────────────

@app.route("/api/auth/login")
def login():
    """Initiate OAuth2 flow"""
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return redirect(f"{AUTH_URL}?{query}")


@app.route("/api/auth/callback")
def auth_callback():
    """Handle OAuth2 callback, exchange code for token"""
    code = request.args.get("code")
    state = request.args.get("state")

    # Verify state
    if state != session.get("oauth_state"):
        return jsonify({"error": "Invalid state"}), 400

    # Exchange code for token
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    data = resp.json()

    if data.get("code") != 0:
        return jsonify({"error": "Token exchange failed", "detail": data}), 400

    # Store token in session
    session["access_token"] = data["data"]["accessToken"]
    session["refresh_token"] = data["data"]["refreshToken"]

    return redirect("/?logged_in=true")


@app.route("/api/auth/me")
def get_me():
    """Get current user info"""
    token = session.get("access_token")
    if not token:
        return jsonify({"error": "Not logged in"}), 401

    from secondme_client import SecondMeClient
    client = SecondMeClient(token)
    try:
        info = client.get_user_info()
        return jsonify({"user": info})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Requirement Analysis API ─────────────────────────────────────────────────

@app.route("/api/analyze/start", methods=["POST"])
def start_analysis():
    """Start a new requirement analysis session"""
    data = request.get_json()
    initial_input = data.get("message", "").strip()

    if not initial_input:
        return jsonify({"error": "Message is required"}), 400

    # Create new analysis session
    session_id = secrets.token_hex(8)
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


@app.route("/api/analyze/reply", methods=["POST"])
def reply_analysis():
    """Continue requirement analysis conversation"""
    data = request.get_json()
    session_id = data.get("session_id")
    message = data.get("message", "").strip()

    if session_id not in analysis_sessions:
        return jsonify({"error": "Session not found"}), 404

    sess = analysis_sessions[session_id]
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

@app.route("/api/analyze/decide", methods=["POST"])
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
        # Step 1: Decompose tasks
        task_data = decompose_tasks(requirement)
        tasks = task_data.get("tasks", [])

        # Step 2: Resource decision for each task
        decisions = run_resource_decision(tasks)

        # Step 3: Generate job designs if needed
        jd_report = generate_jd_report(
            decisions,
            requirement,
            original_description=sess.get("initial_input", ""),
        )

        # Step 4: Build summary
        summary = _build_decision_summary(tasks, decisions, jd_report)

        return jsonify({
            "requirement": requirement,
            "tasks": tasks,
            "decisions": decisions,
            "jd_report": jd_report,
            "summary": summary,
        })

    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc(),
        }), 500


def _build_decision_summary(tasks, decisions, jd_report) -> dict:
    """Build human-readable summary of the decision"""
    all_decisions = decisions.get("decisions", [])

    agent_count = sum(
        1 for d in all_decisions
        if d.get("recommendation", {}).get("decision") == "agent"
    )
    human_count = sum(
        1 for d in all_decisions
        if d.get("recommendation", {}).get("decision") == "human"
    )
    hybrid_count = sum(
        1 for d in all_decisions
        if d.get("recommendation", {}).get("decision") == "hybrid"
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


# ─── Candidate Side ───────────────────────────────────────────────────────────

@app.route("/api/candidates", methods=["GET"])
def list_candidates():
    """List demo candidates with their profiles"""
    from candidate_profile import DEMO_CANDIDATES, build_candidate_profile

    candidates = []
    for cid in DEMO_CANDIDATES:
        try:
            profile = build_candidate_profile(cid)
            candidates.append(profile)
        except Exception as e:
            candidates.append({"id": cid, "error": str(e)})

    return jsonify({"candidates": candidates})


@app.route("/api/match", methods=["POST"])
def match_candidates():
    """Match candidates against a job design"""
    data = request.get_json()
    job_design = data.get("job_design")
    session_id = data.get("session_id")

    if not job_design:
        return jsonify({"error": "job_design is required"}), 400

    from candidate_profile import get_all_resources
    from agents import evaluate_resource_for_task

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

@app.route("/api/candidates/<candidate_id>/profile", methods=["GET"])
def get_candidate_profile(candidate_id):
    """Get full profile for a single candidate"""
    from candidate_profile import build_candidate_profile, DEMO_CANDIDATES
    if candidate_id not in DEMO_CANDIDATES:
        return jsonify({"error": "Unknown candidate"}), 404
    try:
        profile = build_candidate_profile(candidate_id)
        return jsonify({"profile": profile})
    except Exception as e:
        # Return static fallback if token not configured
        from candidate_profile import DEMO_CANDIDATES
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
            "capability_summary": "暂无详细信息（Second Me token 未配置）",
        }})


@app.route("/api/jobs", methods=["GET"])
def list_jobs():
    """List available jobs for candidate-side matching"""
    from application_agent import get_demo_jobs

    # Also include any JDs generated in company-side sessions
    extra_jobs = []
    for sess in analysis_sessions.values():
        # Look for jd_report stored in session
        jd_report = sess.get("jd_report")
        if jd_report and jd_report.get("job_designs"):
            extra_jobs.extend(jd_report["job_designs"])

    jobs = get_demo_jobs() + extra_jobs
    return jsonify({"jobs": jobs})


@app.route("/api/candidate-match", methods=["POST"])
def candidate_match():
    """Match a candidate against all available jobs"""
    from application_agent import get_demo_jobs
    from candidate_profile import build_candidate_profile, DEMO_CANDIDATES
    from agents import evaluate_resource_for_task

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


@app.route("/api/apply", methods=["POST"])
def apply_to_job():
    """Generate cover letter and record application"""
    from application_agent import generate_cover_letter, apply_to_job as _apply
    from candidate_profile import build_candidate_profile, DEMO_CANDIDATES

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


@app.route("/api/tracker", methods=["GET"])
def get_tracker():
    """Get all application records (Tracker Agent)"""
    from application_agent import get_applications
    candidate_id = request.args.get("candidate_id")
    apps = get_applications(candidate_id)
    return jsonify({"applications": apps, "total": len(apps)})


# ─── Health check ─────────────────────────────────────────────────────────────

# ─── Career Strategy Agent API ────────────────────────────────────────────────

@app.route("/api/career/start", methods=["POST"])
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


@app.route("/api/career/reply", methods=["POST"])
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

@app.route("/api/career/generate", methods=["POST"])
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tracker/task-complete", methods=["POST"])
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


@app.route("/api/profile/state", methods=["GET"])
def get_profile_state():
    """Get current user profile state (EXP, level, skill boosts)."""
    return jsonify(user_profile_state)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "client_id": CLIENT_ID[:8] + "..."})


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
        "description": "根据岗位需求，从 A2A 网络中匹配最合适的候选人或 Agent",
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


@app.route("/api/mcp", methods=["POST"])
def mcp_endpoint():
    """JSON-RPC 2.0 MCP endpoint for SecondMe OpenClaw integration."""
    body = request.get_json(silent=True) or {}
    rpc_id = body.get("id", 1)
    method = body.get("method", "")
    params = body.get("params", {})

    # Extract Bearer token forwarded by SecondMe
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
                from application_agent import get_demo_jobs
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
                from candidate_profile import get_all_resources
                from agents import evaluate_resource_for_task
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
            import traceback
            return err(-32603, f"Tool execution error: {e}\n{traceback.format_exc()}")

    return err(-32601, f"Method not found: {method}")


# ─── Serve frontend ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main page"""
    return render_template('index.html')


@app.route('/employer')
def employer():
    return render_template('employer.html')

@app.route('/jobseeker')
def jobseeker():
    return render_template('jobseeker.html')

@app.route('/agents')
def agents():
    return render_template('agents.html')


@app.route("/api/analyze/quick", methods=["POST"])
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
    analysis_sessions[session_id] = {
        "agent": None,
        "initial_input": original_description,
        "history": [],
        "requirement": requirement,
    }

    try:
        task_data = decompose_tasks(requirement)
        tasks = task_data.get("tasks", [])
        decisions = run_resource_decision(tasks)
        jd_report = generate_jd_report(
            decisions, requirement, original_description=original_description
        )
        # store jd_report in session for job listing
        analysis_sessions[session_id]["jd_report"] = jd_report
        summary = _build_decision_summary(tasks, decisions, jd_report)

        return jsonify({
            "session_id": session_id,
            "requirement": requirement,
            "tasks": tasks,
            "decisions": decisions,
            "jd_report": jd_report,
            "summary": summary,
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("APP_PORT", 3000)))
    print(f"HireNet running on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True)
