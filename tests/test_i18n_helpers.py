"""
WP-I18N-2 — the two helpers every localised route is built on.

`resolve_request_lang` is the single place a route learns which language the
caller asked for; `pick` / `localize` are the single place a
`{"zh": ..., "en": ...}` seed literal turns back into one string. Both have
the same red line: with no `lang` anywhere they must produce exactly what the
pre-i18n code produced (Chinese), because `tests/test_prompts.py` and
`tests/test_i18n_lang_param.py` pin the v1 wire format on that assumption.

No Flask app is created here — `resolve_request_lang` only needs a request
context, which `flask.Flask.test_request_context` gives us without booting
the real app (and therefore without the DB / bootstrap machinery).
"""
import pytest
from flask import Flask, request

from app.agents.lang_support import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    is_bilingual,
    localize,
    normalize_lang,
    pick,
    resolve_request_lang,
)

app = Flask(__name__)


def resolve(path="/", session_lang=None, **kwargs):
    with app.test_request_context(path, **kwargs):
        return resolve_request_lang(request, session_lang)


# ─── resolve_request_lang ─────────────────────────────────────────────────────


class TestResolveRequestLangQueryParam:
    def test_get_with_lang_en(self):
        assert resolve("/api/jobs?lang=en") == "en"

    def test_get_with_lang_zh(self):
        assert resolve("/api/jobs?lang=zh") == "zh"

    def test_get_without_lang_defaults_to_zh(self):
        assert resolve("/api/jobs") == DEFAULT_LANG == "zh"

    def test_unsupported_query_lang_is_none_so_the_route_can_400(self):
        assert resolve("/api/jobs?lang=fr") is None

    def test_empty_query_lang_falls_through_to_the_default(self):
        assert resolve("/api/jobs?lang=") == DEFAULT_LANG


class TestResolveRequestLangBody:
    def test_post_body_lang(self):
        assert resolve("/api/apply", json={"lang": "en"}) == "en"

    def test_post_body_without_lang_defaults_to_zh(self):
        assert resolve("/api/apply", json={"candidate_id": "candidate_a"}) == "zh"

    def test_unsupported_body_lang_is_none(self):
        assert resolve("/api/apply", json={"lang": "de"}) is None

    def test_non_dict_body_is_ignored(self):
        assert resolve("/api/apply", json=["not", "a", "dict"]) == DEFAULT_LANG

    def test_unparseable_body_is_ignored_not_raised(self):
        assert resolve(
            "/api/apply", data="}{ not json", content_type="application/json"
        ) == DEFAULT_LANG

    def test_query_wins_over_body(self):
        """A GET-style flag on a POST URL beats the body — one rule, both verbs."""
        assert resolve("/api/apply?lang=en", json={"lang": "zh"}) == "en"


class TestResolveRequestLangSession:
    def test_session_lang_is_used_when_the_request_says_nothing(self):
        assert resolve("/api/analyze/decide", session_lang="en") == "en"

    def test_request_lang_beats_the_session(self):
        assert resolve("/api/analyze/decide?lang=zh", session_lang="en") == "zh"

    def test_no_request_and_no_session_is_the_default(self):
        assert resolve("/api/analyze/decide", session_lang=None) == DEFAULT_LANG

    def test_matches_normalize_lang_for_every_supported_value(self):
        for value in SUPPORTED_LANGS:
            assert resolve(f"/x?lang={value}") == normalize_lang(value)


# ─── is_bilingual / pick ──────────────────────────────────────────────────────


class TestIsBilingual:
    @pytest.mark.parametrize("value", [
        {"zh": "张伟", "en": "Wei Zhang"},
        {"zh": ["需求分析"], "en": ["Requirements analysis"]},
        {"zh": "只有中文"},
    ])
    def test_true(self, value):
        assert is_bilingual(value) is True

    @pytest.mark.parametrize("value", [
        {},                                   # empty dict is NOT a seed node
        {"en": "English only"},               # zh is the required side
        {"zh": "a", "en": "b", "fr": "c"},    # extra language key
        {"zh": "a", "id": "candidate_a"},     # a real payload dict
        "plain string",
        ["a", "list"],
        None,
        42,
    ])
    def test_false(self, value):
        assert is_bilingual(value) is False


