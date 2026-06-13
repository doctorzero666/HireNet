"""
U3 验收测试：注册 SkillAsset 接口（算 content_hash）

判据：
  C-1  注册成功落库，返回 skill_id + content_hash
  C-2  相同内容 → 相同 hash
  C-3  不同内容 → 不同 hash
  C-4  缺必填字段 → 400
  C-5  split_rule 不合法 → 400
  C-6  creator_id 不信任客户端 (Phase 1 stub)
  C-7  type 字段落库、参与 hash、enum 校验
  C-8  非 object JSON → 400
  C-9  price_amount 类型校验 (integer only)
  C-10 fake content_hash 被服务端覆盖
  C-11 未知字段 → 400
  C-12 endpoint 类型注册不发起网络请求 (SSRF 防护)
  C-13 读回记录通过 schema 校验
"""
import json
import os
import re
import socket
import tempfile

import pytest

from app.app import create_app
from app.services.validation import validate
from app.storage.skill_assets import get_skill_asset

_PHASE1_CREATOR = "phase1_stub_creator"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"DATABASE_PATH": db_path, "TESTING": True})
    with app.test_client() as c:
        yield c
    os.unlink(db_path)


@pytest.fixture
def app_and_client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"DATABASE_PATH": db_path, "TESTING": True})
    with app.test_client() as c:
        yield app, c, db_path
    os.unlink(db_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_payload(**overrides) -> dict:
    base = {
        "name": "Resume Parser",
        "description": "Parses a resume and extracts structured data",
        "type": "skill",
        "io_schema": {"input": {"resume_text": "string"}, "output": {"skills": "list"}},
        "price_amount": 100,
        "price_currency": "USD",
        "split_rule": {"creator": 7000, "platform": 3000},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# C-1: Successful registration — returns skill_id + content_hash
# ---------------------------------------------------------------------------

def test_register_returns_skill_id_and_hash(client):
    resp = client.post("/api/skills/register", json=_base_payload())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body.get("skill_id"), "Response must include a non-empty skill_id"
    assert _HEX64.match(body.get("content_hash", "")), \
        "content_hash must be 64-char lowercase hex"


def test_registered_asset_persists_in_db(app_and_client):
    app, c, db_path = app_and_client
    payload = _base_payload()
    resp = c.post("/api/skills/register", json=payload)
    assert resp.status_code == 201
    skill_id = resp.get_json()["skill_id"]

    stored = get_skill_asset(db_path, skill_id)
    assert stored is not None, "Asset not found in DB after registration"
    assert stored["name"] == payload["name"]
    assert stored["description"] == payload["description"]
    assert stored["type"] == payload["type"]
    assert stored["io_schema"] == payload["io_schema"]
    assert stored["price_amount"] == payload["price_amount"]
    assert stored["price_currency"] == payload["price_currency"]
    assert stored["split_rule"] == payload["split_rule"]
    assert _HEX64.match(stored["content_hash"])


def test_register_with_optional_price_chain(client):
    payload = _base_payload(price_chain="ETH")
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# C-2: Same content → same hash
# ---------------------------------------------------------------------------

def test_same_content_same_hash(client):
    payload = _base_payload()
    r1 = client.post("/api/skills/register", json=payload)
    r2 = client.post("/api/skills/register", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] == r2.get_json()["content_hash"]


def test_dict_key_order_does_not_affect_hash(client):
    """io_schema with identical content but different key insertion order → same hash."""
    p1 = _base_payload(io_schema={"a": 1, "b": 2})
    p2 = _base_payload(io_schema={"b": 2, "a": 1})
    r1 = client.post("/api/skills/register", json=p1)
    r2 = client.post("/api/skills/register", json=p2)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] == r2.get_json()["content_hash"]


# ---------------------------------------------------------------------------
# C-3: Different content → different hash
# ---------------------------------------------------------------------------

def test_different_name_different_hash(client):
    r1 = client.post("/api/skills/register", json=_base_payload(name="Skill A"))
    r2 = client.post("/api/skills/register", json=_base_payload(name="Skill B"))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] != r2.get_json()["content_hash"]


def test_different_description_different_hash(client):
    r1 = client.post("/api/skills/register", json=_base_payload(description="Does X"))
    r2 = client.post("/api/skills/register", json=_base_payload(description="Does Y"))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] != r2.get_json()["content_hash"]


def test_different_io_schema_different_hash(client):
    r1 = client.post("/api/skills/register", json=_base_payload(io_schema={"in": "text"}))
    r2 = client.post("/api/skills/register", json=_base_payload(io_schema={"in": "file"}))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] != r2.get_json()["content_hash"]


# ---------------------------------------------------------------------------
# C-4: Missing required field → 400
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", [
    # creator_id is NOT in this list — Phase 1 stub ignores the client value
    "name", "description", "type", "io_schema",
    "price_amount", "price_currency", "split_rule",
])
def test_missing_required_field_returns_400(client, field):
    payload = _base_payload()
    del payload[field]
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# C-5: Invalid split_rule → 400
# ---------------------------------------------------------------------------

