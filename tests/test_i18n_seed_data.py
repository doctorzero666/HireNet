"""
WP-I18N-2 / D-B, D-C, D-G — bilingual seed data, its migration, and the routes
that serialise it.

Four things are pinned here:

1. **`lang=en` -> no CJK, and no leaked seed node.** Every JSON route that
   returns demo/seed data is asked in English and the whole response tree is
   walked. `assert_no_bilingual_nodes` is the guardrail for the specific way
   this change can go wrong: forget one `pick()` at a read site and the UI
   renders the literal string `{'zh': '…', 'en': '…'}`.
2. **`lang` absent -> byte-identical Chinese.** The exact pre-change literals
   are asserted, not just "some Chinese" — this is the v1 red line.
3. **Seed keys are identifiers, not content.** Dict keys, `job_id`,
   `candidate_id` and `agent_id` values must survive the rewrite untouched;
   `build_candidate_profile` and the `/api/jobs` dedup key off them.
4. **The SQLite migration is additive and the bootstraps stay idempotent.**
   `name_en` / `description_en` are nullable, are NOT in `content_hash`, and
   are NOT in the bootstrap `expected` match — so a redeploy backfills the
   English text onto the existing row instead of forking a duplicate.
"""
import sqlite3
from contextlib import closing

import pytest

from app.agents.application_agent import DEMO_JOBS, get_demo_jobs
from app.agents.candidate_profile import (
    DEMO_AGENTS,
    DEMO_CANDIDATES,
    MOCK_PROFILES,
    build_agent_profile,
    build_candidate_profile,
    get_all_resources,
)
from app.app import DEMO_IDENTITIES
from app.services.asset_bootstrap import (
    JOB_DESIGN_ASSET,
    JOB_DESIGN_ASSET_EN,
    bootstrap_job_design_asset,
)
from app.services.demo_bootstrap import (
    DEMO_DATA_ANALYST,
    DISPLAY_EN_BY_NAME,
    bootstrap_demo_data_analyst_asset,
    bootstrap_demo_extra_assets,
)
from app.services.skill_registration import compute_content_hash
from app.storage.db import _create_tables, _migrate, _open, _seed_demo_users
from app.storage.skill_assets import list_skill_assets
from tests.test_i18n_helpers import (
    CJK_PATTERN,
    assert_clean_english,
    assert_no_bilingual_nodes,
    assert_no_cjk,
)


# ─── 3. Seed keys are identifiers ─────────────────────────────────────────────


class TestSeedKeyStability:
    """A regression here breaks `build_candidate_profile`, `/api/jobs` dedup,
    `decision_policy.DEFAULT_COST_LOOKUP`, and any client that stored an id."""

    def test_candidate_keys(self):
        assert set(DEMO_CANDIDATES) == {"candidate_a", "candidate_b", "candidate_c"}
        assert set(MOCK_PROFILES) == {"candidate_a", "candidate_b", "candidate_c"}

    def test_candidate_id_fields_match_their_keys(self):
        for key, profile in MOCK_PROFILES.items():
            assert profile["id"] == key
            assert profile["type"] == "human"

    def test_role_hints_are_unchanged_plain_strings(self):
        assert [DEMO_CANDIDATES[c]["role_hint"] for c in ("candidate_a", "candidate_b", "candidate_c")] == [
            "fullstack", "product_manager", "data_analyst",
        ]

    def test_agent_keys_and_cost_hints(self):
        assert set(DEMO_AGENTS) == {"agent_code", "agent_content", "agent_data"}
        assert [DEMO_AGENTS[a]["cost_per_task"] for a in ("agent_code", "agent_content", "agent_data")] == [
            "$0.05", "$0.02", "$0.03",
        ]

    def test_job_ids(self):
        assert [job["job_id"] for job in DEMO_JOBS] == ["demo_job_1", "demo_job_2", "demo_job_3"]

    def test_job_enum_fields_stay_plain(self):
        for job in DEMO_JOBS:
            assert job["work_type"] == "full-time"
            assert job["source"] == "demo"
            assert isinstance(job["water_score"], int)

    def test_identity_keys_ids_roles_avatars(self):
        assert set(DEMO_IDENTITIES) == {"li_boss", "zhang_ai", "wang_dev", "zhao_design"}
        for key, identity in DEMO_IDENTITIES.items():
            assert identity["id"] == key
            assert isinstance(identity["role"], str)
            assert isinstance(identity["avatar"], str)

    def test_decision_policy_cost_lookup_still_resolves(self):
        from app.agents.decision_policy import DEFAULT_COST_LOOKUP

        assert DEFAULT_COST_LOOKUP == {
            "agent_code": "$0.05", "agent_content": "$0.02", "agent_data": "$0.03",
        }


