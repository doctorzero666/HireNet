"""
Stage 2 / WP-A: AP2-shaped mandate fields on the pact object.

The pact gains `intent` / `amount_cap` / `expires_at` / `payee` /
`content_hash` (plus the `approved_by` / `approval_method` audit pair),
named after Google AP2's mandate vocabulary. These tests pin the *behaviour*
of those fields only — the honesty caveats (no signature, unsigned digest,
statuses unchanged) live in the section comment in app/app.py.

Everything here is additive: tests/test_pact_lifecycle.py must keep passing
untouched, which is what proves the existing contract did not move.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.app import PACT_DEFAULT_TTL_HOURS, _pact_content_hash
from app.storage.pacts import get_pact, update_pact_fields
from app.storage.skill_assets import get_skill_asset


_WALLET = "0x1234567890abcdef1234567890abcdef0000abcd"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create(client, **overrides):
    body = {
        "task_id": "task-mandate-001",
        "agent_name": "客服话术生成器",
        "creator_id": "creator-1",
        "amount": 60,
        "currency": "USD",
    }
    body.update(overrides)
    resp = client.post("/api/pact/create", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _register_asset(client, *, wallet_address=None, name="Mandate Test Agent"):
    """Register a SkillAsset so a pact can bind to a known wallet (or none)."""
    payload = {
        "name": name,
        "description": "Asset under test for pact mandate fields",
        "type": "agent",
        "io_schema": {"input": {"q": "string"}, "output": {"a": "string"}},
        "price_amount": 1000,
        "price_currency": "USD",
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    }
    if wallet_address is not None:
        payload["wallet_address"] = wallet_address
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["skill_id"]


def _past(hours=1):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _future(hours=1):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _db(client):
    """The temp SQLite file behind `client` — where pacts live since WP-G."""
    return client.application.config["DATABASE_PATH"]


def _tamper(client, pact_id, **fields):
    """Mutate a stored pact behind the routes' back (setup only).

    Stage 2 / WP-G moved the pact store from a module-level dict to the
    `pacts` table, so "reach into the store and change a field" is now a DAO
    write. Same intent as before: simulate a stored-state mutation that
    bypassed the create route.
    """
    assert update_pact_fields(_db(client), pact_id, **fields)


def _expire_in_place(client, pact_id):
    """Backdate a stored pact's TTL *and* re-seal its digest.

    Settle checks expiry before integrity, so a naive backdate would still
    return "pact expired" — but the test would then be passing for two
    reasons at once. Re-sealing keeps this test about the TTL alone.
    """
    stored = get_pact(_db(client), pact_id)
    stored["expires_at"] = _past()
    _tamper(
        client, pact_id,
        expires_at=stored["expires_at"],
        content_hash=_pact_content_hash(stored),
    )


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestMandateDefaults:
    def test_intent_generated_from_agent_and_task(self, client):
        pact = _create(client)
        assert pact["intent"] == "Run 客服话术生成器 for task task-mandate-001"

    def test_amount_cap_defaults_to_amount(self, client):
        pact = _create(client, amount=42.5)
        assert pact["amount_cap"] == 42.5
        assert pact["amount"] == 42.5

    def test_expires_at_defaults_to_24h_from_now(self, client):
        before = datetime.now(timezone.utc)
        pact = _create(client)
        after = datetime.now(timezone.utc)

        expires = datetime.fromisoformat(pact["expires_at"])
        assert expires.tzinfo is not None, "expires_at must be timezone-aware UTC"
        assert before + timedelta(hours=PACT_DEFAULT_TTL_HOURS) <= expires
        assert expires <= after + timedelta(hours=PACT_DEFAULT_TTL_HOURS)

    def test_approval_audit_fields_start_null(self, client):
        pact = _create(client)
        assert pact["approved_by"] is None
        assert pact["approval_method"] is None

    def test_content_hash_is_sha256_hex_of_canonical_material_fields(self, client):
        pact = _create(client)
        material = {
            "pact_id": pact["pact_id"],
            "task_id": pact["task_id"],
            "asset_id": pact["asset_id"],
            "amount_cap": pact["amount_cap"],
            "currency": pact["currency"],
            "payee": pact["payee"],
            "expires_at": pact["expires_at"],
        }
        expected = hashlib.sha256(
            json.dumps(
                material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        assert pact["content_hash"] == expected
        assert len(pact["content_hash"]) == 64


# ---------------------------------------------------------------------------
# Client-supplied values
# ---------------------------------------------------------------------------

class TestClientSuppliedMandateFields:
    def test_client_intent_is_kept_verbatim(self, client):
        pact = _create(client, intent="Draft 20 refund replies, tone: apologetic")
        assert pact["intent"] == "Draft 20 refund replies, tone: apologetic"

    def test_blank_intent_falls_back_to_generated_text(self, client):
        pact = _create(client, intent="   ")
        assert pact["intent"] == "Run 客服话术生成器 for task task-mandate-001"

    def test_non_string_intent_is_rejected(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10, "intent": 7,
        })
        assert resp.status_code == 400
        assert "intent" in resp.get_json()["error"]

    def test_client_amount_cap_is_kept(self, client):
        pact = _create(client, amount=10, amount_cap=25)
        assert pact["amount_cap"] == 25
        assert pact["amount"] == 10

    @pytest.mark.parametrize("bad", [0, -1, "abc", True, float("inf")])
    def test_invalid_amount_cap_is_rejected(self, client, bad):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10, "amount_cap": bad,
        })
        assert resp.status_code == 400
        assert "amount_cap" in resp.get_json()["error"]

    def test_client_expires_at_is_kept(self, client):
        stamp = _future(hours=3)
        pact = _create(client, expires_at=stamp)
        assert pact["expires_at"] == stamp

    def test_unparseable_expires_at_is_rejected(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10,
            "expires_at": "next tuesday",
        })
        assert resp.status_code == 400
        assert "expires_at" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# payee resolution
# ---------------------------------------------------------------------------

class TestPayeeResolution:
    def test_payee_is_the_bound_assets_wallet_address(self, client):
        asset_id = _register_asset(client, wallet_address=_WALLET)
        pact = _create(client, asset_id=asset_id)
        assert pact["payee"] == _WALLET

    def test_payee_is_null_when_the_asset_has_no_wallet(self, client):
        asset_id = _register_asset(client)  # no wallet_address registered
        pact = _create(client, asset_id=asset_id)
        assert pact["payee"] is None, "a missing wallet must never be invented"


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

class TestExpiry:
    def test_approve_after_expiry_is_409(self, client):
        pact = _create(client, expires_at=_past())
        resp = client.post(f"/api/pact/approve/{pact['pact_id']}")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "pact expired"}

    def test_expired_pact_stays_pending_after_a_refused_approve(self, client):
        pact = _create(client, expires_at=_past())
        client.post(f"/api/pact/approve/{pact['pact_id']}")
        status = client.get(f"/api/pact/status/{pact['pact_id']}").get_json()
        assert status["status"] == "pending"
        assert status["approved_by"] is None

    def test_settle_after_expiry_is_409(self, client):
        pact = _create(client)
        pact_id = pact["pact_id"]
        assert client.post(f"/api/pact/approve/{pact_id}").status_code == 200
        _expire_in_place(client, pact_id)

        resp = client.post(f"/api/pact/settle/{pact_id}")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "pact expired"}

    def test_refused_settle_leaves_the_pact_approved_and_unbilled(self, client):
        pact = _create(client)
        pact_id = pact["pact_id"]
        client.post(f"/api/pact/approve/{pact_id}")
        _expire_in_place(client, pact_id)
        client.post(f"/api/pact/settle/{pact_id}")

        status = client.get(f"/api/pact/status/{pact_id}").get_json()
        assert status["status"] == "approved"
        assert "run_id" not in status


# ---------------------------------------------------------------------------
# Spend cap
# ---------------------------------------------------------------------------

class TestAmountCap:
    def test_settle_over_the_cap_is_409(self, client):
        pact = _create(client, amount=60, amount_cap=10)
        pact_id = pact["pact_id"]
        assert client.post(f"/api/pact/approve/{pact_id}").status_code == 200

        resp = client.post(f"/api/pact/settle/{pact_id}")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "amount exceeds cap"}

    def test_settle_exactly_at_the_cap_succeeds(self, client):
        pact = _create(client, amount=60, amount_cap=60)
        pact_id = pact["pact_id"]
        client.post(f"/api/pact/approve/{pact_id}")
        resp = client.post(f"/api/pact/settle/{pact_id}")
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["status"] == "settled"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

class TestContentHashIntegrity:
    def test_tampering_with_a_hashed_field_fails_settle(self, client):
        pact = _create(client)
        pact_id = pact["pact_id"]
        client.post(f"/api/pact/approve/{pact_id}")

        # Simulate a stored-state mutation that bypassed the create route.
        _tamper(client, pact_id, payee="0x000000000000000000000000000000000000dead")

        resp = client.post(f"/api/pact/settle/{pact_id}")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "pact integrity check failed"}

    def test_tampering_with_the_cap_fails_settle(self, client):
        pact = _create(client, amount=10)
        pact_id = pact["pact_id"]
        client.post(f"/api/pact/approve/{pact_id}")
        _tamper(client, pact_id, amount_cap=10_000)

        resp = client.post(f"/api/pact/settle/{pact_id}")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "pact integrity check failed"}

    def test_untampered_pact_settles(self, client):
        pact = _create(client)
        pact_id = pact["pact_id"]
        client.post(f"/api/pact/approve/{pact_id}")
        resp = client.post(f"/api/pact/settle/{pact_id}")
        assert resp.status_code == 200, resp.get_json()

    def test_content_hash_is_stable_for_identical_material_fields(self):
        material = {
            "pact_id": "pact-abc123",
            "task_id": "task-1",
            "asset_id": "asset-1",
            "amount_cap": 60.0,
            "currency": "USD",
            "payee": _WALLET,
            "expires_at": "2026-09-05T00:00:00+00:00",
        }
        # Same values, different insertion order, plus fields outside the
        # hashed set: the digest must not move.
        shuffled = {k: material[k] for k in reversed(list(material))}
        shuffled["status"] = "approved"
        shuffled["amount"] = 59.0

        assert _pact_content_hash(material) == _pact_content_hash(shuffled)

    def test_content_hash_changes_when_a_hashed_field_changes(self):
        base = {
            "pact_id": "pact-abc123", "task_id": "task-1", "asset_id": "asset-1",
            "amount_cap": 60.0, "currency": "USD", "payee": None,
            "expires_at": "2026-09-05T00:00:00+00:00",
        }
        moved = dict(base, amount_cap=61.0)
        assert _pact_content_hash(base) != _pact_content_hash(moved)

    def test_two_pacts_created_from_the_same_body_hash_differently(self, client):
        """pact_id is inside the digest, so two otherwise-identical mandates
        cannot be swapped for one another."""
        stamp = _future(hours=5)
        a = _create(client, expires_at=stamp)
        b = _create(client, expires_at=stamp)
        assert a["content_hash"] != b["content_hash"]


# ---------------------------------------------------------------------------
# Approval audit trail
# ---------------------------------------------------------------------------

class TestApprovalAudit:
    def test_approve_records_who_and_how(self, client):
        pact = _create(client)
        resp = client.post(f"/api/pact/approve/{pact['pact_id']}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["approval_method"] == "ui"
        assert body["approved_by"] == client.application.config["PHASE1_CALLER_ID"]

    def test_approved_by_follows_the_demo_identity_header(self, client):
        pact = _create(client)
        resp = client.post(
            f"/api/pact/approve/{pact['pact_id']}",
            headers={"X-Demo-Identity": "zhang_ai"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["approved_by"] == "zhang_ai"

    def test_no_ap2_credential_field_names_are_claimed(self, client):
        """AP2 reserves user_authorization / merchant_authorization for signed
        JWT / verifiable-presentation values. HireNet has neither."""
        pact = _create(client)
        assert "user_authorization" not in pact
        assert "merchant_authorization" not in pact


# ---------------------------------------------------------------------------
# Status route surface
# ---------------------------------------------------------------------------

class TestStatusIncludesMandate:
    def test_status_returns_every_mandate_field(self, client):
        asset_id = _register_asset(client, wallet_address=_WALLET)
        pact = _create(client, asset_id=asset_id)
        status = client.get(f"/api/pact/status/{pact['pact_id']}").get_json()

        for field in (
            "intent", "amount_cap", "expires_at", "payee", "content_hash",
            "approved_by", "approval_method",
        ):
            assert field in status, f"{field} missing from /api/pact/status"
        assert status["payee"] == _WALLET
        assert status["content_hash"] == pact["content_hash"]

    def test_existing_status_keys_are_untouched(self, client):
        pact = _create(client)
        status = client.get(f"/api/pact/status/{pact['pact_id']}").get_json()
        for field in (
            "pact_id", "status", "task_id", "agent_name", "creator_id",
            "asset_id", "amount", "currency", "created_at", "approved_at",
        ):
            assert field in status


# ---------------------------------------------------------------------------
# payee comes from the DB, not from the request
# ---------------------------------------------------------------------------

def test_payee_on_the_default_asset_path_matches_the_stored_row(client, app_db_path):
    """With no asset_id supplied the pact binds to JOB_DESIGN_ASSET_ID; payee
    must equal whatever that row actually stores (including NULL) — the value
    is read from skill_assets, never taken from the request."""
    pact = _create(client)
    asset = get_skill_asset(app_db_path, pact["asset_id"])
    assert asset is not None
    assert pact["payee"] == asset["wallet_address"]


def test_payee_ignores_a_client_supplied_value(client):
    """A caller cannot redirect the money by putting `payee` in the body."""
    asset_id = _register_asset(client, wallet_address=_WALLET)
    pact = _create(
        client,
        asset_id=asset_id,
        payee="0x000000000000000000000000000000000000dead",
    )
    assert pact["payee"] == _WALLET