def test_split_rule_not_summing_to_10000_returns_400(client):
    payload = _base_payload(split_rule={"creator": 5000, "platform": 4000})
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400


def test_split_rule_exceeding_10000_returns_400(client):
    payload = _base_payload(split_rule={"creator": 8000, "platform": 3000})
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400


def test_no_body_returns_400(client):
    resp = client.post("/api/skills/register", content_type="application/json", data="")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# C-6: creator_id — Phase 1 stub; client value is ignored
# ---------------------------------------------------------------------------

def test_client_creator_id_is_ignored(app_and_client):
    """Server must use the Phase 1 stub, not the value the client supplies."""
    app, c, db_path = app_and_client
    payload = _base_payload(creator_id="evil_attacker")
    resp = c.post("/api/skills/register", json=payload)
    assert resp.status_code == 201
    skill_id = resp.get_json()["skill_id"]

    stored = get_skill_asset(db_path, skill_id)
    # Phase 1 stub: stored creator must be the server-configured stub
    assert stored["creator_id"] == _PHASE1_CREATOR, \
        f"Expected Phase 1 stub creator '{_PHASE1_CREATOR}', got '{stored['creator_id']}'"
    assert stored["creator_id"] != "evil_attacker", \
        "Client-supplied creator_id must NOT be persisted"


def test_register_without_creator_id_uses_stub(app_and_client):
    """Omitting creator_id in payload is fine — server uses the stub."""
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload())
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["creator_id"] == _PHASE1_CREATOR


# ---------------------------------------------------------------------------
# C-7: type field — stored, participates in hash, enum validated
# ---------------------------------------------------------------------------

def test_type_field_stored_in_db(app_and_client):
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload(type="agent"))
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["type"] == "agent"


def test_type_field_affects_hash(client):
    """Same name/description/io_schema but different type → different hash."""
    r1 = client.post("/api/skills/register", json=_base_payload(type="skill"))
    r2 = client.post("/api/skills/register", json=_base_payload(type="agent"))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] != r2.get_json()["content_hash"]


def test_invalid_type_returns_400(client):
    payload = _base_payload(type="magic_bean")
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400


def test_endpoint_type_with_url_stored(app_and_client):
    """endpoint type with endpoint_url is stored but URL is never accessed."""
    app, c, db_path = app_and_client
    payload = _base_payload(type="endpoint", endpoint_url="https://api.example.com/hook")
    resp = c.post("/api/skills/register", json=payload)
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["type"] == "endpoint"
    assert stored["endpoint_url"] == "https://api.example.com/hook"


# ---------------------------------------------------------------------------
# C-8: Non-object JSON body → 400, not 500
# ---------------------------------------------------------------------------

