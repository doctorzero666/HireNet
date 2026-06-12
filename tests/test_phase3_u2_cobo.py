"""
Phase 3 / U2 — CoboSettlementProvider unit tests.

⚠️ These tests stub `requests` at the boundary. They prove:
  - the provider conforms to SettlementProvider's contract;
  - the HTTP request shape (URL, headers, body) matches what Cobo's WaaS 2.0
    docs describe;
  - the Ed25519 signature actually verifies (round-trip with the public key);
  - response → SettlementResult / SettlementStatus mapping is correct;
  - transport / HTTP / JSON failures fail gracefully.

They do NOT prove the wire shape matches Cobo's *running* testnet endpoint.
The author had no testnet creds at implementation time — that handshake
needs one real `cobo transfer` run before any mainnet move.
"""
import json
import time

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.cobo_settlement import CoboSettlementProvider, _COBO_STATE_MAP
from app.services.settlement import SettlementStatus


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeResponse:
    """Minimal `requests.Response`-shaped object for unit tests."""
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class RequestRecorder:
    """Captures every call to provider._request and returns a queued response."""
    def __init__(self, responses):
        # `responses` may be a single FakeResponse, a list (consumed FIFO),
        # or a callable(method, url, **kwargs) → FakeResponse for tests that
        # want to vary by request.
        self.calls = []
        self._responses = responses

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if callable(self._responses):
            return self._responses(method, url, **kwargs)
        if isinstance(self._responses, list):
            return self._responses.pop(0)
        return self._responses


# A syntactically-valid Ed25519 private key (32 bytes / 64 hex chars). Not a
# real Cobo key — purely a fixture so the constructor accepts it.
VALID_SECRET_HEX = "11" * 32


def _make_provider(**overrides):
    base = dict(
        api_key="test-key",
        api_secret=VALID_SECRET_HEX,
        base_url="https://api.cobo.com",
        wallet_id="wallet-test",
    )
    base.update(overrides)
    return CoboSettlementProvider(**base)


# ---------------------------------------------------------------------------
# __init__ validation — every required field must fail loudly
# ---------------------------------------------------------------------------

class TestCoboInitValidation:
    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="COBO_API_KEY is required"):
            _make_provider(api_key="")

    def test_missing_api_secret_raises(self):
        with pytest.raises(ValueError, match="COBO_API_SECRET is required"):
            _make_provider(api_secret="")

    def test_missing_base_url_raises(self):
        with pytest.raises(ValueError, match="COBO_BASE_URL is required"):
            _make_provider(base_url="")

    def test_missing_wallet_id_raises(self):
        with pytest.raises(ValueError, match="COBO_WALLET_ID is required"):
            _make_provider(wallet_id="")

    def test_non_hex_secret_raises(self):
        with pytest.raises(ValueError, match="hex-encoded Ed25519 private key"):
            _make_provider(api_secret="not-hex!")

    def test_wrong_length_secret_raises(self):
        # 30 bytes instead of 32 — Ed25519PrivateKey rejects.
        with pytest.raises(ValueError, match="hex-encoded Ed25519 private key"):
            _make_provider(api_secret="11" * 30)

    def test_trailing_slash_in_base_url_stripped(self):
        p = _make_provider(base_url="https://api.cobo.com/v2/")
        assert p.base_url == "https://api.cobo.com/v2"

    def test_name_attribute_is_cobo(self):
        # Route layer reads provider.name to persist settlement_method on the
        # agent_runs row — regression-guard the literal value.
        assert _make_provider().name == "cobo"


# ---------------------------------------------------------------------------
# Ed25519 signing — verify with the matching public key
# ---------------------------------------------------------------------------