class TestPick:
    NAME = {"zh": "张伟（全栈工程师）", "en": "Wei Zhang (Full-stack Engineer)"}

    def test_en(self):
        assert pick(self.NAME, "en") == "Wei Zhang (Full-stack Engineer)"

    def test_zh(self):
        assert pick(self.NAME, "zh") == "张伟（全栈工程师）"

    def test_lang_absent_is_the_chinese_side(self):
        """The v1 red line: no lang == exactly today's Chinese output."""
        assert pick(self.NAME) == "张伟（全栈工程师）"
        assert pick(self.NAME, None) == "张伟（全栈工程师）"

    def test_unknown_lang_falls_back_to_chinese(self):
        assert pick(self.NAME, "fr") == "张伟（全栈工程师）"

    def test_missing_en_side_falls_back_to_chinese(self):
        assert pick({"zh": "只有中文"}, "en") == "只有中文"

    @pytest.mark.parametrize("value", ["plain", ["a"], 7, None, {"id": "x"}])
    def test_non_seed_values_pass_through_unchanged(self, value):
        assert pick(value, "en") is value

    def test_a_bilingual_list_resolves_to_the_right_list(self):
        skills = {"zh": ["需求分析", "PRD写作"], "en": ["Requirements analysis", "PRD writing"]}
        assert pick(skills, "en") == ["Requirements analysis", "PRD writing"]


# ─── localize ─────────────────────────────────────────────────────────────────


NESTED = {
    "id": "candidate_b",
    "name": {"zh": "李娜", "en": "Na Li"},
    "skills": {"zh": ["需求分析"], "en": ["Requirements analysis"]},
    "jobs": [
        {"title": {"zh": "产品经理", "en": "Product Manager"}, "job_id": "demo_job_2"},
    ],
    "profile_completeness": 80,
    "raw_memories": [],
}


class TestLocalize:
    def test_en_resolves_every_node(self):
        out = localize(NESTED, "en")
        assert out == {
            "id": "candidate_b",
            "name": "Na Li",
            "skills": ["Requirements analysis"],
            "jobs": [{"title": "Product Manager", "job_id": "demo_job_2"}],
            "profile_completeness": 80,
            "raw_memories": [],
        }

    def test_lang_absent_reproduces_the_pre_i18n_chinese_structure(self):
        assert localize(NESTED) == {
            "id": "candidate_b",
            "name": "李娜",
            "skills": ["需求分析"],
            "jobs": [{"title": "产品经理", "job_id": "demo_job_2"}],
            "profile_completeness": 80,
            "raw_memories": [],
        }

    def test_ids_and_keys_are_untouched(self):
        out = localize(NESTED, "en")
        assert set(out) == set(NESTED)
        assert out["id"] == NESTED["id"]
        assert out["jobs"][0]["job_id"] == "demo_job_2"

    def test_the_source_literal_is_never_mutated(self):
        """Seed dicts are module-level constants shared by every request."""
        localize(NESTED, "en")
        localize(NESTED, "zh")
        assert NESTED["name"] == {"zh": "李娜", "en": "Na Li"}
        assert NESTED["jobs"][0]["title"] == {"zh": "产品经理", "en": "Product Manager"}

    def test_nested_bilingual_inside_a_bilingual_branch_also_resolves(self):
        value = {
            "zh": {"label": {"zh": "中文", "en": "English"}},
            "en": {"label": {"zh": "中文", "en": "English"}},
        }
        assert localize(value, "en") == {"label": "English"}

    def test_scalars_pass_through(self):
        assert localize(7, "en") == 7
        assert localize(None, "en") is None
        assert localize("plain", "en") == "plain"