# ─── 2. `lang` absent -> byte-identical Chinese ───────────────────────────────


class TestAccessorsDefaultToTheExactPreI18nChinese:
    def test_candidate_profile(self):
        assert build_candidate_profile("candidate_a") == {
            "id": "candidate_a",
            "type": "human",
            "name": "张伟（全栈工程师）",
            "bio": "3年全栈开发经验，熟悉React+Node.js技术栈，有独立交付产品经验",
            "role_hint": "fullstack",
            "skills": ["React", "Node.js", "TypeScript", "Python", "Docker",
                       "PostgreSQL", "RESTful API", "Git"],
            "experience": ["某互联网公司全栈工程师3年，负责前后端开发和系统架构"],
            "preferences": ["全栈工程师", "前端工程师"],
            "capability_summary": (
                "技能：React、Node.js、TypeScript、Python、Docker；"
                "经验：3年全栈开发，独立交付多个产品"
            ),
            "profile_completeness": 85,
            "raw_memories": [],
        }

    def test_agent_profile_including_the_composed_capability_summary(self):
        assert build_agent_profile("agent_code") == {
            "id": "agent_code",
            "type": "agent",
            "name": "代码生成 Agent",
            "capabilities": ["前端开发", "后端开发", "脚本编写", "代码审查"],
            "cost_per_task": "$0.05",
            "availability": "immediate",
            "capability_summary": "前端开发、后端开发、脚本编写、代码审查",
        }

    def test_demo_jobs(self):
        job = get_demo_jobs()[0]
        assert job["job_title"] == "全栈工程师"
        assert job["company"] == "某科技创业公司"
        assert job["experience_range"] == {"min": 2, "max": 5, "unit": "年"}
        assert job["salary_range"] == {"min": 20000, "max": 35000, "unit": "元/月"}
        assert job["water_analysis"] == "需求明确，职责具体，技能要求合理"
        assert job["core_responsibilities"] == [
            "负责前端 React 页面开发与维护",
            "设计并实现 Node.js 后端 API",
            "参与系统架构设计和技术选型",
        ]

    def test_resource_pool_is_the_same_shape_the_evaluation_prompt_expects(self):
        """`_llm_evaluate_resource` interpolates `resource['name']` straight
        into the v1 prompt — a dict there would change the wire format."""
        for resource in get_all_resources():
            assert isinstance(resource["name"], str)
            assert isinstance(resource["type"], str)
            assert isinstance(resource.get("capability_summary", ""), str)

    def test_seed_literals_are_not_mutated_by_localising_them(self):
        get_all_resources("en")
        get_demo_jobs("en")
        assert MOCK_PROFILES["candidate_a"]["name"] == {
            "zh": "张伟（全栈工程师）", "en": "Wei Zhang (Full-stack Engineer)",
        }
        assert DEMO_JOBS[0]["job_title"] == {"zh": "全栈工程师", "en": "Full-stack Engineer"}


class TestAccessorsInEnglish:
    def test_candidate_profile_has_no_cjk(self):
        profile = build_candidate_profile("candidate_b", "en")
        assert_no_cjk(profile, "build_candidate_profile(candidate_b, 'en')")
        assert_no_bilingual_nodes(profile)
        assert profile["id"] == "candidate_b"

    def test_agent_profile_joins_capabilities_with_a_comma_not_a_dun_comma(self):
        profile = build_agent_profile("agent_data", "en")
        assert profile["capability_summary"] == (
            "Data cleaning, Report generation, Data visualisation, Statistical analysis"
        )
        assert_no_cjk(profile)

    def test_every_resource_in_the_pool_is_english(self):
        for resource in get_all_resources("en"):
            assert_no_cjk(resource, f"resource {resource['id']}")

    def test_every_demo_job_is_english(self):
        for job in get_demo_jobs("en"):
            assert_no_cjk(job, f"job {job['job_id']}")
            assert_no_bilingual_nodes(job)


