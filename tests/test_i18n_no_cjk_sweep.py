"""
WP-I18N-2 / commit 6 — the sweep: EVERY JSON route the SPA calls, in English,
must answer without a single CJK character.

The per-commit tests check one mechanism each. This one checks the PROMISE:
"English mode is English everywhere". It is deliberately end-to-end and
deliberately blunt — walk the whole response tree, fail on any CJK — because
the failure mode this work package exists to prevent is a single missed read
site, and a targeted test only finds the sites someone remembered.

The route list is DERIVED from `frontend/src/services/api.js`, not
hand-maintained: `test_the_sweep_covers_every_route_api_js_calls` extracts
every `apiUrl(...)` in that file and asserts the set matches `COVERED_PATHS`
exactly. Add a `fetch` to the SPA without adding it here and that test fails.

LLM calls go through `fake_llm` (the conftest factory seam) or an explicitly
injected fake; nothing here touches the network. Where the model's own prose
is involved the scripted response is English — the point is to catch HireNet's
own strings, and a Chinese canned response would only be testing the fake.
"""
import json
import re
from pathlib import Path

import pytest

import app.agents.application_agent as application_agent_module
import app.agents.job_design as job_design_module
import app.app as app_module
from tests.conftest import FakeLLMClient
from tests.test_analyze_routes_v1 import CountingStub
from tests.test_i18n_decision_strings import (
    ENGLISH_JOB_DESIGN,
    ENGLISH_TASKS,
    _install_stub_evaluator,
)
from tests.test_i18n_helpers import assert_no_bilingual_nodes, assert_no_cjk

API_JS = Path(__file__).resolve().parent.parent / "frontend" / "src" / "services" / "api.js"


@pytest.fixture(autouse=True)
def _guard_no_real_llm(no_real_llm_client):
    """No test in this module may construct the real OpenAI client."""


# ─── The route list, derived from api.js ─────────────────────────────────────

#: `apiUrl('/x')` or ``apiUrl(`/x/${id}/y`)`` -> the path, with every
#: `${...}` interpolation collapsed to `<param>` so the two sides can be
#: compared without knowing what the client happens to interpolate.
_API_URL_CALL = re.compile(r"apiUrl\(\s*(['\"`])(.+?)\1\s*\)")
_INTERPOLATION = re.compile(r"\$\{[^}]*\}")


def api_js_paths() -> set[str]:
    source = API_JS.read_text(encoding="utf-8")
    return {
        _INTERPOLATION.sub("<param>", match.group(2))
        for match in _API_URL_CALL.finditer(source)
    }


#: Every path the sweep below exercises. Kept as normalised api.js paths so
#: the derivation test can compare the two sets directly.
COVERED_PATHS = {
    "/analyze/start",
    "/analyze/reply",
    "/analyze/decide",
    "/jobs",
    "/candidates",
    "/candidates/<param>/profile",
    "/apply",
    "/demo/identities",
    "/demo/identity",
    "/demo/agent",
    "/jobs/publish",
    "/candidate/analyze",
    "/pact/create",
    "/pact/approve/<param>",
    "/pact/settle/<param>",
    "/royalty/settle",
    "/skills/register",
    "/skills/list",
    "/creator/earnings",
    "/creator/ledger",
    "/auth/login",
    "/auth/me",
}


def test_the_sweep_covers_every_route_api_js_calls():
    """The guard that keeps this file honest as the SPA grows."""
    from_api_js = api_js_paths()
    assert from_api_js, "failed to parse any apiUrl() call out of api.js"
    missing = from_api_js - COVERED_PATHS
    stale = COVERED_PATHS - from_api_js
    assert not missing, f"api.js calls routes the sweep does not exercise: {sorted(missing)}"
    assert not stale, f"the sweep lists routes api.js no longer calls: {sorted(stale)}"


def test_every_fetch_in_api_js_goes_through_apiUrl():
    """`apiUrl()` is what attaches `?lang=`; a raw template URL would bypass it."""
    source = API_JS.read_text(encoding="utf-8")
    assert "${API_BASE}/" not in source, (
        "a fetch in api.js builds its URL without apiUrl(), so it cannot carry lang"
    )


# ─── Fixtures shared by the sweep ────────────────────────────────────────────

ENGLISH_COMPLETE_RESPONSE = (
    "That is enough to go on.\n"
    "[REQUIREMENT_COMPLETE]\n"
    + json.dumps({
        "project_name": "Support automation",
        "core_description": "An assistant covering pre-sales, after-sales and complaints",
        "tasks_hint": ["Build the knowledge base", "Wire up the ticketing system"],
        "duration": "ongoing",
        "team_context": "A 3-person ops team, no engineers",
        "urgency": "high",
        "budget_hint": "medium",
    }, ensure_ascii=False)
)

ENGLISH_COVER_LETTER = json.dumps({
    "subject": "Application: Full-stack Engineer",
    "cover_letter": "I have shipped React and Node.js products end to end.",
    "key_match_points": ["React", "Node.js"],
    "match_score": 88,
}, ensure_ascii=False)

