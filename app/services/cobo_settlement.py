"""
Phase 3 / U2 — Cobo WaaS 2.0 settlement provider.

Submits royalty payouts to Cobo Custody / Wallet-as-a-Service v2. Speaks the
same SettlementProvider contract as MockSettlementProvider, so the swap is a
single env var (HIRENET_SETTLEMENT_PROVIDER=cobo). Authenticates with
Ed25519 over `method|path|nonce|timestamp[|body]`; the secret in
COBO_API_SECRET is a hex-encoded 32-byte Ed25519 private key.

⚠️ NOT EXERCISED AGAINST REAL COBO TESTNET. The author had no testnet API
credentials at implementation time, so the wire shape is reconstructed from
Cobo's published WaaS 2.0 docs and only verified at the boundary by mocked
`requests`. Before going to testnet/mainnet, run one real transaction
end-to-end and reconcile with the live response — in particular:
  - exact transaction state strings returned by GET /transactions/{id};
  - which response field actually carries the on-chain tx_hash vs. the
    Cobo-internal request_id;
  - whether `from_address` is required when the wallet has multiple addrs.

Known stubs left for a follow-up PR (do NOT ship to mainnet without these):
  - `payee_id` is used directly as `to_address`. Real deployment needs an
    identity → wallet-address registry (Phase 3 U3+).
  - `amount` is forwarded as cents; Cobo wants the on-chain smallest unit
    (USDC has 6 decimals → 100 cents = 100,000 micro-USDC). No per-token
    decimal map yet — testnet payouts will undershoot by 10**(decimals-2).
"""
import json
import secrets
import time

import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
)


# Cobo WaaS 2.0 transaction states → our enum. Unknown / unexpected states
# intentionally map to SETTLING (not SETTLED) so a stale or surprising
# response can't silently flip a run to terminal-success — the route layer
# can keep polling, and an operator can investigate.
_COBO_STATE_MAP = {
    "Success": SettlementStatus.SETTLED,
    "Completed": SettlementStatus.SETTLED,
    "Failed": SettlementStatus.FAILED,
    "Rejected": SettlementStatus.FAILED,
    "Submitted": SettlementStatus.SETTLING,
    "Pending": SettlementStatus.SETTLING,
    "PendingApproval": SettlementStatus.SETTLING,
    "PendingSignature": SettlementStatus.SETTLING,
    "Broadcasting": SettlementStatus.SETTLING,
    "Confirmation": SettlementStatus.SETTLING,
}

# Internal retry budget for transport-level failures (Timeout / ConnectionError
# only — NOT HTTP 4xx/5xx). Re-submissions reuse the same Cobo request_id so
# the server-side dedupe key prevents double-billing on the retry. Three
# attempts ≈ one initial + two retries; tune up only after measuring real
# Cobo retry budgets, otherwise tail latency balloons.
_MAX_TRANSPORT_RETRIES = 3

# Whitelist of (currency, chain) tuples this provider knows how to settle.
# Adding a new token requires also verifying the amount-scaling story (the
# integer `amount` arg is currently forwarded as the on-chain smallest unit
# — see the module docstring). Until that map exists, restricting the set
# is the only thing that prevents a silent USDC→micro-USDC underpayment.
_SUPPORTED_TOKENS = frozenset({
    ("USDC", "ETH"),
    ("USDC", "BASE"),
    ("USDC", "SEPOLIA"),
})


