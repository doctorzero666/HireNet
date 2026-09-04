"""
Phase 2 / U6 — JWT minimal auth.

C1 scope: seed users, /api/auth/{login,register,me}. C2 IDOR tests against
/api/creator/earnings land in the next file/commit; this file stays focused on
the auth service + routes themselves.
"""
import json

import pytest

from app.services.auth import (
    create_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.storage.users import create_user, get_user


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────

# Index of the signature character the tamper helper rewrites. Any index other
# than the last one works; 10 is comfortably inside the 43-char base64url
# encoding of a 32-byte HS256 signature.
_TAMPER_INDEX = 10


def tamper_signature(token: str) -> str:
    """Return `token` with exactly one signature byte changed.

    Do NOT tamper the LAST base64url character: a 32-byte HS256 signature
    encodes to 43 chars, and the final char carries only 4 significant bits
    (the remaining 2 are padding). 16 of the 64 base64url characters therefore
    decode to the same 32 bytes, so a "tampered" token verifies successfully
    and the test flakes (~7% of runs). A character in the middle always carries
    6 significant bits, so any different character changes the decoded
    signature and verification must fail deterministically.
    """
    head, mid, sig = token.split(".")
    original = sig[_TAMPER_INDEX]
    replacement = "A" if original != "A" else "B"
    return f"{head}.{mid}.{sig[:_TAMPER_INDEX] + replacement + sig[_TAMPER_INDEX + 1:]}"


# ──────────────────────────────────────────────────────────────────────────────
# hash_password / verify_password
# ──────────────────────────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_roundtrip(self):
        h = hash_password("hunter2")
        assert verify_password("hunter2", h)
        assert not verify_password("hunter3", h)

    def test_hash_format_is_salt_dollar_digest(self):
        h = hash_password("x")
        salt_hex, digest_hex = h.split("$")
        assert len(salt_hex) == 32   # 16 bytes hex
        assert len(digest_hex) == 64  # 32 bytes (sha256) hex

    def test_hash_is_unique_per_call(self):
        # Per-password salt → two hashes for the same password differ.
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        assert verify_password("same", h1)
        assert verify_password("same", h2)

    def test_verify_rejects_malformed_stored(self):
        assert not verify_password("x", "no-dollar-sign")
        assert not verify_password("x", "")
        assert not verify_password("x", "ZZ$ZZ")  # non-hex

    def test_hash_rejects_empty(self):
        with pytest.raises(ValueError):
            hash_password("")


# ──────────────────────────────────────────────────────────────────────────────
# JWT create / verify
# ──────────────────────────────────────────────────────────────────────────────

class TestJWT:
    def test_create_then_verify(self):
        tok = create_token("alice", "creator")
        payload = verify_token(tok)
        assert payload is not None
        assert payload["sub"] == "alice"
        assert payload["role"] == "creator"
        assert "exp" in payload and "iat" in payload

    def test_verify_rejects_garbage(self):
        assert verify_token("not-a-token") is None
        assert verify_token("") is None

    def test_verify_rejects_tampered_signature(self):
        tok = create_token("alice", "creator")
        assert verify_token(tamper_signature(tok)) is None


# ──────────────────────────────────────────────────────────────────────────────
# Demo users seeded on init_db
# ──────────────────────────────────────────────────────────────────────────────

class TestDemoUsersSeeded:
    def test_all_four_present(self, client):
        db = client.application.config["DATABASE_PATH"]
        for uid in ("li_boss", "zhang_ai", "wang_dev", "zhao_design"):
            row = get_user(db, uid)
            assert row is not None, f"{uid} missing"
            assert row["password_hash"]  # non-empty

    def test_roles_match_demo_identities(self, client):
        db = client.application.config["DATABASE_PATH"]
        assert get_user(db, "li_boss")["role"] == "enterprise"
        assert get_user(db, "zhang_ai")["role"] == "creator"
        assert get_user(db, "wang_dev")["role"] == "jobseeker"
        assert get_user(db, "zhao_design")["role"] == "creator"

    def test_seed_is_idempotent(self, client):
        """Re-running init_db must not duplicate / overwrite seed rows."""
        from app.storage.db import init_db
        db = client.application.config["DATABASE_PATH"]
        before = get_user(db, "li_boss")
        init_db(client.application)  # re-run
        after = get_user(db, "li_boss")
        # Same row, same hash — INSERT OR IGNORE protected it.
        assert before == after

    def test_seeded_password_verifies(self, client):
        db = client.application.config["DATABASE_PATH"]
        row = get_user(db, "zhang_ai")
        assert verify_password("demo123", row["password_hash"])


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/auth/login
# ──────────────────────────────────────────────────────────────────────────────

class TestLoginRoute:
    def test_login_success_returns_token_and_user(self, client):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": "zhang_ai", "password": "demo123"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert "token" in body and body["token"]
        assert body["user"] == {"id": "zhang_ai", "name": "张AI", "role": "creator"}

    def test_login_token_decodes_to_correct_sub(self, client):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": "li_boss", "password": "demo123"}),
            content_type="application/json",
        )
        payload = verify_token(resp.get_json()["token"])
        assert payload["sub"] == "li_boss"
        assert payload["role"] == "enterprise"

    def test_login_wrong_password_401(self, client):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": "zhang_ai", "password": "WRONG"}),
            content_type="application/json",
        )
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "Invalid credentials"}

    def test_login_unknown_user_401(self, client):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": "ghost", "password": "anything"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_login_missing_fields_400(self, client):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": "x"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_login_rejects_non_json_415(self, client):
        resp = client.post(
            "/api/auth/login",
            data="user_id=zhang_ai&password=demo123",
            content_type="application/x-www-form-urlencoded",
        )
        assert resp.status_code == 415


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/auth/register
# ──────────────────────────────────────────────────────────────────────────────