# ─── 1. Routes ────────────────────────────────────────────────────────────────


def _login(client, user_id="li_boss", password="demo123"):
    res = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()["token"]


#: Every GET route in this commit's scope that needs no request body.
SEED_GET_ROUTES = [
    "/api/candidates",
    "/api/candidates/candidate_a/profile",
    "/api/candidates/candidate_b/profile",
    "/api/candidates/candidate_c/profile",
    "/api/jobs",
    "/api/skills/list",
    "/api/demo/identities",
    "/api/creator/earnings",
    "/api/creator/ledger",
]


class TestSeedRoutesInEnglish:
    @pytest.mark.parametrize("path", SEED_GET_ROUTES)
    def test_no_cjk_and_no_leaked_seed_node(self, client, path):
        res = client.get(f"{path}?lang=en")
        assert res.status_code == 200, res.get_data(as_text=True)
        assert_clean_english(res, path)

    def test_candidates_keep_their_ids(self, client):
        payload = assert_clean_english(client.get("/api/candidates?lang=en"))
        assert [c["id"] for c in payload["candidates"]] == [
            "candidate_a", "candidate_b", "candidate_c",
        ]

    def test_jobs_keep_their_ids(self, client):
        payload = assert_clean_english(client.get("/api/jobs?lang=en"))
        assert [j["job_id"] for j in payload["jobs"]] == [
            "demo_job_1", "demo_job_2", "demo_job_3",
        ]

    def test_identities_keep_ids_roles_and_avatars(self, client):
        payload = assert_clean_english(client.get("/api/demo/identities?lang=en"))
        assert [i["id"] for i in payload["identities"]] == [
            "li_boss", "zhang_ai", "wang_dev", "zhao_design",
        ]
        assert [i["role"] for i in payload["identities"]] == [
            "enterprise", "creator", "jobseeker", "creator",
        ]
        assert payload["identities"][0]["name"] == "Boss Li"

    def test_set_identity_echo(self, client):
        res = client.post(
            "/api/demo/identity?lang=en", json={"identity_id": "zhao_design"}
        )
        assert res.status_code == 200
        payload = assert_clean_english(res, "/api/demo/identity")
        assert payload["identity"]["id"] == "zhao_design"
        assert payload["identity"]["name"] == "Designer Zhao"

    def test_current_identity_follows_the_demo_header(self, client):
        res = client.get("/api/demo/identities?lang=en", headers={"X-Demo-Identity": "wang_dev"})
        payload = assert_clean_english(res)
        assert payload["current"] == {
            "id": "wang_dev", "name": "Engineer Wang", "role": "jobseeker", "avatar": "👤",
        }

    def test_auth_me_uses_the_users_name_en_column(self, client):
        token = _login(client)
        res = client.get("/api/auth/me?lang=en", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        payload = assert_clean_english(res, "/api/auth/me")
        assert payload["user"] == {"id": "li_boss", "name": "Boss Li", "role": "enterprise"}

    def test_auth_login_response_uses_name_en(self, client):
        res = client.post(
            "/api/auth/login?lang=en", json={"user_id": "zhang_ai", "password": "demo123"}
        )
        assert res.status_code == 200
        assert res.get_json()["user"]["name"] == "AI Zhang"

    def test_skills_list_uses_the_backfilled_name_en(self, client):
        """The Job Design Agent is bootstrapped even under TESTING."""
        payload = assert_clean_english(client.get("/api/skills/list?lang=en"))
        assert payload["skills"], "expected the bootstrapped Job Design asset"
        job_design = next(s for s in payload["skills"] if s["name"] == "Job Design Agent")
        assert job_design["description"] == JOB_DESIGN_ASSET_EN["description"]
        assert job_design["creator_name"] == "Phase 1 Stub Creator"


class TestSeedRoutesWithoutLangAreUnchanged:
    def test_candidates(self, client):
        payload = client.get("/api/candidates").get_json()
        assert payload["candidates"][0]["name"] == "张伟（全栈工程师）"
        assert payload["candidates"][0]["capability_summary"].startswith("技能：React")

    def test_candidate_profile(self, client):
        payload = client.get("/api/candidates/candidate_c/profile").get_json()
        assert payload["profile"] == build_candidate_profile("candidate_c")

    def test_jobs(self, client):
        payload = client.get("/api/jobs").get_json()
        assert payload["jobs"] == get_demo_jobs()

    def test_identities(self, client):
        payload = client.get("/api/demo/identities").get_json()
        assert [i["name"] for i in payload["identities"]] == ["李老板", "张AI", "王工", "赵设计"]

    def test_auth_me(self, client):
        token = _login(client)
        payload = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).get_json()
        assert payload["user"]["name"] == "李老板"

    def test_skills_list_keeps_the_chinese_description(self, client):
        payload = client.get("/api/skills/list").get_json()
        job_design = next(s for s in payload["skills"] if s["name"] == "Job Design Agent")
        assert job_design["description"] == JOB_DESIGN_ASSET["description"]
        assert CJK_PATTERN.search(job_design["description"])

    def test_publish_job_title_fallback(self, client):
        res = client.post(
            "/api/jobs/publish",
            json={"jd": "some jd", "job_id": "zh_fallback"},
            headers={"X-Demo-Identity": "li_boss"},
        )
        assert res.status_code == 200
        job = res.get_json()["job"]
        assert job["job_title"] == "Demo 岗位"
        assert job["company"] == "李老板"

    def test_publish_job_title_fallback_in_english(self, client):
        res = client.post(
            "/api/jobs/publish?lang=en",
            json={"jd": "some jd", "job_id": "en_fallback"},
            headers={"X-Demo-Identity": "li_boss"},
        )
        assert res.status_code == 200
        job = res.get_json()["job"]
        assert job["job_title"] == "Demo role"
        assert job["company"] == "Boss Li"
        assert_no_cjk(job, "published job")