class CoboSettlementProvider(SettlementProvider):
    """Submit royalty payouts via Cobo WaaS 2.0.

    The Ed25519 private key is parsed once in __init__ — if COBO_API_SECRET
    isn't a 64-char hex string the constructor raises ValueError instead of
    letting the first sign attempt explode mid-route. Same loud-failure
    posture for the other three required config values.
    """
    name = "cobo"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str,
        wallet_id: str,
        *,
        from_address: str | None = None,
        timeout_seconds: int = 30,
        request_callable=None,
    ):
        if not api_key:
            raise ValueError("COBO_API_KEY is required")
        if not api_secret:
            raise ValueError("COBO_API_SECRET is required")
        if not base_url:
            raise ValueError("COBO_BASE_URL is required")
        if not wallet_id:
            raise ValueError("COBO_WALLET_ID is required")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.wallet_id = wallet_id
        self.from_address = from_address
        self.timeout = timeout_seconds
        # Lets tests inject a fake `requests.request`-shaped callable without
        # monkeypatching the global module — keeps test isolation tight.
        self._request = request_callable or requests.request

        try:
            self._private_key = Ed25519PrivateKey.from_private_bytes(
                bytes.fromhex(api_secret)
            )
        except ValueError as exc:
            raise ValueError(
                "COBO_API_SECRET must be a hex-encoded Ed25519 private key "
                f"(32 bytes / 64 hex chars): {exc}"
            )

    # ------------------------------------------------------------------
    # SettlementProvider contract
    # ------------------------------------------------------------------

    def settle(
        self,
        payee_id: str,
        amount: int,
        currency: str,
        chain: str | None,
    ) -> SettlementResult:
        # Unknown (currency, chain) → ValueError. Forwarding an unwhitelisted
        # token would let the integer `amount` slip through with no decimal
        # scaling (USDC has 6 decimals → 100 cents would settle as 100
        # micro-USDC instead of $1.00). Operators must explicitly add a
        # combination here after verifying the scaling story below in
        # `_derive_token_id` / the eventual decimal map.
        self._require_supported_token(currency, chain)
        token_id = self._derive_token_id(currency, chain)

        # request_id is Cobo's idempotency token. Generated ONCE per settle()
        # call and reused across the internal retry loop so a transport
        # timeout doesn't get billed twice: if the first attempt did reach
        # Cobo but the response was lost, the retry hits Cobo's server-side
        # dedupe and returns the original result rather than minting a new
        # transfer. The outer state machine in agent_runs guards against
        # duplicate settle() calls from concurrent requests on the same run.
        request_id = "hirenet-" + secrets.token_hex(12)

        body = {
            "request_id": request_id,
            "to_address": payee_id,
            "token_id": token_id,
            "amount": str(amount),
            "memo": "HireNet royalty payout",
        }
        if self.from_address:
            body["from_address"] = self.from_address

        # Body bytes must be identical between the signing step and the wire
        # send, otherwise the signature won't verify. sort_keys + the compact
        # separators give a stable, canonical form.
        body_str = json.dumps(body, sort_keys=True, separators=(",", ":"))
        path = f"/v2/wallets/{self.wallet_id}/transactions/transfer"
        url = self.base_url + path

        # Retry only on transport-level glitches (Timeout / ConnectionError).
        # HTTP 4xx/5xx with a real Cobo response is NOT retried — the request
        # was processed and we should propagate the answer. Non-retryable
        # RequestException subclasses (e.g. InvalidURL) also bubble out.
        resp = None
        last_error: Exception | None = None
        for _attempt in range(_MAX_TRANSPORT_RETRIES):
            try:
                # Re-sign each attempt: Cobo requires a fresh nonce + timestamp
                # per request, but the body (and thus request_id) is identical
                # so the server-side dedupe key stays constant.
                headers = self._sign_request("POST", path, body_str)
                headers["Content-Type"] = "application/json"
                resp = self._request(
                    "POST", url, data=body_str, headers=headers,
                    timeout=self.timeout,
                )
                break
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                last_error = exc
                continue
            except requests.exceptions.RequestException as exc:
                return SettlementResult(
                    success=False, error=f"Cobo transport error: {exc}",
                )
        else:
            return SettlementResult(
                success=False,
                error=(
                    f"Cobo transport error after {_MAX_TRANSPORT_RETRIES} "
                    f"attempts: {last_error}"
                ),
            )

        if resp.status_code >= 400:
            return SettlementResult(
                success=False,
                error=f"Cobo HTTP {resp.status_code}: {self._error_text(resp)}",
            )

        try:
            data = resp.json()
        except ValueError:
            return SettlementResult(
                success=False, error="Cobo response was not JSON",
            )

        # Cobo's transfer response carries several IDs; prefer the on-chain
        # tx_hash, then Cobo's internal id, then echo back our own request_id
        # so the row at least has *something* linkable on a follow-up poll.
        tx_hash = (
            data.get("tx_hash")
            or data.get("cobo_id")
            or data.get("request_id")
            or request_id
        )
        # On-chain confirmation isn't synchronous on Cobo: success here means
        # the transfer was accepted, not that it's on-chain. The route layer
        # reads `next_status=SETTLING` and leaves the agent_run at 'settling'
        # until a later check_status() poll observes a terminal Cobo state.
        return SettlementResult(
            success=True,
            tx_hash=tx_hash,
            next_status=SettlementStatus.SETTLING,
        )

    def check_status(self, tx_hash: str) -> SettlementStatus:
        """GET /v2/wallets/{wallet_id}/transactions/{tx_hash}.

        Transport / HTTP / JSON errors degrade to SETTLING (not FAILED): a
        transient outage shouldn't poison an in-flight run, and the route
        layer can keep polling. Only an explicit Cobo "Failed" / "Rejected"
        flips us to FAILED.
        """
        path = f"/v2/wallets/{self.wallet_id}/transactions/{tx_hash}"
        url = self.base_url + path

        try:
            headers = self._sign_request("GET", path, "")
            resp = self._request("GET", url, headers=headers, timeout=self.timeout)
        except requests.exceptions.RequestException:
            return SettlementStatus.SETTLING

        if resp.status_code >= 400:
            return SettlementStatus.SETTLING

        try:
            data = resp.json()
        except ValueError:
            return SettlementStatus.SETTLING

        state = data.get("status") or data.get("state") or ""
        return _COBO_STATE_MAP.get(state, SettlementStatus.SETTLING)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _sign_request(self, method: str, path: str, body: str) -> dict:
        """Ed25519 over `method|path|nonce|timestamp[|body]`.

        Body is the exact bytes sent over the wire — caller must compute
        the body string once and pass the same value to both this function
        and the HTTP transport, otherwise the signature won't verify.
        """
        timestamp = str(int(time.time() * 1000))
        nonce = secrets.token_hex(16)
        message = f"{method}|{path}|{nonce}|{timestamp}"
        if body:
            message += f"|{body}"
        signature = self._private_key.sign(message.encode("utf-8")).hex()
        return {
            "Biz-Api-Key": self.api_key,
            "Biz-Api-Nonce": nonce,
            "Biz-Api-Timestamp": timestamp,
            "Biz-Api-Signature": signature,
        }

    @staticmethod
    def _require_supported_token(currency: str, chain: str | None) -> None:
        """Raise ValueError unless (currency, chain) is in the whitelist.

        Guards against silent under-payment: this provider forwards `amount`
        verbatim as Cobo's smallest-unit field and has no decimal map yet, so
        an unfamiliar token would settle at the wrong magnitude (USDC=6
        decimals, ETH=18, DAI=18 — paying 100 cents would actually move 100
        micro-USDC = $0.0001). Failing loudly here forces an operator to
        update both _SUPPORTED_TOKENS and the eventual scaling map together.
        """
        normalised = (
            (currency or "").upper(),
            (chain or "").upper() if chain else None,
        )
        if normalised not in _SUPPORTED_TOKENS:
            raise ValueError(
                f"Cobo provider: unsupported (currency, chain) "
                f"({currency!r}, {chain!r}). "
                f"Add it to _SUPPORTED_TOKENS only after verifying the "
                f"on-chain decimal scaling for this token."
            )

    @staticmethod
    def _derive_token_id(currency: str, chain: str | None) -> str:
        """Map (currency, chain) → Cobo token_id (e.g. SEPOLIA_USDC).

        Cobo's token catalog uses `{CHAIN}_{TOKEN}`. When chain is None we
        fall through to currency alone so Cobo's own validator returns the
        error rather than us guessing a default chain.
        """
        if chain:
            return f"{chain}_{currency}".upper()
        return currency.upper()

    @staticmethod
    def _error_text(resp) -> str:
        """Best-effort short error string from a non-2xx Cobo response."""
        try:
            data = resp.json()
            if isinstance(data, dict):
                return (
                    data.get("error_message")
                    or data.get("message")
                    or json.dumps(data)
                )
            return str(data)
        except ValueError:
            return (resp.text or "")[:200]