def test_non_object_json_list_returns_400(client):
    resp = client.post(
        "/api/skills/register",
        data=json.dumps([1, 2, 3]),
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body


def test_non_object_json_string_returns_400(client):
    resp = client.post(
        "/api/skills/register",
        data=json.dumps("hello"),
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body


def test_non_object_json_int_returns_400(client):
    resp = client.post(
        "/api/skills/register",
        data=json.dumps(42),
        content_type="application/json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# C-9: price_amount type validation — only plain non-negative integers
# ---------------------------------------------------------------------------

def test_price_amount_float_returns_400(client):
    payload = _base_payload(price_amount=1.5)
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400


def test_price_amount_string_returns_400(client):
    payload = _base_payload()
    # Send raw JSON to force string type
    raw = json.dumps(payload).replace('"price_amount": 100', '"price_amount": "100"')
    resp = client.post("/api/skills/register", data=raw, content_type="application/json")
    assert resp.status_code == 400


def test_price_amount_bool_returns_400(client):
    payload = _base_payload(price_amount=True)
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# C-10: Client-supplied content_hash is ignored; server computes its own
# ---------------------------------------------------------------------------

def test_fake_content_hash_is_ignored(app_and_client):
    """Server must overwrite any client-supplied content_hash with its own computation."""
    app, c, db_path = app_and_client
    fake_hash = "a" * 64
    payload = _base_payload(content_hash=fake_hash)
    resp = c.post("/api/skills/register", json=payload)
    assert resp.status_code == 201
    body = resp.get_json()

    # Response hash must be a real 64-char hex string
    assert _HEX64.match(body["content_hash"]), "Response content_hash must be valid hex"
    # Server must NOT echo back the fake hash
    assert body["content_hash"] != fake_hash, \
        "Server must compute its own hash, not accept the client-supplied one"

    # DB record must also hold the real hash, not the fake one
    stored = get_skill_asset(db_path, body["skill_id"])
    assert stored["content_hash"] != fake_hash
    assert _HEX64.match(stored["content_hash"])


# ---------------------------------------------------------------------------
# C-11: Unknown fields in payload → 400
# ---------------------------------------------------------------------------

def test_unknown_field_returns_400(client):
    payload = _base_payload(surprise_field="boom")
    resp = client.post("/api/skills/register", json=payload)
    assert resp.status_code == 400
    assert "Unknown fields" in resp.get_json().get("error", "")


# ---------------------------------------------------------------------------
# C-12: endpoint type — no network request (SSRF guard)
# ---------------------------------------------------------------------------

def test_endpoint_type_no_network_request(client, monkeypatch):
    """Registering an endpoint asset must never open a network connection."""
    def _no_connect(self, *args, **kwargs):
        raise AssertionError(
            f"SSRF: registration triggered a network connection to {args}"
        )
    monkeypatch.setattr(socket.socket, "connect", _no_connect)

    payload = _base_payload(type="endpoint", endpoint_url="http://evil.example.com/hook")
    resp = client.post("/api/skills/register", json=payload)
    # If we reach here without AssertionError, no network call was attempted
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# C-13: Read-back passes SkillAsset schema validation
# ---------------------------------------------------------------------------

def test_get_skill_asset_passes_schema_validation(app_and_client):
    """The dict returned by get_skill_asset must satisfy the SkillAsset schema."""
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload())
    assert resp.status_code == 201
    skill_id = resp.get_json()["skill_id"]

    stored = get_skill_asset(db_path, skill_id)
    assert stored is not None
    # Must not raise
    validate(stored, "skill_asset")


# ---------------------------------------------------------------------------
# C-14: wallet_address — optional EVM recipient for Sepolia settlement
# ---------------------------------------------------------------------------

_TEST_WALLET = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def test_wallet_address_persists_in_db(app_and_client):
    """A valid EVM address in the payload is stored verbatim on the asset row."""
    app, c, db_path = app_and_client
    payload = _base_payload(wallet_address=_TEST_WALLET)
    resp = c.post("/api/skills/register", json=payload)
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["wallet_address"] == _TEST_WALLET


def test_wallet_address_absent_stored_as_null(app_and_client):
    """Omitting the field stores NULL — the Sepolia provider then falls back
    to SEPOLIA_TO_ADDRESS / self.from_address."""
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload())
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["wallet_address"] is None


def test_wallet_address_empty_string_stored_as_null(app_and_client):
    """Empty string from a half-filled form must normalise to NULL, not pass
    a "" through to the chain (which Web3.is_address would reject at settle)."""
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload(wallet_address=""))
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["wallet_address"] is None


def test_wallet_address_explicit_null_stored_as_null(app_and_client):
    """Explicit JSON null is accepted and stored as NULL."""
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload(wallet_address=None))
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    assert stored["wallet_address"] is None


@pytest.mark.parametrize("bad", [
    "not-an-address",
    "0xdeadbeef",                      # too short
    "70997970C51812dc3A010C7d01b50e0d17dc79C8",  # missing 0x prefix
    "0xZZ997970C51812dc3A010C7d01b50e0d17dc79C8",  # non-hex char
    "0x70997970C51812dc3A010C7d01b50e0d17dc79C8AA",  # too long
])
def test_wallet_address_malformed_returns_400(client, bad):
    """Malformed addresses are rejected at the route layer; a corrupt row
    must never reach the chain."""
    resp = client.post("/api/skills/register", json=_base_payload(wallet_address=bad))
    assert resp.status_code == 400, f"Expected 400 for {bad!r}, got {resp.status_code}"


def test_wallet_address_non_string_returns_400(client):
    """A number / bool / object in wallet_address is a 400, not a 500."""
    resp = client.post(
        "/api/skills/register",
        json=_base_payload(wallet_address=12345),
    )
    assert resp.status_code == 400


def test_wallet_address_not_in_content_hash(client):
    """wallet_address is an economic/operational field, NOT a provenance one.
    Changing it must not invalidate the SkillAsset's content_hash — otherwise
    rotating a key would look like minting a new asset. Same content + diff
    wallet → identical hash."""
    p1 = _base_payload(wallet_address=_TEST_WALLET)
    p2 = _base_payload(wallet_address="0x" + "ab" * 20)  # different valid address
    r1 = client.post("/api/skills/register", json=p1)
    r2 = client.post("/api/skills/register", json=p2)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["content_hash"] == r2.get_json()["content_hash"]


def test_registered_asset_with_wallet_passes_schema_validation(app_and_client):
    """The DB row including wallet_address must satisfy the SkillAsset schema —
    catches a misalignment between schema and DAO."""
    app, c, db_path = app_and_client
    resp = c.post("/api/skills/register", json=_base_payload(wallet_address=_TEST_WALLET))
    assert resp.status_code == 201
    stored = get_skill_asset(db_path, resp.get_json()["skill_id"])
    validate(stored, "skill_asset")  # must not raise