ENGLISH_JOB_PAYLOAD = {
    "jd": "We are hiring a full-stack engineer.",
    "job_id": "sweep_job_1",
    "company": "A technology startup",
    "job_title": "Full-stack Engineer",
    "required_skills": ["React", "Node.js"],
    "core_responsibilities": ["Build the frontend"],
    "work_type": "full-time",
}

ENGLISH_SKILL_PAYLOAD = {
    "name": "Sweep Test Agent",
    "description": "An agent registered by the no-CJK sweep.",
    "type": "agent",
    "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
    "price_amount": 100,
    "price_currency": "USD",
    "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
}


@pytest.fixture
def fake_cover_letter_llm(monkeypatch):
    client = FakeLLMClient()
    monkeypatch.setattr(application_agent_module, "_get_llm", lambda: client)
    return client


def _english_session(client, fake_llm):
    """Run /analyze/start in English and return its session id."""
    fake_llm.queue(ENGLISH_COMPLETE_RESPONSE)
    res = client.post(
        "/api/analyze/start?lang=en",
        json={"message": "We need a support assistant", "lang": "en"},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()["session_id"]


def _settled_pact(client):
    """create -> approve -> settle a pact on the default (endpoint-less) asset.

    No `asset_id`, so it binds to the bootstrapped Job Design asset, which has
    no `endpoint_url` — `mcp_result` is None and nothing reaches the network.
    Returns the settle response.
    """
    created = client.post("/api/pact/create?lang=en", json={
        "task_id": "sweep-task", "agent_name": "Sweep Agent",
        "amount": 1, "currency": "USD", "lang": "en",
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    pact_id = created.get_json()["pact_id"]
    approved = client.post(f"/api/pact/approve/{pact_id}?lang=en")
    assert approved.status_code == 200, approved.get_data(as_text=True)
    return client.post(f"/api/pact/settle/{pact_id}?lang=en")


# ─── The sweep ───────────────────────────────────────────────────────────────
#
# Each case is `(path, callable)`. The callable gets the fixtures it needs and
# returns the Flask response whose body is swept. Cases are self-contained:
# anything a route needs (a session, a pact, a login) is created inside it, so
# a single failing case never cascades.


def _case_analyze_start(client, fake_llm, **_):
    fake_llm.queue(ENGLISH_COMPLETE_RESPONSE)
    return client.post("/api/analyze/start?lang=en",
                       json={"message": "We need a support assistant", "lang": "en"})


def _case_analyze_reply(client, fake_llm, **_):
    session_id = _english_session(client, fake_llm)
    fake_llm.queue(ENGLISH_COMPLETE_RESPONSE)
    return client.post("/api/analyze/reply?lang=en",
                       json={"session_id": session_id, "message": "Long-running, please",
                             "lang": "en"})


def _case_analyze_decide(client, fake_llm, monkeypatch, **_):
    monkeypatch.setenv("HIRENET_TASK_AGENT", "v1")
    monkeypatch.setattr(app_module, "decompose_tasks",
                        CountingStub(result={"tasks": ENGLISH_TASKS}))
    monkeypatch.setattr(job_design_module, "design_job",
                        CountingStub(result=dict(ENGLISH_JOB_DESIGN)))
    _install_stub_evaluator(monkeypatch)
    session_id = _english_session(client, fake_llm)
    return client.post("/api/analyze/decide?lang=en",
                       json={"session_id": session_id, "lang": "en"})


def _case_jobs(client, **_):
    return client.get("/api/jobs?lang=en")


def _case_candidates(client, **_):
    return client.get("/api/candidates?lang=en")


def _case_candidate_profile(client, **_):
    return client.get("/api/candidates/candidate_b/profile?lang=en")


def _case_apply(client, fake_cover_letter_llm, **_):
    fake_cover_letter_llm.queue(ENGLISH_COVER_LETTER)
    return client.post("/api/apply?lang=en", json={
        "candidate_id": "candidate_a",
        "job_design": {
            "job_id": "demo_job_1", "job_title": "Full-stack Engineer",
            "company": "A technology startup",
            "core_responsibilities": ["Build the frontend"],
            "required_skills": ["React"],
        },
        "lang": "en",
    })


def _case_demo_identities(client, **_):
    return client.get("/api/demo/identities?lang=en", headers={"X-Demo-Identity": "zhao_design"})


def _case_demo_identity(client, **_):
    return client.post("/api/demo/identity?lang=en",
                       json={"identity_id": "wang_dev", "lang": "en"})


def _case_demo_agent(client, **_):
    """`/api/demo/agent` 404s under TESTING because the demo bootstrap is
    skipped — so the sweep runs the bootstrap itself and points the config at
    it, which is also what exercises the `name_en` / `description_en`
    fallback in the response."""
    from app.services.demo_bootstrap import bootstrap_demo_data_analyst_asset

    db_path = client.application.config["DATABASE_PATH"]
    client.application.config["DEMO_DA_AGENT_ASSET_ID"] = (
        bootstrap_demo_data_analyst_asset(db_path)
    )
    return client.get("/api/demo/agent?lang=en")


def _case_jobs_publish(client, **_):
    return client.post("/api/jobs/publish?lang=en",
                       json=dict(ENGLISH_JOB_PAYLOAD, lang="en"),
                       headers={"X-Demo-Identity": "li_boss"})


def _case_candidate_analyze(client, fake_llm, **_):
    fake_llm.queue("- Ships full-stack features end to end\n- Strong React and Node.js background")
    return client.post("/api/candidate/analyze?lang=en", json={
        "profile": {"id": "candidate_a", "skills": ["React"]}, "lang": "en",
    })


def _case_pact_create(client, **_):
    return client.post("/api/pact/create?lang=en", json={
        "task_id": "sweep-task", "agent_name": "Sweep Agent",
        "amount": 1, "currency": "USD", "lang": "en",
    })


def _case_pact_approve(client, **_):
    created = client.post("/api/pact/create?lang=en", json={
        "task_id": "sweep-task-approve", "agent_name": "Sweep Agent",
        "amount": 1, "currency": "USD", "lang": "en",
    })
    return client.post(f"/api/pact/approve/{created.get_json()['pact_id']}?lang=en")


def _case_pact_settle(client, **_):
    return _settled_pact(client)


def _case_royalty_settle(client, **_):
    run_id = _settled_pact(client).get_json()["run_id"]
    return client.post("/api/royalty/settle?lang=en", json={"run_id": run_id, "lang": "en"})


def _case_skills_register(client, **_):
    return client.post("/api/skills/register?lang=en", json=ENGLISH_SKILL_PAYLOAD)


def _case_skills_list(client, **_):
    return client.get("/api/skills/list?lang=en")


def _case_creator_earnings(client, **_):
    return client.get("/api/creator/earnings?lang=en", headers={"X-Demo-Identity": "zhao_design"})


def _case_creator_ledger(client, **_):
    return client.get("/api/creator/ledger?lang=en", headers={"X-Demo-Identity": "zhao_design"})


def _case_auth_login(client, **_):
    return client.post("/api/auth/login?lang=en",
                       json={"user_id": "li_boss", "password": "demo123", "lang": "en"})


def _case_auth_me(client, **_):
    token = client.post("/api/auth/login?lang=en", json={
        "user_id": "zhang_ai", "password": "demo123",
    }).get_json()["token"]
    return client.get("/api/auth/me?lang=en", headers={"Authorization": f"Bearer {token}"})


SWEEP_CASES = [
    ("/analyze/start", _case_analyze_start),
    ("/analyze/reply", _case_analyze_reply),
    ("/analyze/decide", _case_analyze_decide),
    ("/jobs", _case_jobs),
    ("/candidates", _case_candidates),
    ("/candidates/<param>/profile", _case_candidate_profile),
    ("/apply", _case_apply),
    ("/demo/identities", _case_demo_identities),
    ("/demo/identity", _case_demo_identity),
    ("/demo/agent", _case_demo_agent),
    ("/jobs/publish", _case_jobs_publish),
    ("/candidate/analyze", _case_candidate_analyze),
    ("/pact/create", _case_pact_create),
    ("/pact/approve/<param>", _case_pact_approve),
    ("/pact/settle/<param>", _case_pact_settle),
    ("/royalty/settle", _case_royalty_settle),
    ("/skills/register", _case_skills_register),
    ("/skills/list", _case_skills_list),
    ("/creator/earnings", _case_creator_earnings),
    ("/creator/ledger", _case_creator_ledger),
    ("/auth/login", _case_auth_login),
    ("/auth/me", _case_auth_me),
]


def test_the_case_table_matches_the_covered_paths():
    assert {path for path, _ in SWEEP_CASES} == COVERED_PATHS


@pytest.mark.parametrize("path, case", SWEEP_CASES, ids=[p for p, _ in SWEEP_CASES])
def test_no_cjk_in_english_mode(path, case, client, fake_llm, fake_cover_letter_llm, monkeypatch):
    res = case(
        client=client,
        fake_llm=fake_llm,
        fake_cover_letter_llm=fake_cover_letter_llm,
        monkeypatch=monkeypatch,
    )
    assert res.status_code in (200, 201), (
        f"{path} -> {res.status_code}: {res.get_data(as_text=True)[:400]}"
    )
    payload = json.loads(res.get_data(as_text=True))
    assert_no_cjk(payload, f"GET/POST {path}?lang=en")
    # The other half of the guarantee: an unresolved seed node renders as the
    # literal string "{'zh': …, 'en': …}" in the UI, and carries no CJK of its
    # own once the English side is picked — so it must be checked separately.
    assert_no_bilingual_nodes(payload, f"{path}?lang=en")