class TestCoboSigning:
    def test_signature_round_trips_with_public_key(self):
        """Signature must verify against the public key derived from our secret."""
        provider = _make_provider()
        headers = provider._sign_request("POST", "/v2/x", "{}")
        # Reconstruct the exact message the provider signed.
        message = (
            f"POST|/v2/x|{headers['Biz-Api-Nonce']}|{headers['Biz-Api-Timestamp']}|"
            "{}"
        )
        public_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(VALID_SECRET_HEX)
        ).public_key()
        # Will raise InvalidSignature on mismatch — silence = success.
        public_key.verify(
            bytes.fromhex(headers["Biz-Api-Signature"]),
            message.encode("utf-8"),
        )

    def test_empty_body_omitted_from_signed_message(self):
        """GET requests sign `method|path|nonce|timestamp` (no trailing |body)."""
        provider = _make_provider()
        headers = provider._sign_request("GET", "/v2/x", "")
        message = (
            f"GET|/v2/x|{headers['Biz-Api-Nonce']}|{headers['Biz-Api-Timestamp']}"
        )
        public_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(VALID_SECRET_HEX)
        ).public_key()
        public_key.verify(
            bytes.fromhex(headers["Biz-Api-Signature"]),
            message.encode("utf-8"),
        )

    def test_nonce_changes_per_request(self):
        provider = _make_provider()
        nonces = {
            provider._sign_request("GET", "/x", "")["Biz-Api-Nonce"]
            for _ in range(10)
        }
        # All 10 calls must yield distinct nonces — replay protection.
        assert len(nonces) == 10

    def test_timestamp_is_recent_millis(self):
        provider = _make_provider()
        before = int(time.time() * 1000)
        headers = provider._sign_request("GET", "/x", "")
        after = int(time.time() * 1000)
        ts = int(headers["Biz-Api-Timestamp"])
        # Timestamp must land between before/after (in milliseconds).
        assert before <= ts <= after

    def test_required_biz_headers_present(self):
        provider = _make_provider()
        headers = provider._sign_request("GET", "/x", "")
        assert set(headers) == {
            "Biz-Api-Key", "Biz-Api-Nonce",
            "Biz-Api-Timestamp", "Biz-Api-Signature",
        }
        assert headers["Biz-Api-Key"] == "test-key"


# ---------------------------------------------------------------------------
# Ed25519 golden fixture — locks the canonical message format
# ---------------------------------------------------------------------------

class TestCoboSigningGolden:
    """Pin the canonical `method|path|nonce|timestamp|body` shape.

    `test_signature_round_trips_with_public_key` only proves the provider
    can verify what it just signed — both sides could quietly drift to a
    different format and the round-trip would still pass. This class hard-
    codes the EXACT message string Cobo's WaaS 2.0 spec says we must sign,
    forces deterministic nonce + timestamp, and checks that the provider's
    Ed25519 output matches an independent signature over that frozen string.

    If anyone changes `_sign_request`'s canonical-form construction (re-orders
    fields, swaps `|` for `:`, normalises case, drops/adds the trailing body
    segment) the provider's signature will diverge from the hard-coded golden
    and these tests fail — even though the round-trip test still passes.
    """

    # Deterministic inputs that make secrets.token_hex(N) → "a" * (2N).
    # Matches the monkeypatch applied below.
    _FIXED_NONCE = "a" * 32          # secrets.token_hex(16)
    _FIXED_REQUEST_ID = "hirenet-" + "a" * 24  # "hirenet-" + secrets.token_hex(12)
    _FIXED_TIMESTAMP = "1700000000000"  # time.time() == 1700000000.0 → ms

    @staticmethod
    def _golden_sig(message: str) -> str:
        """Independent Ed25519 over `message` with the test fixture's key."""
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(VALID_SECRET_HEX))
        return key.sign(message.encode("utf-8")).hex()

    @staticmethod
    def _freeze_randomness(monkeypatch):
        """Force secrets.token_hex → 'a' * 2N and time.time → 1700000000.0.

        Touches the names as bound inside app.services.cobo_settlement so the
        provider's own `secrets.token_hex(...)` / `time.time()` calls hit the
        fake without affecting any other module.
        """
        import app.services.cobo_settlement as cobo_mod
        monkeypatch.setattr(cobo_mod.secrets, "token_hex", lambda n: "a" * (2 * n))
        monkeypatch.setattr(cobo_mod.time, "time", lambda: 1700000000.0)

    def test_get_request_golden_signature(self, monkeypatch):
        """GET signs `method|path|nonce|timestamp` — no trailing body segment."""
        self._freeze_randomness(monkeypatch)
        provider = _make_provider()
        headers = provider._sign_request("GET", "/v2/wallets/wallet-test/transactions/tx1", "")

        expected_message = (
            f"GET|/v2/wallets/wallet-test/transactions/tx1"
            f"|{self._FIXED_NONCE}|{self._FIXED_TIMESTAMP}"
        )
        assert headers["Biz-Api-Nonce"] == self._FIXED_NONCE
        assert headers["Biz-Api-Timestamp"] == self._FIXED_TIMESTAMP
        assert headers["Biz-Api-Signature"] == self._golden_sig(expected_message)

    def test_post_request_golden_signature(self, monkeypatch):
        """POST with body signs `method|path|nonce|timestamp|body`."""
        self._freeze_randomness(monkeypatch)
        provider = _make_provider()
        body = '{"x":1}'
        headers = provider._sign_request("POST", "/v2/test", body)

        expected_message = (
            f"POST|/v2/test|{self._FIXED_NONCE}|{self._FIXED_TIMESTAMP}|{body}"
        )
        assert headers["Biz-Api-Signature"] == self._golden_sig(expected_message)

    def test_settle_golden_signature_end_to_end(self, monkeypatch):
        """Drive the full settle() path; pin the exact body + signature.

        Catches any future drift in the body JSON shape: key order, separators,
        added/removed fields, or amount stringification. If the body bytes
        change, the signature diverges from the hard-coded golden.
        """
        self._freeze_randomness(monkeypatch)
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0xdone"}))
        provider = _make_provider(request_callable=rec)
        provider.settle("0xRecipient", 100, "USDC", "ETH")

        # Golden body: settle() sorts keys, uses compact separators, casts
        # amount to str. If this changes, Cobo rejects the signature.
        expected_body = (
            '{"amount":"100",'
            '"memo":"HireNet royalty payout",'
            f'"request_id":"{self._FIXED_REQUEST_ID}",'
            '"to_address":"0xRecipient",'
            '"token_id":"ETH_USDC"}'
        )
        expected_message = (
            f"POST|/v2/wallets/wallet-test/transactions/transfer"
            f"|{self._FIXED_NONCE}|{self._FIXED_TIMESTAMP}|{expected_body}"
        )

        assert rec.calls[0]["data"] == expected_body
        assert rec.calls[0]["headers"]["Biz-Api-Signature"] == self._golden_sig(
            expected_message,
        )


