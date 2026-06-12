"""
Smoke tests for the Demo identity system + JD publish + candidate analyze stub.

Only the LLM call in /api/candidate/analyze is treated as a real LLM boundary —
we stub it with monkeypatch so this file stays offline (per memory: prove via
real path, stub only LLM 边界).
"""
import json
import types

import pytest


class TestDemoIdentities:
    def test_list_identities(self, client):
        resp = client.get("/api/demo/identities")
        assert resp.status_code == 200
        body = resp.get_json()
        ids = [it["id"] for it in body["identities"]]
        assert ids == ["li_boss", "zhang_ai", "wang_dev", "zhao_design"]
        # default current id is the Phase 1 fallback employer stub
        assert body["current"]["id"] == "phase1_stub_employer"

    def test_set_identity_via_cookie_round_trip(self, client):
        resp = client.post(
            "/api/demo/identity",
            data=json.dumps({"identity_id": "zhang_ai"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        # subsequent GET reads the cookie
        resp2 = client.get("/api/demo/identities")
        assert resp2.get_json()["current"]["id"] == "zhang_ai"

    def test_set_identity_unknown_id_400(self, client):
        resp = client.post(
            "/api/demo/identity",
            data=json.dumps({"identity_id": "ghost_user"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_header_overrides_cookie(self, client):
        # Set cookie to zhang_ai
        client.post(
            "/api/demo/identity",
            data=json.dumps({"identity_id": "zhang_ai"}),
            content_type="application/json",
        )
        # Now send a request with a header — header should win
        resp = client.get(
            "/api/demo/identities",
            headers={"X-Demo-Identity": "li_boss"},
        )
        assert resp.get_json()["current"]["id"] == "li_boss"


class TestPublishJob:
    def test_publish_success(self, client):
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({"jd": "# Demo JD\n\nbody", "job_title": "Demo 工程师"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["job_id"].startswith("demo_job_")
        assert body["job"]["job_title"] == "Demo 工程师"
        # Default publisher_id is the fallback (no demo identity set in test)
        assert body["job"]["publisher_id"] == "phase1_stub_employer"

    def test_publish_with_demo_identity(self, client):
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({"jd": "# JD"}),
            content_type="application/json",
            headers={"X-Demo-Identity": "li_boss"},
        )
        body = resp.get_json()
        assert body["job"]["publisher_id"] == "li_boss"
        assert body["job"]["company"] == "李老板"  # falls back to identity name

    def test_publish_requires_jd(self, client):
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({"job_id": "demo_job_x"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_publish_rejects_duplicate_job_id(self, client):
        payload = {"jd": "x", "job_id": "demo_job_dupe"}
        first = client.post(
            "/api/jobs/publish",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert first.status_code == 200
        second = client.post(
            "/api/jobs/publish",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert second.status_code == 409

    def test_publish_accepts_structured_fields(self, client):
        """Publisher can attach required_skills / core_responsibilities / work_type.

        Regression for U6: without these the apply-flow's cover letter
        generator saw empty arrays and JobDetail had nothing to render.
        """
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({
                "jd": "# JD\n…",
                "job_id": "demo_job_struct",
                "job_title": "全栈工程师",
                "required_skills": ["React", "Node.js"],
                "core_responsibilities": ["写前端", "写后端"],
                "nice_to_have_skills": ["Rust"],
                "work_type": "full-time",
                "salary_range": {"min": 15000, "max": 25000, "unit": "元/月"},
            }),
            content_type="application/json",
        )
        assert resp.status_code == 200
        job = resp.get_json()["job"]
        assert job["required_skills"] == ["React", "Node.js"]
        assert job["core_responsibilities"] == ["写前端", "写后端"]
        assert job["nice_to_have_skills"] == ["Rust"]
        assert job["work_type"] == "full-time"
        assert job["salary_range"] == {"min": 15000, "max": 25000, "unit": "元/月"}

    def test_publish_defaults_when_structured_fields_omitted(self, client):
        """Backward compat: existing call sites that send only jd still work."""
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({"jd": "x", "job_id": "demo_job_minimal_struct"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        job = resp.get_json()["job"]
        assert job["required_skills"] == []
        assert job["core_responsibilities"] == []
        assert job["work_type"] == "full-time"
        assert "salary_range" not in job

    def test_publish_rejects_bad_work_type(self, client):
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({
                "jd": "x", "job_id": "demo_job_bad_wt", "work_type": "godmode",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "work_type" in resp.get_json()["error"]

    def test_publish_rejects_non_list_required_skills(self, client):
        resp = client.post(
            "/api/jobs/publish",
            data=json.dumps({
                "jd": "x", "job_id": "demo_job_bad_rs",
                "required_skills": "React, Node.js",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "required_skills" in resp.get_json()["error"]

    def test_published_job_visible_in_list_jobs(self, client):
        """JD posted via /api/jobs/publish must surface in GET /api/jobs.

        Regression for Codex P2: JdModal posted to published_jobs but the
        candidate-side /api/jobs only returned demo + session-derived JDs,
        making the new JD invisible. The dedupe should keep duplicates
        (re-publishing the same job_id) from appearing twice.
        """
        unique_id = "demo_job_visible_check"
        # Clean up any leftover from earlier tests in the same session
        from app.app import published_jobs as _pj
        for j in list(_pj):
            if j.get("job_id") == unique_id:
                _pj.remove(j)

        client.post(
            "/api/jobs/publish",
            data=json.dumps({"jd": "# visible JD", "job_id": unique_id,
                             "job_title": "Listed Engineer"}),
            content_type="application/json",
        )

        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        jobs = resp.get_json()["jobs"]
        listed = [j for j in jobs if j.get("job_id") == unique_id]
        assert len(listed) == 1, (
            f"published job {unique_id} not in /api/jobs response "
            f"(got {[j.get('job_id') for j in jobs]})"
        )
        assert listed[0]["job_title"] == "Listed Engineer"


class TestCandidateAnalyze:
    def test_analyze_parses_bullet_list(self, client, monkeypatch):
        """Stub the LLM boundary; verify the route extracts bullets."""
        class FakeResp:
            def __init__(self, text):
                self.choices = [
                    types.SimpleNamespace(
                        message=types.SimpleNamespace(content=text)
                    )
                ]
        class FakeChat:
            def __init__(self, text):
                self.text = text
            def create(self, **kw):
                return FakeResp(self.text)
        class FakeClient:
            def __init__(self, text):
                self.chat = types.SimpleNamespace(completions=FakeChat(text))

        text = (
            "- 三年 Python 后端经验\n"
            "- 主导过支付系统设计\n"
            "- 熟悉云原生部署"
        )

        import app.app as app_module
        monkeypatch.setattr(
            app_module, "__name__", app_module.__name__
        )  # no-op, keeps reference
        # Patch get_llm_client where app.app imports it
        from app.agents import agents as agents_module
        monkeypatch.setattr(
            agents_module, "get_llm_client", lambda: FakeClient(text)
        )

        resp = client.post(
            "/api/candidate/analyze",
            data=json.dumps({"profile": {"name": "demo", "skills": ["Python"]}}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["strengths"] == [
            "三年 Python 后端经验",
            "主导过支付系统设计",
            "熟悉云原生部署",
        ]

    def test_analyze_requires_profile(self, client):
        resp = client.post(
            "/api/candidate/analyze",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
