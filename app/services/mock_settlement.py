"""
Phase 3 / U1 — In-memory mock settlement provider.

The Mock provider never touches a real chain. `settle` returns a synthetic
`mock-<hex>` tx_hash and reports success; `check_status` always reports
SETTLED. The point is to exercise the `accrued → settling → settled` state
machine end-to-end so the U2 swap to Cobo is a pure provider replacement,
not a route/DAO rewrite.

Do NOT use this in any environment where real money should move — the route
layer trusts the provider's success signal and flips the ledger to settled.
"""
import secrets

from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
)


class MockSettlementProvider(SettlementProvider):
    """Always-succeed provider used by U1 + tests. Method name 'mock'."""

    name = "mock"

    def settle(
        self,
        payee_id: str,
        amount: int,
        currency: str,
        chain: str | None,
    ) -> SettlementResult:
        # token_hex(8) → 16 hex chars; collision risk for demo volumes is nil.
        return SettlementResult(
            success=True,
            tx_hash=f"mock-{secrets.token_hex(8)}",
        )

    def check_status(self, tx_hash: str) -> SettlementStatus:
        return SettlementStatus.SETTLED
