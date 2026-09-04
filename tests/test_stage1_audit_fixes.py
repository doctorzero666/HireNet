"""
Stage 1 / WP5 — the small fixes the audit turned up, each with the test it was
missing.

Three unrelated things live here because they share one cause: they are the
leftovers of the Stage 1 audit that were too small to earn a work package of
their own, and none of them had any test at all.

  * `POST /api/career/generate` returned `str(e)` to the client (D11b says the
    analysis routes must not, and this route is the same kind of route);
  * the module-level demo stores in `app/app.py` leak across tests;
  * `/api/jobs` is the route where that leak is visible.

`app/agents/job_design.py`'s parsing fix has its own file
(`tests/test_job_design.py`) because it needs the fake-LLM machinery.
"""
import logging

import pytest

import app.app as app_module
from tests.conftest import MODULE_LEVEL_STORES


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/career/generate — the exception belongs in the log, not the body
# ──────────────────────────────────────────────────────────────────────────────

class _RaisingAgent:
    """A CareerStrategyAgent stand-in whose failure message must not leak."""

    SECRET = "Error code: 401 - api key sk-live-DO-NOT-LEAK is invalid"

    def force_generate_strategy(self):
        raise RuntimeError(self.SECRET)


class _WorkingAgent:
    STRATEGY = {"direction": "AI 产品经理", "steps": ["补齐 SQL", "做一个 side project"]}

    def force_generate_strategy(self):
        return self.STRATEGY


class TestCareerGenerate:
    def test_a_failing_agent_returns_a_generic_error_not_the_exception(self, client, caplog):
        app_module.career_sessions["s1"] = {"agent": _RaisingAgent(), "strategy": None}

        with caplog.at_level(logging.ERROR):
            resp = client.post("/api/career/generate", json={"session_id": "s1"})

        assert resp.status_code == 500
        assert resp.get_json() == {"error": "career strategy generation failed"}
        assert "sk-live-DO-NOT-LEAK" not in resp.get_data(as_text=True)
        assert "career strategy generation failed" in caplog.text
        assert _RaisingAgent.SECRET in caplog.text, "the real cause still has to be debuggable"

    def test_the_happy_path_is_unchanged(self, client):
        app_module.career_sessions["s2"] = {"agent": _WorkingAgent(), "strategy": None}

        resp = client.post("/api/career/generate", json={"session_id": "s2"})

        assert resp.status_code == 200
        assert resp.get_json() == {"success": True, "strategy": _WorkingAgent.STRATEGY}
        assert app_module.career_sessions["s2"]["strategy"] == _WorkingAgent.STRATEGY

    def test_an_unknown_session_is_still_a_404(self, client):
        resp = client.post("/api/career/generate", json={"session_id": "nope"})

        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Session not found"}


# ──────────────────────────────────────────────────────────────────────────────
# The autouse isolation fixture (tests/conftest.py)
#
# Two tests that only mean something together, and only in this order: the
# first one dirties every store, the second one asserts it is not looking at
# the first one's leftovers. Before the fixture existed, the second one failed.
# ──────────────────────────────────────────────────────────────────────────────

FAKE_JOB = {"job_id": "jd_leak_probe", "job_title": "泄漏探针岗位"}


class TestModuleStoreIsolation:
    def test_1_a_test_may_dirty_every_module_level_store(self, client):
        app_module.published_jobs.append(FAKE_JOB)
        app_module.analysis_sessions["leak_probe"] = {
            "jd_report": {"job_designs": [{"job_id": "jd_leak_probe_2"}]}
        }
        app_module.career_sessions["leak_probe"] = {"agent": None, "strategy": None}
        app_module.user_profile_state["exp"] = 999999

        titles = [j.get("job_id") for j in client.get("/api/jobs").get_json()["jobs"]]
        assert "jd_leak_probe" in titles
        assert "jd_leak_probe_2" in titles

    def test_2_the_next_test_does_not_inherit_any_of_it(self, client):
        assert FAKE_JOB not in app_module.published_jobs
        assert "leak_probe" not in app_module.analysis_sessions
        assert "leak_probe" not in app_module.career_sessions
        assert app_module.user_profile_state["exp"] != 999999

        job_ids = [j.get("job_id") for j in client.get("/api/jobs").get_json()["jobs"]]
        assert "jd_leak_probe" not in job_ids
        assert "jd_leak_probe_2" not in job_ids


@pytest.mark.parametrize("name", MODULE_LEVEL_STORES)
def test_every_store_the_fixture_names_still_exists(name):
    """A rename in app/app.py must not silently turn the isolation off.

    Parametrised over the fixture's own list (Stage 2 / WP-G) rather than a
    copy of it: a store that moves to SQLite leaves both lists at once, and a
    store that is merely RENAMED still fails here.
    """
    assert hasattr(app_module, name)