# ─── 4. Migration + bootstrap idempotency ─────────────────────────────────────

#: The three columns this work package adds. The fixture below builds the
#: CURRENT schema and then drops exactly these, so the "pre-migration"
#: database is the real thing minus this change — not a hand-copied DDL that
#: silently drifts from db.py.
_I18N_COLUMNS = (
    ("skill_assets", "name_en"),
    ("skill_assets", "description_en"),
    ("users", "name_en"),
)

_LEGACY_ASSET = (
    "legacy-asset-1", "zhao_design", "遗留资产", "一段中文描述", "agent", None,
    '{"input": {}}', 100, "USD", None, '{"creator": 10000}', "a" * 64, None,
    "2026-01-01T00:00:00+00:00",
)


@pytest.fixture
def pre_i18n_db(tmp_path):
    """A database on the pre-WP-I18N-2 schema, holding one row per table."""
    db_path = str(tmp_path / "pre_i18n.db")
    with closing(_open(db_path)) as conn:
        _create_tables(conn)
        for table, column in _I18N_COLUMNS:
            # Table / column names are the module-level literals above; no
            # caller-supplied value reaches this string (SQLite cannot bind an
            # identifier as a parameter — same posture as db.py's ALTERs).
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute(
            "INSERT INTO skill_assets "
            "(id, creator_id, name, description, type, endpoint_url, io_schema, "
            " price_amount, price_currency, price_chain, split_rule, content_hash, "
            " wallet_address, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _LEGACY_ASSET,
        )
        conn.execute(
            "INSERT INTO users (id, name, role, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("li_boss", "李老板", "enterprise", "x$y", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    return db_path


def _columns(db_path, table):
    with closing(sqlite3.connect(db_path)) as conn:
        return {row[1]: row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


class TestMigration:
    def test_pre_migration_schema_really_lacks_the_columns(self, pre_i18n_db):
        assert "name_en" not in _columns(pre_i18n_db, "skill_assets")
        assert "description_en" not in _columns(pre_i18n_db, "skill_assets")
        assert "name_en" not in _columns(pre_i18n_db, "users")

    def test_migrate_adds_all_three_columns(self, pre_i18n_db):
        with closing(_open(pre_i18n_db)) as conn:
            _migrate(conn)
        assert "name_en" in _columns(pre_i18n_db, "skill_assets")
        assert "description_en" in _columns(pre_i18n_db, "skill_assets")
        assert "name_en" in _columns(pre_i18n_db, "users")

    def test_the_new_columns_are_nullable_with_no_default(self, pre_i18n_db):
        with closing(_open(pre_i18n_db)) as conn:
            _migrate(conn)
        for table, column in (
            ("skill_assets", "name_en"),
            ("skill_assets", "description_en"),
            ("users", "name_en"),
        ):
            info = _columns(table=table, db_path=pre_i18n_db)[column]
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            assert info[2] == "TEXT"
            assert info[3] == 0, f"{table}.{column} must be nullable"
            assert info[4] is None, f"{table}.{column} must have no SQL default"

    def test_existing_rows_survive_with_null_english_text(self, pre_i18n_db):
        with closing(_open(pre_i18n_db)) as conn:
            _migrate(conn)
        with closing(sqlite3.connect(pre_i18n_db)) as conn:
            conn.row_factory = sqlite3.Row
            asset = dict(conn.execute("SELECT * FROM skill_assets").fetchone())
            user = dict(conn.execute("SELECT * FROM users").fetchone())
        assert asset["name"] == "遗留资产"
        assert asset["content_hash"] == "a" * 64
        assert asset["name_en"] is None
        assert asset["description_en"] is None
        assert user["name"] == "李老板"
        assert user["name_en"] is None

    def test_migrate_is_idempotent(self, pre_i18n_db):
        with closing(_open(pre_i18n_db)) as conn:
            _migrate(conn)
            _migrate(conn)
            _migrate(conn)
        assert "name_en" in _columns(pre_i18n_db, "skill_assets")

    def test_seed_backfills_name_en_onto_a_pre_existing_user_row(self, pre_i18n_db):
        """The li_boss row already existed with name_en NULL; a boot fills it."""
        with closing(_open(pre_i18n_db)) as conn:
            _create_tables(conn)
            _migrate(conn)
            _seed_demo_users(conn)
        with closing(sqlite3.connect(pre_i18n_db)) as conn:
            conn.row_factory = sqlite3.Row
            row = dict(conn.execute("SELECT * FROM users WHERE id = 'li_boss'").fetchone())
        assert row["name"] == "李老板", "the Chinese name must not be overwritten"
        assert row["name_en"] == "Boss Li"

    def test_seed_does_not_overwrite_an_existing_name_en(self, pre_i18n_db):
        with closing(_open(pre_i18n_db)) as conn:
            _create_tables(conn)
            _migrate(conn)
            conn.execute("UPDATE users SET name_en = 'Custom' WHERE id = 'li_boss'")
            conn.commit()
            _seed_demo_users(conn)
        with closing(sqlite3.connect(pre_i18n_db)) as conn:
            row = conn.execute("SELECT name_en FROM users WHERE id = 'li_boss'").fetchone()
        assert row[0] == "Custom"

    def test_seed_demo_users_name_en_matches_demo_identities(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        with closing(_open(db_path)) as conn:
            _create_tables(conn)
            _migrate(conn)
            _seed_demo_users(conn)
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM users").fetchall()}
        for uid, identity in DEMO_IDENTITIES.items():
            assert rows[uid]["name_en"] == identity["name"]["en"], uid
            assert rows[uid]["name"] == identity["name"]["zh"], uid


@pytest.fixture
def bootstrap_db(tmp_path):
    db_path = str(tmp_path / "bootstrap.db")
    with closing(_open(db_path)) as conn:
        _create_tables(conn)
        _migrate(conn)
        _seed_demo_users(conn)
    return db_path


def _assets(db_path):
    return list_skill_assets(db_path)


class TestBootstrapIdempotency:
    """The duplicate-row risk: if `name_en` entered `content_hash` or the
    `expected` equality match, every already-deployed row would stop matching
    and a second copy would be inserted on the next boot."""

    def test_job_design_bootstrap_twice_is_one_row(self, bootstrap_db):
        first = bootstrap_job_design_asset(bootstrap_db, "phase1_stub_creator")
        second = bootstrap_job_design_asset(bootstrap_db, "phase1_stub_creator")
        assert first == second
        assert len(_assets(bootstrap_db)) == 1

    def test_demo_bootstraps_twice_are_stable(self, bootstrap_db):
        ids_first = [
            bootstrap_job_design_asset(bootstrap_db, "phase1_stub_creator"),
            bootstrap_demo_data_analyst_asset(bootstrap_db),
            *bootstrap_demo_extra_assets(bootstrap_db),
        ]
        count_after_first = len(_assets(bootstrap_db))
        ids_second = [
            bootstrap_job_design_asset(bootstrap_db, "phase1_stub_creator"),
            bootstrap_demo_data_analyst_asset(bootstrap_db),
            *bootstrap_demo_extra_assets(bootstrap_db),
        ]
        assert ids_first == ids_second
        assert len(_assets(bootstrap_db)) == count_after_first == 3

    def test_content_hash_is_unchanged_by_the_english_text(self, bootstrap_db):
        """The provenance red line (CLAUDE.md TIER 1 §2): content_hash covers
        name/description/type/io_schema/endpoint_url only."""
        asset_id = bootstrap_demo_data_analyst_asset(bootstrap_db)
        row = next(a for a in _assets(bootstrap_db) if a["id"] == asset_id)
        assert row["content_hash"] == compute_content_hash(
            name=DEMO_DATA_ANALYST["name"],
            description=DEMO_DATA_ANALYST["description"],
            asset_type=DEMO_DATA_ANALYST["type"],
            io_schema=DEMO_DATA_ANALYST["io_schema"],
            endpoint_url=DEMO_DATA_ANALYST.get("endpoint_url"),
        )
        assert row["name_en"] == DISPLAY_EN_BY_NAME["数据分析助手"]["name"]

    def test_a_legacy_row_with_null_name_en_is_backfilled_not_duplicated(self, bootstrap_db):
        """Exactly the deployed-Railway case: the row exists from before the
        migration, so name_en is NULL. The next boot must fill it in place."""
        asset_id = bootstrap_demo_data_analyst_asset(bootstrap_db)
        with closing(sqlite3.connect(bootstrap_db)) as conn:
            conn.execute(
                "UPDATE skill_assets SET name_en = NULL, description_en = NULL WHERE id = ?",
                (asset_id,),
            )
            conn.commit()
        again = bootstrap_demo_data_analyst_asset(bootstrap_db)
        assert again == asset_id
        assert len(_assets(bootstrap_db)) == 1
        row = _assets(bootstrap_db)[0]
        assert row["name_en"] == DISPLAY_EN_BY_NAME["数据分析助手"]["name"]
        assert row["description_en"] == DISPLAY_EN_BY_NAME["数据分析助手"]["description"]

    def test_backfill_does_not_touch_the_chinese_columns(self, bootstrap_db):
        asset_id = bootstrap_demo_data_analyst_asset(bootstrap_db)
        bootstrap_demo_data_analyst_asset(bootstrap_db)
        row = next(a for a in _assets(bootstrap_db) if a["id"] == asset_id)
        assert row["name"] == DEMO_DATA_ANALYST["name"]
        assert row["description"] == DEMO_DATA_ANALYST["description"]

    def test_english_bootstrap_text_is_actually_english(self):
        for name, display in DISPLAY_EN_BY_NAME.items():
            assert_no_cjk(display, f"DISPLAY_EN_BY_NAME[{name!r}]")
        assert_no_cjk(JOB_DESIGN_ASSET_EN, "JOB_DESIGN_ASSET_EN")