# ---------------------------------------------------------------------------
# settle() — happy path: URL, body shape, headers, tx_hash extraction
# ---------------------------------------------------------------------------

class TestCoboSettleHappyPath:
    def test_returns_tx_hash_from_response(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0xdeadbeef"}))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xRecipient", 100, "USDC", "ETH")
        assert result.success is True
        assert result.tx_hash == "0xdeadbeef"
        assert result.error is None

    def test_falls_back_to_cobo_id_when_tx_hash_missing(self):
        # Cobo's response for a freshly-submitted tx may not have an on-chain
        # hash yet — only its internal cobo_id. Provider must surface
        # *something* linkable so a later check_status can join back.
        rec = RequestRecorder(FakeResponse(200, {"cobo_id": "cobo-abc"}))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xRecipient", 100, "USDC", "ETH")
        assert result.success is True
        assert result.tx_hash == "cobo-abc"

    def test_falls_back_to_request_id_when_response_empty(self):
        # Truly degenerate: 200 but the body has nothing useful. We echo back
        # our own request_id so the row has a non-empty tx_hash.
        rec = RequestRecorder(FakeResponse(200, {}))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xRecipient", 100, "USDC", "ETH")
        assert result.success is True
        assert result.tx_hash.startswith("hirenet-")

    def test_targets_transfer_url(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        provider.settle("0xRecipient", 100, "USDC", "ETH")
        assert rec.calls[0]["method"] == "POST"
        assert rec.calls[0]["url"] == (
            "https://api.cobo.com/v2/wallets/wallet-test/transactions/transfer"
        )

    def test_signed_headers_present_on_settle(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        provider.settle("0xRecipient", 100, "USDC", "ETH")
        headers = rec.calls[0]["headers"]
        assert "Biz-Api-Key" in headers
        assert "Biz-Api-Nonce" in headers
        assert "Biz-Api-Timestamp" in headers
        assert "Biz-Api-Signature" in headers
        assert headers["Content-Type"] == "application/json"

    def test_body_carries_required_fields(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        provider.settle("0xRecipient", 100, "USDC", "ETH")
        body = json.loads(rec.calls[0]["data"])
        assert body["to_address"] == "0xRecipient"
        assert body["token_id"] == "ETH_USDC"
        assert body["amount"] == "100"  # Cobo wants a string
        assert body["request_id"].startswith("hirenet-")
        assert body["memo"] == "HireNet royalty payout"

    def test_from_address_included_when_set(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(
            request_callable=rec, from_address="0xMyWallet",
        )
        provider.settle("0xRecipient", 100, "USDC", "ETH")
        body = json.loads(rec.calls[0]["data"])
        assert body["from_address"] == "0xMyWallet"

    def test_from_address_omitted_when_unset(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        provider.settle("0xRecipient", 100, "USDC", "ETH")
        body = json.loads(rec.calls[0]["data"])
        assert "from_address" not in body

    def test_signed_body_matches_wire_body_byte_for_byte(self):
        """If the signed body and wire body diverge, Cobo rejects the request."""
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        provider.settle("0xRecipient", 100, "USDC", "ETH")
        wire_body = rec.calls[0]["data"]
        headers = rec.calls[0]["headers"]
        message = (
            f"POST|/v2/wallets/wallet-test/transactions/transfer|"
            f"{headers['Biz-Api-Nonce']}|{headers['Biz-Api-Timestamp']}|{wire_body}"
        )
        public_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(VALID_SECRET_HEX)
        ).public_key()
        public_key.verify(
            bytes.fromhex(headers["Biz-Api-Signature"]),
            message.encode("utf-8"),
        )


# ---------------------------------------------------------------------------
# settle() — error paths: HTTP 4xx/5xx, transport, non-JSON
# ---------------------------------------------------------------------------

class TestCoboSettleErrorPaths:
    def test_http_400_returns_failure(self):
        rec = RequestRecorder(FakeResponse(400, {"error_message": "bad token"}))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")
        assert result.success is False
        assert result.tx_hash is None
        assert "Cobo HTTP 400" in result.error
        assert "bad token" in result.error

    def test_http_500_returns_failure(self):
        rec = RequestRecorder(FakeResponse(500, text="Internal Error"))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")
        assert result.success is False
        assert "Cobo HTTP 500" in result.error

    def test_connection_error_returns_failure(self):
        def boom(*a, **kw):
            raise requests.exceptions.ConnectionError("network down")
        provider = _make_provider(request_callable=boom)
        result = provider.settle("0xR", 100, "USDC", "ETH")
        assert result.success is False
        assert "Cobo transport error" in result.error
        assert "network down" in result.error

    def test_timeout_error_returns_failure(self):
        def boom(*a, **kw):
            raise requests.exceptions.Timeout("slow")
        provider = _make_provider(request_callable=boom)
        result = provider.settle("0xR", 100, "USDC", "ETH")
        assert result.success is False
        assert "Cobo transport error" in result.error

    def test_non_json_response_returns_failure(self):
        rec = RequestRecorder(FakeResponse(200, json_data=None, text="<html>"))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")
        assert result.success is False
        assert result.error == "Cobo response was not JSON"


# ---------------------------------------------------------------------------
# settle() — transport-level retry uses the SAME request_id (idempotency)
# ---------------------------------------------------------------------------

class TestCoboSettleRetryIdempotency:
    """Re-submission on a transport timeout must reuse Cobo's request_id.

    Why this matters: if the first attempt reached Cobo but the response was
    lost (timeout / TCP reset), retrying with a NEW request_id would mint a
    *second* transfer and double-bill the creator. Cobo dedupes server-side
    on request_id, so as long as both attempts carry the same value the
    second submission is a no-op and returns the original result.
    """

    def test_retry_on_timeout_reuses_request_id(self):
        """Two-attempt sequence: first times out, second succeeds. Same id."""
        request_ids = []
        attempts = {"n": 0}

        def handler(method, url, **kwargs):
            request_ids.append(json.loads(kwargs["data"])["request_id"])
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise requests.exceptions.Timeout("first attempt slow")
            return FakeResponse(200, {"tx_hash": "0xfinal"})

        rec = RequestRecorder(handler)
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")

        assert result.success is True
        assert result.tx_hash == "0xfinal"
        assert len(request_ids) == 2
        # Both attempts MUST carry the same request_id so Cobo dedupes.
        assert request_ids[0] == request_ids[1]
        assert request_ids[0].startswith("hirenet-")

    def test_retry_on_connection_error_reuses_request_id(self):
        """ConnectionError (e.g. RST mid-send) takes the same retry path."""
        request_ids = []
        attempts = {"n": 0}

        def handler(method, url, **kwargs):
            request_ids.append(json.loads(kwargs["data"])["request_id"])
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise requests.exceptions.ConnectionError("reset")
            return FakeResponse(200, {"tx_hash": "0xok"})

        rec = RequestRecorder(handler)
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")

        assert result.success is True
        assert request_ids[0] == request_ids[1]

    def test_retry_budget_gives_up_after_three(self):
        """Persistent transport failure surfaces a single error to the caller."""
        attempts = {"n": 0}

        def handler(method, url, **kwargs):
            attempts["n"] += 1
            raise requests.exceptions.Timeout("always slow")

        rec = RequestRecorder(handler)
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")

        assert result.success is False
        # The retry budget is bounded — must not loop forever on a dead host.
        assert attempts["n"] == 3
        assert "after 3 attempts" in result.error

    def test_retry_resigns_with_fresh_nonce_each_attempt(self):
        """Each attempt must carry a fresh nonce + timestamp (replay protection),
        even though request_id stays constant for dedupe."""
        nonces = []
        attempts = {"n": 0}

        def handler(method, url, **kwargs):
            nonces.append(kwargs["headers"]["Biz-Api-Nonce"])
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise requests.exceptions.Timeout("slow")
            return FakeResponse(200, {"tx_hash": "0xok"})

        rec = RequestRecorder(handler)
        provider = _make_provider(request_callable=rec)
        provider.settle("0xR", 100, "USDC", "ETH")

        # If we ever reused a nonce, Cobo's replay guard would reject the retry.
        assert len(nonces) == 2
        assert nonces[0] != nonces[1]

    def test_http_4xx_is_not_retried(self):
        """A 400 means the request was processed — retrying would change nothing."""
        attempts = {"n": 0}

        def handler(method, url, **kwargs):
            attempts["n"] += 1
            return FakeResponse(400, {"error_message": "bad token"})

        rec = RequestRecorder(handler)
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")

        assert result.success is False
        # Exactly one attempt: HTTP errors are not in the retryable set.
        assert attempts["n"] == 1


# ---------------------------------------------------------------------------
# settle() — currency / chain validation (P0-3)
# ---------------------------------------------------------------------------

class TestCoboSettleTokenValidation:
    """Unknown (currency, chain) tuples must abort at settle() entry.

    The provider has no per-token decimal map yet, so an unfamiliar token
    would silently move the wrong magnitude on-chain. Failing loudly forces
    operators to add the decimal scaling story together with the whitelist
    entry.
    """

    def test_unknown_currency_raises(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        with pytest.raises(ValueError, match="unsupported"):
            provider.settle("0xR", 100, "MYSTERYCOIN", "ETH")
        # No HTTP call should have left the provider for an unknown token.
        assert rec.calls == []

    def test_unknown_chain_raises(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        with pytest.raises(ValueError, match="unsupported"):
            provider.settle("0xR", 100, "USDC", "POLYGON")
        assert rec.calls == []

    def test_no_chain_raises(self):
        """Chain=None (fiat-like) is not a Cobo concept; reject up-front."""
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        with pytest.raises(ValueError, match="unsupported"):
            provider.settle("0xR", 100, "USD", None)
        assert rec.calls == []

    def test_case_insensitive_match(self):
        """Lower-case input still resolves to the canonical entry."""
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "usdc", "eth")
        assert result.success is True

    def test_whitelisted_combos_pass(self):
        """All declared (currency, chain) entries must reach the wire."""
        for currency, chain in (("USDC", "ETH"), ("USDC", "BASE"), ("USDC", "SEPOLIA")):
            rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
            provider = _make_provider(request_callable=rec)
            result = provider.settle("0xR", 100, currency, chain)
            assert result.success is True, f"({currency}, {chain}) should succeed"


# ---------------------------------------------------------------------------
# settle() — Cobo is not synchronously settled (P2)
# ---------------------------------------------------------------------------

class TestCoboSettleNextStatus:
    """Cobo's transfer success only means submitted; status stays settling."""

    def test_success_returns_next_status_settling(self):
        rec = RequestRecorder(FakeResponse(200, {"tx_hash": "0x1"}))
        provider = _make_provider(request_callable=rec)
        result = provider.settle("0xR", 100, "USDC", "ETH")
        assert result.success is True
        # Default would be SETTLED (Mock's posture). Cobo must override to
        # SETTLING — the route reads this to leave the agent_run pending an
        # on-chain confirmation via check_status().
        assert result.next_status is SettlementStatus.SETTLING


# ---------------------------------------------------------------------------
# check_status() — state mapping and degrade-to-SETTLING on transport failure
# ---------------------------------------------------------------------------

class TestCoboCheckStatus:
    @pytest.mark.parametrize("cobo_state,expected", [
        ("Success", SettlementStatus.SETTLED),
        ("Completed", SettlementStatus.SETTLED),
        ("Failed", SettlementStatus.FAILED),
        ("Rejected", SettlementStatus.FAILED),
        ("Submitted", SettlementStatus.SETTLING),
        ("Pending", SettlementStatus.SETTLING),
        ("PendingApproval", SettlementStatus.SETTLING),
        ("Broadcasting", SettlementStatus.SETTLING),
    ])
    def test_state_mapping(self, cobo_state, expected):
        rec = RequestRecorder(FakeResponse(200, {"status": cobo_state}))
        provider = _make_provider(request_callable=rec)
        assert provider.check_status("tx-1") is expected

    def test_unknown_state_degrades_to_settling(self):
        """Defensive: an unrecognised Cobo state must NOT silently flip to SETTLED."""
        rec = RequestRecorder(FakeResponse(200, {"status": "TotallyMadeUp"}))
        provider = _make_provider(request_callable=rec)
        assert provider.check_status("tx-1") is SettlementStatus.SETTLING

    def test_missing_state_degrades_to_settling(self):
        rec = RequestRecorder(FakeResponse(200, {}))
        provider = _make_provider(request_callable=rec)
        assert provider.check_status("tx-1") is SettlementStatus.SETTLING

    def test_http_error_degrades_to_settling(self):
        # Transient outage shouldn't poison an in-flight run to FAILED.
        rec = RequestRecorder(FakeResponse(503, text="unavailable"))
        provider = _make_provider(request_callable=rec)
        assert provider.check_status("tx-1") is SettlementStatus.SETTLING

    def test_transport_error_degrades_to_settling(self):
        def boom(*a, **kw):
            raise requests.exceptions.ConnectionError("nope")
        provider = _make_provider(request_callable=boom)
        assert provider.check_status("tx-1") is SettlementStatus.SETTLING

    def test_targets_transaction_url(self):
        rec = RequestRecorder(FakeResponse(200, {"status": "Success"}))
        provider = _make_provider(request_callable=rec)
        provider.check_status("0xabc")
        assert rec.calls[0]["method"] == "GET"
        assert rec.calls[0]["url"] == (
            "https://api.cobo.com/v2/wallets/wallet-test/transactions/0xabc"
        )

    def test_check_status_signs_request(self):
        rec = RequestRecorder(FakeResponse(200, {"status": "Success"}))
        provider = _make_provider(request_callable=rec)
        provider.check_status("0xabc")
        # Every Cobo call must carry the Biz-Api-* signature headers, GET too.
        assert "Biz-Api-Signature" in rec.calls[0]["headers"]


# ---------------------------------------------------------------------------
# token_id derivation — pure helper, exhaustively cased
# ---------------------------------------------------------------------------

class TestCoboTokenIdDerivation:
    def test_chain_and_currency_concatenate(self):
        assert CoboSettlementProvider._derive_token_id("USDC", "ETH") == "ETH_USDC"

    def test_chain_and_currency_uppercased(self):
        assert CoboSettlementProvider._derive_token_id("usdc", "sepolia") == "SEPOLIA_USDC"

    def test_no_chain_falls_back_to_currency(self):
        # No chain → no concat. Cobo's validator returns the error, not us.
        assert CoboSettlementProvider._derive_token_id("USD", None) == "USD"


# ---------------------------------------------------------------------------
# State map sanity — every value is a real SettlementStatus
# ---------------------------------------------------------------------------

class TestCoboStateMapSanity:
    def test_every_mapped_value_is_a_settlement_status(self):
        for state, mapped in _COBO_STATE_MAP.items():
            assert isinstance(mapped, SettlementStatus), (
                f"_COBO_STATE_MAP[{state!r}] is not a SettlementStatus"
            )

    def test_no_unknown_state_maps_to_settled(self):
        # Belt-and-braces: a future contributor adding a state must not
        # accidentally route an ambiguous one to SETTLED without thinking.
        assert SettlementStatus.SETTLED not in [
            _COBO_STATE_MAP[s] for s in ("Submitted", "Pending", "PendingApproval")
        ]
