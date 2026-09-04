"""
Phase 3 / U1 — Settlement provider abstraction + state machine.

This module defines the contract a settlement backend must implement, so the
royalty path stays the same shape whether we settle through:
  - the Mock provider (this Phase, U1) — no real chain, returns fake tx_hash;
  - the Anvil provider (demo) — local Foundry node, real tx_hash, 0-ETH
    metadata tx so the receipt is verifiable via `cast receipt`;
  - the Sepolia provider — public Ethereum testnet via HTTP RPC;
  - x402 or other rails (later) — same ABC, different impl.

The state machine the rest of the system relies on is:

    accrued ──claim──▶ settling ──confirm──▶ settled   (terminal)
                          │
                          └──fail──▶ failed ──claim──▶ settling …  (retriable)

`accrued` and `failed` are the only states from which `claim_settlement` will
flip a run to `settling`. `settled` is the only true terminal — a second POST
to /api/royalty/settle on a settled run is a no-op. Concurrency is handled by
a conditional UPDATE on `agent_runs.settlement_status` (the DAO layer); two
threads racing to claim see exactly one rowcount=1 result, the other gets 0.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class SettlementStatus(Enum):
    """Lifecycle states for a single agent_run's settlement.

    Mirrors agent_runs.settlement_status DB enum 1:1. The DAO layer stores the
    `.value` string; provider implementations return one of these enum members
    from `check_status`.
    """
    ACCRUED = "accrued"
    SETTLING = "settling"   # submitted to provider/chain, awaiting confirmation
    SETTLED = "settled"     # provider confirmed; terminal
    FAILED = "failed"       # provider rejected/errored; retriable


@dataclass
class SettlementResult:
    """Outcome of a single provider.settle() call.

    `success=True` means the provider accepted the submission; the on-chain
    state may still be pending (use check_status for that). `tx_hash` is the
    provider's identifier we persist on `agent_runs.tx_hash` so a later poll
    / audit can join back to the run.

    On `success=False`, `error` carries a short human-readable reason. The
    caller is responsible for translating it into the appropriate HTTP status
    + storing the run as `failed` via `fail_settlement`.

    `next_status` tells the route layer what agent_run state to transition
    to after a successful submission. Mock returns SETTLED (synchronous —
    no on-chain wait). An asynchronous on-chain provider returns SETTLING
    because the transfer has only been accepted, not yet confirmed on-chain;
    the run advances to SETTLED when a later check_status() observes a
    terminal state. Ignored when success=False (the route flips the run to
    FAILED).
    """
    success: bool
    tx_hash: str | None = None
    error: str | None = None
    next_status: SettlementStatus = SettlementStatus.SETTLED


class SettlementProvider(ABC):
    """Abstract contract every settlement backend must implement.

    Intentionally small: U1 needs only "submit" + "poll". Real rails (on-chain
    / x402) bring richer affordances (cancel, replace, fee estimation) — those
    land in Phase 4 alongside the second provider implementation, not now.
    """

    @abstractmethod
    def settle(
        self,
        payee_id: str,
        amount: int,
        currency: str,
        chain: str | None,
    ) -> SettlementResult:
        """Submit a payment to the underlying rail.

        Args:
            payee_id: opaque identifier of the recipient. For the Mock and
                on-chain providers this is the creator's id; multi-payee
                splits are a
                ledger-layer concern, not the provider's.
            amount: integer basis-point amount (1 cent = 1 for USD-like
                currencies). Matches royalty_ledger.amount / charge_amount.
            currency: ISO-like currency code (e.g. "USD", "USDC").
            chain: optional chain identifier (e.g. "base", "ethereum"). None
                for off-chain rails like fiat or the Mock provider.

        Returns:
            SettlementResult — see dataclass docstring for semantics.
        """
        ...

    @abstractmethod
    def check_status(self, tx_hash: str) -> SettlementStatus:
        """Poll the rail for the current state of a previously-submitted tx.

        U1 only uses this for the Mock provider (always returns SETTLED). U2
        will wire the polling into a status endpoint or background worker so a
        slow on-chain confirmation can eventually flip settling → settled.
        """
        ...


def get_provider(name: str) -> SettlementProvider:
    """Factory: resolve a provider name (env var) to a concrete instance.

    Unknown names raise ValueError so a typo in the deployment env is loud,
    not silent. Each provider reads its own env vars at construction time
    — if any required field is missing, the provider's __init__ raises
    ValueError, which we surface unchanged so the operator sees the exact
    field that's empty.

    Supported names: "mock" (default for tests), "anvil" (local-chain demo
    via Foundry's Anvil node), "sepolia" (public Ethereum testnet via HTTP
    RPC).
    """
    if name == "mock":
        from app.services.mock_settlement import MockSettlementProvider
        return MockSettlementProvider()
    if name == "anvil":
        import os
        from app.services.anvil_settlement import AnvilSettlementProvider
        return AnvilSettlementProvider(
            rpc_url=os.getenv("ANVIL_RPC_URL", "http://localhost:8545"),
            from_key=os.getenv("ANVIL_FROM_KEY", ""),
            to_address=os.getenv("ANVIL_TO_ADDRESS", ""),
        )
    if name == "sepolia":
        import os
        from app.services.sepolia_settlement import SepoliaSettlementProvider
        # SEPOLIA_TO_ADDRESS is the platform-default recipient — used when a
        # SkillAsset hasn't declared its own wallet_address. Empty string
        # → None so the provider knows to fall back to self.from_address.
        default_to = os.getenv("SEPOLIA_TO_ADDRESS", "").strip() or None
        return SepoliaSettlementProvider(
            rpc_url=os.getenv("SEPOLIA_RPC_URL", ""),
            from_key=os.getenv("SEPOLIA_PRIVATE_KEY", ""),
            from_address=os.getenv("SEPOLIA_FROM_ADDRESS", ""),
            default_to_address=default_to,
        )
    raise ValueError(f"Unknown settlement provider: {name!r}")