class TestRegisterRoute:
    def test_register_new_user_returns_token(self, client):
        resp = client.post(
            "/api/auth/register",
            data=json.dumps({
                "user_id": "new_creator",
                "name": "New Creator",
                "role": "creator",
                "password": "strongpw",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["user"]["id"] == "new_creator"
        assert verify_token(body["token"])["sub"] == "new_creator"

    def test_register_duplicate_id_400(self, client):
        resp = client.post(
            "/api/auth/register",
            data=json.dumps({
                "user_id": "zhang_ai",  # already seeded
                "name": "x",
                "role": "creator",
                "password": "strongpw",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "already exists" in resp.get_json()["error"]

    def test_register_invalid_role_400(self, client):
        resp = client.post(
            "/api/auth/register",
            data=json.dumps({
                "user_id": "x",
                "name": "x",
                "role": "admin",  # not in ALLOWED_ROLES
                "password": "strongpw",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_register_short_password_400(self, client):
        resp = client.post(
            "/api/auth/register",
            data=json.dumps({
                "user_id": "x",
                "name": "x",
                "role": "creator",
                "password": "12345",  # < 6
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_register_missing_field_400(self, client):
        resp = client.post(
            "/api/auth/register",
            data=json.dumps({"user_id": "x", "name": "x", "role": "creator"}),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 / U6 fix: phase1 stub identities are system-reserved
# ──────────────────────────────────────────────────────────────────────────────
#
# phase1_stub_creator / phase1_stub_employer own pre-existing royalty rows.
# They must be seeded as unloginable users AND blocked from registration so
# an attacker can't grab the id and inherit historical earnings via JWT.

class TestReservedStubIdentities:
    def test_stub_users_are_seeded(self, client):
        db = client.application.config["DATABASE_PATH"]
        for uid in ("phase1_stub_creator", "phase1_stub_employer"):
            row = get_user(db, uid)
            assert row is not None, f"{uid} should be seeded"

    def test_stub_login_is_rejected(self, client):
        """Sentinel password_hash must never verify. Any password → 401."""
        for uid in ("phase1_stub_creator", "phase1_stub_employer"):
            resp = client.post(
                "/api/auth/login",
                data=json.dumps({"user_id": uid, "password": "demo123"}),
                content_type="application/json",
            )
            assert resp.status_code == 401, (
                f"stub {uid} should not be loginable; got {resp.status_code}"
            )

    def test_stub_register_is_rejected_with_reserved_message(self, client):
        """auth_register returns 400 'reserved' before hitting the DB."""
        for uid in ("phase1_stub_creator", "phase1_stub_employer"):
            resp = client.post(
                "/api/auth/register",
                data=json.dumps({
                    "user_id": uid, "name": "Attacker",
                    "role": "creator", "password": "strongpw",
                }),
                content_type="application/json",
            )
            assert resp.status_code == 400
            assert "reserved" in resp.get_json()["error"]

    def test_dao_create_user_rejects_reserved_ids(self, client):
        """Even bypassing the route, the DAO refuses the reserved ids."""
        db = client.application.config["DATABASE_PATH"]
        with pytest.raises(ValueError, match="reserved"):
            create_user(
                db, "phase1_stub_creator", "x", "creator", hash_password("pw1234"),
            )


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/auth/me
# ──────────────────────────────────────────────────────────────────────────────

class TestMeRoute:
    def _login(self, client, user_id="zhang_ai"):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": user_id, "password": "demo123"}),
            content_type="application/json",
        )
        return resp.get_json()["token"]

    def test_me_with_valid_token(self, client):
        token = self._login(client)
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["user"] == {
            "id": "zhang_ai", "name": "张AI", "role": "creator",
        }

    def test_me_without_token_401(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "Authentication required"}

    def test_me_with_garbage_token_401(self, client):
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_me_with_tampered_signature_401(self, client):
        token = self._login(client)
        bad = tamper_signature(token)
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {bad}"},
        )
        assert resp.status_code == 401

    def test_me_for_deleted_user_401(self, client):
        """Token was valid when issued but the user has since vanished."""
        token = create_token("ghost_only_in_token", "creator")
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "User no longer exists"

    def test_me_wrong_auth_scheme_401(self, client):
        token = self._login(client)
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Basic {token}"},
        )
        assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# DAO users.create_user
# ──────────────────────────────────────────────────────────────────────────────

class TestUserDAO:
    def test_create_user_roundtrip(self, client):
        db = client.application.config["DATABASE_PATH"]
        user = create_user(db, "dao_user", "DAO Test", "creator",
                           hash_password("pw1234"))
        assert user["id"] == "dao_user"
        assert get_user(db, "dao_user")["name"] == "DAO Test"

    def test_create_user_rejects_bad_role(self, client):
        db = client.application.config["DATABASE_PATH"]
        with pytest.raises(ValueError):
            create_user(db, "x", "X", "godmode", hash_password("pw"))

    def test_create_user_rejects_duplicate(self, client):
        db = client.application.config["DATABASE_PATH"]
        with pytest.raises(ValueError):
            create_user(db, "zhang_ai", "x", "creator", hash_password("pw"))

    def test_get_user_returns_none_for_unknown(self, client):
        db = client.application.config["DATABASE_PATH"]
        assert get_user(db, "no_such_user_at_all") is None


# ──────────────────────────────────────────────────────────────────────────────
# C2: get_current_identity prefers JWT over demo header/cookie — closes IDOR
# ──────────────────────────────────────────────────────────────────────────────
#
# Strategy: seed two creators with completely different (currency, chain,
# amount) ledger rows so any cross-bleed is loud. Hit /creator/earnings as
# zhang_ai (JWT), assert zhang_ai's numbers render and zhao_design's never
# leak — even when X-Demo-Identity tries to spoof zhao_design.

from app.services.agent_run_recording import record_agent_run
from app.services.skill_registration import register_skill_asset


def _register_asset_for(db_path, creator_id, *, currency="USD", chain=None,
                        split=(7000, 3000), name="Asset"):
    payload = {
        "name": name,
        "description": f"desc {name}",
        "type": "skill",
        "io_schema": {"input": {"text": "string"}, "output": {"r": "string"}},
        "price_amount": 100,
        "price_currency": currency,
        "split_rule": {"creator": split[0], "platform": split[1]},
    }
    if chain is not None:
        payload["price_chain"] = chain
    return register_skill_asset(db_path, payload, creator_id)["skill_id"]


def _bill(db_path, asset_id, *, charge_amount=100, currency="USD", chain=None):
    kw = dict(agent_name="A", caller_id="c1", task_id="t1", asset_id=asset_id,
              charge_amount=charge_amount, charge_currency=currency, success=True)
    if chain is not None:
        kw["charge_chain"] = chain
    record_agent_run(db_path, **kw)


class TestEarningsIDORWithJWT:
    @pytest.fixture(autouse=True)
    def _seed_earnings(self, client):
        """Two creators, very different ledger fingerprints."""
        db = client.application.config["DATABASE_PATH"]
        # zhang_ai — USD no chain, 3 × 100 with 70/30 split → 210 USD accrued
        a1 = _register_asset_for(db, "zhang_ai", currency="USD",
                                 split=(7000, 3000), name="Zhang USD")
        for _ in range(3):
            _bill(db, a1, charge_amount=100, currency="USD")
        # zhao_design — EUR on ethereum, 1 × 1234 with 50/50 → 617 EUR ethereum
        a2 = _register_asset_for(db, "zhao_design", currency="EUR",
                                 chain="ethereum", split=(5000, 5000),
                                 name="Zhao EUR ETH")
        _bill(db, a2, charge_amount=1234, currency="EUR", chain="ethereum")

    def _login(self, client, user_id):
        resp = client.post(
            "/api/auth/login",
            data=json.dumps({"user_id": user_id, "password": "demo123"}),
            content_type="application/json",
        )
        return resp.get_json()["token"]

    def test_jwt_zhang_ai_sees_only_own_earnings_html(self, client):
        token = self._login(client, "zhang_ai")
        resp = client.get(
            "/creator/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # zhang_ai's data MUST render
        assert "zhang_ai" in body
        assert "210" in body, "zhang_ai's 210 USD accrued total missing"
        assert "ACCRUED USD" in body
        # zhao_design's data MUST NOT leak — same IDOR guard as U5
        assert "zhao_design" not in body
        assert "617" not in body, "IDOR: zhao_design's amount leaked into zhang_ai page"
        assert "EUR" not in body, "IDOR: zhao_design's currency leaked"
        assert "ethereum" not in body, "IDOR: zhao_design's chain leaked"

    def test_jwt_zhang_ai_sees_only_own_earnings_json(self, client):
        token = self._login(client, "zhang_ai")
        resp = client.get(
            "/api/creator/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["creator_id"] == "zhang_ai"
        assert body["call_count"] == 3
        assert body["totals_by_currency"] == [
            {"currency": "USD", "chain": None, "amount": 210},
        ]

    def test_jwt_zhao_design_sees_only_own_earnings(self, client):
        token = self._login(client, "zhao_design")
        resp = client.get(
            "/api/creator/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = resp.get_json()
        assert body["creator_id"] == "zhao_design"
        assert body["call_count"] == 1
        assert body["totals_by_currency"] == [
            {"currency": "EUR", "chain": "ethereum", "amount": 617},
        ]

    def test_jwt_overrides_demo_header_spoof_attempt(self, client):
        """JWT zhang_ai + X-Demo-Identity: zhao_design — JWT must win."""
        token = self._login(client, "zhang_ai")
        resp = client.get(
            "/api/creator/earnings",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Demo-Identity": "zhao_design",  # spoof attempt
            },
        )
        body = resp.get_json()
        # Server-derived JWT identity wins — header is ignored
        assert body["creator_id"] == "zhang_ai", \
            "IDOR: X-Demo-Identity header was honored over JWT"
        assert body["call_count"] == 3
        # zhao_design's EUR row must NOT appear in zhang_ai's totals
        assert all(t["currency"] != "EUR" for t in body["totals_by_currency"])

    def test_jwt_overrides_demo_cookie_spoof_attempt(self, client):
        """JWT zhang_ai + demo_identity cookie zhao_design — JWT must win."""
        token = self._login(client, "zhang_ai")
        client.set_cookie("demo_identity", "zhao_design")
        resp = client.get(
            "/api/creator/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = resp.get_json()
        assert body["creator_id"] == "zhang_ai"

    def test_jwt_pointing_at_deleted_user_falls_back_to_demo(self, client):
        """Stale token whose sub doesn't exist must NOT 500; falls through."""
        from app.services.auth import create_token
        token = create_token("vanished_user", "creator")
        # With no demo cookie / header, falls to PHASE1_CREATOR_ID stub.
        resp = client.get(
            "/api/creator/earnings",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        # Must be the stub, not "vanished_user" (no fabrication from token alone)
        assert body["creator_id"] == client.application.config["PHASE1_CREATOR_ID"]
        assert body["creator_id"] != "vanished_user"

    def test_no_token_demo_cookie_still_works(self, client):
        """Backward compat: without JWT, demo cookie still routes identity."""
        client.set_cookie("demo_identity", "zhao_design")
        resp = client.get("/api/creator/earnings")
        body = resp.get_json()
        # No JWT — demo cookie picks zhao_design
        assert body["creator_id"] == "zhao_design"
        assert body["call_count"] == 1
