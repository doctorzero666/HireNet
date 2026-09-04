"""
Phase 3 / U1 acceptance tests: SettlementProvider interface + state machine.

Covers, in order of dependency:
  - MockSettlementProvider behaviour (interface contract);
  - DAO layer: claim / confirm / fail transitions on agent_runs + ledger;
  - /api/royalty/settle walks the full accrued → settling → settled path;
  - /api/royalty/settle handles failure (custom provider) and retry from failed;
  - /api/royalty/settle is idempotent on settled / 409 on settling;
  - GET /api/royalty/status/<run_id> reports current state + tx_hash.

The Mock provider always succeeds, so tests that need the failure path
inject a FailingProvider (or HoldingProvider for 'settling' races) via
create_app(config={"SETTLEMENT_PROVIDER": ...}).
"""
import os
import tempfile

import pytest
from flask import Flask

from app.app import create_app
from app.services.agent_run_recording import record_agent_run
from app.services.mock_settlement import MockSettlementProvider
from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
    get_provider,
)
from app.services.skill_registration import register_skill_asset
from app.storage.agent_runs import (
    claim_settlement,
    confirm_settlement,
    fail_settlement,
    get_agent_run,
)
from app.storage.db import init_db
from app.storage.royalty_ledger import list_royalties_by_run


# ---------------------------------------------------------------------------
# Test-only providers (drive the not-mock paths)
# ---------------------------------------------------------------------------

class FailingProvider(SettlementProvider):
    """Always reports a failure; used to exercise the failed/retry path."""
    name = "failing"

    def settle(self, payee_id, amount, currency, chain):
        return SettlementResult(success=False, error="injected failure")

    def check_status(self, tx_hash):
        return SettlementStatus.FAILED


class RaisingProvider(SettlementProvider):
    """Raises during settle() — tests our 502 + fail_settlement on exception."""
    name = "raising"

    def settle(self, payee_id, amount, currency, chain):
        raise RuntimeError("provider blew up")

    def check_status(self, tx_hash):
        raise RuntimeError("provider blew up")


class AsyncProvider(SettlementProvider):
    """Models an async on-chain provider: settle() submits, returns SETTLING.

    `check_status` is driven by `chain_state` — the test sets it to mimic
    on-chain progression. Defaults to SETTLING so the row stays pending
    until the test explicitly advances it.
    """
    name = "async"

    def __init__(self):
        self.chain_state = SettlementStatus.SETTLING
        self.settle_calls = 0
        self.check_status_calls = 0

    def settle(self, payee_id, amount, currency, chain):
        self.settle_calls += 1
        return SettlementResult(
            success=True,
            tx_hash=f"async-{self.settle_calls:04d}",
            next_status=SettlementStatus.SETTLING,
        )

    def check_status(self, tx_hash):
        self.check_status_calls += 1
        return self.chain_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = path
    init_db(app)
    yield path
    os.unlink(path)


@pytest.fixture
def failing_client():
    """A Flask test client wired to FailingProvider instead of Mock."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": path,
        "SETTLEMENT_PROVIDER": FailingProvider(),
    })
    with app.test_client() as c:
        yield c
    os.unlink(path)


@pytest.fixture
def raising_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": path,
        "SETTLEMENT_PROVIDER": RaisingProvider(),
    })
    with app.test_client() as c:
        yield c
    os.unlink(path)


@pytest.fixture
def async_client():
    """Flask test client wired to an AsyncProvider (async-chain-shaped:
    settle → SETTLING; check_status drives the eventual advance)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": path,
        "SETTLEMENT_PROVIDER": AsyncProvider(),
    })
    with app.test_client() as c:
        yield c
    os.unlink(path)


def _register_asset(db_path: str, *, creator_id: str = "user_001") -> str:
    payload = {
        "name": "U1 Settlement Skill",
        "description": "fixture asset for Phase 3 U1 tests",
        "type": "skill",
        "io_schema": {"input": {"text": "string"}, "output": {"result": "string"}},
        "price_amount": 100,
        "price_currency": "USD",
        "split_rule": {"creator": 7000, "platform": 2000, "tax": 1000},
    }
    return register_skill_asset(db_path, payload, creator_id)["skill_id"]


def _record_run(db_path: str, asset_id: str, *, charge_amount: int = 100) -> str:
    result = record_agent_run(
        db_path,
        agent_name="TestAgent",
        caller_id="caller_001",
        task_id="task_001",
        asset_id=asset_id,
        charge_amount=charge_amount,
        charge_currency="USD",
        success=True,
    )
    return result["run_id"]


def _seed_run_via_client(client) -> str:
    """End-to-end seed: register an asset under PHASE1_CREATOR_ID and record one run."""
    db_path = client.application.config["DATABASE_PATH"]
    creator_id = client.application.config["PHASE1_CREATOR_ID"]
    asset_id = _register_asset(db_path, creator_id=creator_id)
    return _record_run(db_path, asset_id)


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class TestMockProvider:
    def test_settle_returns_mock_tx_hash(self):
        provider = MockSettlementProvider()
        result = provider.settle("user_001", 100, "USD", None)
        assert result.success is True
        assert result.tx_hash is not None
        assert result.tx_hash.startswith("mock-")
        assert result.error is None

    def test_check_status_always_settled(self):
        provider = MockSettlementProvider()
        assert provider.check_status("mock-abc") is SettlementStatus.SETTLED

    def test_settle_tx_hashes_are_unique(self):
        provider = MockSettlementProvider()
        hashes = {provider.settle("u", 1, "USD", None).tx_hash for _ in range(10)}
        assert len(hashes) == 10, "mock tx_hash should be unique per call"


class TestProviderFactory:
    def test_mock_resolves(self):
        provider = get_provider("mock")
        assert isinstance(provider, MockSettlementProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown settlement provider"):
            get_provider("nonsense")


# ---------------------------------------------------------------------------
# DAO state machine
# ---------------------------------------------------------------------------

class TestClaimSettlement:
    def test_claim_accrued_returns_true(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        assert claim_settlement(db_path, run_id) is True
        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "settling"

    def test_second_claim_returns_false(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        assert claim_settlement(db_path, run_id) is False

    def test_claim_failed_returns_true(self, db_path):
        # failed is retriable: a previously-errored run can be claimed again.
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        fail_settlement(db_path, run_id, "injected")
        assert claim_settlement(db_path, run_id) is True

    def test_claim_settled_returns_false(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        confirm_settlement(db_path, run_id, "tx-001", "mock")
        assert claim_settlement(db_path, run_id) is False

    def test_claim_unknown_run_returns_false(self, db_path):
        assert claim_settlement(db_path, "no-such-run") is False


class TestConfirmSettlement:
    def test_confirm_flips_run_and_three_ledger_rows(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)

        flipped = confirm_settlement(db_path, run_id, "tx-aaa", "mock")
        assert flipped == 3, "creator + platform + tax rows must all flip"

        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "settled"
        assert run["tx_hash"] == "tx-aaa"
        assert run["settlement_method"] == "mock"

        ledger = list_royalties_by_run(db_path, run_id)
        assert len(ledger) == 3
        assert all(row["status"] == "settled" for row in ledger)

    def test_confirm_without_claim_is_noop(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        # status is 'accrued', not 'settling' — confirm must do nothing.
        flipped = confirm_settlement(db_path, run_id, "tx-aaa", "mock")
        assert flipped == 0
        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "accrued"
        assert run["tx_hash"] is None


class TestFailSettlement:
    def test_fail_marks_run_failed_leaves_ledger_alone(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)

        assert fail_settlement(db_path, run_id, "boom") is True

        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "failed"
        assert run["tx_hash"] is None  # never set, stays NULL

        ledger = list_royalties_by_run(db_path, run_id)
        assert all(row["status"] == "accrued" for row in ledger), (
            "fail_settlement must NOT flip ledger rows — they remain accrued so a retry "
            "can confirm them later"
        )

    def test_fail_without_claim_returns_false(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        # 'accrued', not 'settling'.
        assert fail_settlement(db_path, run_id, "boom") is False


# ---------------------------------------------------------------------------
# /api/royalty/settle — happy path through Mock
# ---------------------------------------------------------------------------

class TestSettleRouteMockHappyPath:
    def test_settle_end_to_end(self, client):
        run_id = _seed_run_via_client(client)
        resp = client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 200
        body = resp.get_json()
        # Legacy shape preserved:
        assert body["run_id"] == run_id
        assert body["settled_count"] == 3
        assert body["status"] == "settled"
        # New U1 fields:
        assert body["settlement_status"] == "settled"
        assert body["settlement_method"] == "mock"
        assert body["tx_hash"].startswith("mock-")

    def test_settle_is_idempotent_on_settled(self, client):
        run_id = _seed_run_via_client(client)
        first = client.post("/api/royalty/settle", json={"run_id": run_id}).get_json()
        second = client.post("/api/royalty/settle", json={"run_id": run_id}).get_json()
        assert first["settled_count"] == 3
        assert second["settled_count"] == 0
        assert second["status"] == "settled"
        assert second["settlement_status"] == "settled"
        # tx_hash must be preserved across the no-op call.
        assert second["tx_hash"] == first["tx_hash"]

    def test_unknown_run_id_404(self, client):
        resp = client.post("/api/royalty/settle", json={"run_id": "no-such-run"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/royalty/settle — failure paths + retry
# ---------------------------------------------------------------------------

class TestSettleRouteFailurePath:
    def test_failing_provider_marks_run_failed(self, failing_client):
        run_id = _seed_run_via_client(failing_client)
        resp = failing_client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 502
        body = resp.get_json()
        assert body["settlement_status"] == "failed"
        assert "injected failure" in body["error"]

        db_path = failing_client.application.config["DATABASE_PATH"]
        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "failed"
        # Ledger rows remain accrued so a retry can confirm them.
        ledger = list_royalties_by_run(db_path, run_id)
        assert all(r["status"] == "accrued" for r in ledger)

    def test_retry_after_failure_succeeds(self, failing_client):
        run_id = _seed_run_via_client(failing_client)
        failing_client.post("/api/royalty/settle", json={"run_id": run_id})
        # Swap to the Mock provider mid-flight (operator-level recovery) and retry.
        failing_client.application.config["SETTLEMENT_PROVIDER"] = MockSettlementProvider()
        resp = failing_client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["settled_count"] == 3
        assert body["settlement_status"] == "settled"
        assert body["tx_hash"].startswith("mock-")

    def test_raising_provider_lands_run_in_failed(self, raising_client):
        run_id = _seed_run_via_client(raising_client)
        resp = raising_client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 502
        assert resp.get_json()["settlement_status"] == "failed"
        run = get_agent_run(
            raising_client.application.config["DATABASE_PATH"], run_id
        )
        assert run["settlement_status"] == "failed"


# ---------------------------------------------------------------------------
# /api/royalty/settle — concurrency / settling guard
# ---------------------------------------------------------------------------

class TestSettleRouteConcurrencyGuard:
    def test_409_when_already_settling(self, client):
        # Simulate the race window: pre-flip the run to 'settling' (as if
        # another thread already claimed it) and verify the route refuses.
        run_id = _seed_run_via_client(client)
        db_path = client.application.config["DATABASE_PATH"]
        assert claim_settlement(db_path, run_id) is True

        resp = client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["settlement_status"] == "settling"


# ---------------------------------------------------------------------------
# GET /api/royalty/status/<run_id>
# ---------------------------------------------------------------------------

class TestRoyaltyStatusRoute:
    def test_status_reflects_initial_accrued(self, client):
        run_id = _seed_run_via_client(client)
        resp = client.get(f"/api/royalty/status/{run_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["run_id"] == run_id
        assert body["settlement_status"] == "accrued"
        assert body["tx_hash"] is None
        assert body["settlement_method"] == "ledger_only"
        assert body["charge_amount"] == 100
        assert body["charge_currency"] == "USD"

    def test_status_after_settle(self, client):
        run_id = _seed_run_via_client(client)
        client.post("/api/royalty/settle", json={"run_id": run_id})
        body = client.get(f"/api/royalty/status/{run_id}").get_json()
        assert body["settlement_status"] == "settled"
        assert body["tx_hash"].startswith("mock-")
        assert body["settlement_method"] == "mock"

    def test_status_unknown_run_id_404(self, client):
        resp = client.get("/api/royalty/status/no-such-run")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Phase 3 / U2: async provider — settle leaves SETTLING, status polls advance
# ---------------------------------------------------------------------------

class TestAsyncSettleLeavesSettling:
    """Async on-chain flow: settle() success ≠ on-chain confirmed.

    Locks in the contract the route must keep with async rails so that a
    transfer the provider only *accepted* never gets billed as paid in the
    ledger until check_status() observes a terminal on-chain state.
    """

    def test_settle_returns_settling_not_settled(self, async_client):
        run_id = _seed_run_via_client(async_client)
        resp = async_client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 200
        body = resp.get_json()
        # settled_count=0 — ledger rows must still be accrued.
        assert body["settled_count"] == 0
        assert body["status"] == "settling"
        assert body["settlement_status"] == "settling"
        assert body["tx_hash"].startswith("async-")
        assert body["settlement_method"] == "async"

    def test_ledger_rows_stay_accrued_during_settling(self, async_client):
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})

        db_path = async_client.application.config["DATABASE_PATH"]
        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "settling"
        # tx_hash and settlement_method must be persisted so a later check_status
        # poll can find this run — without this the row is unrecoverable.
        assert run["tx_hash"].startswith("async-")
        assert run["settlement_method"] == "async"

        ledger = list_royalties_by_run(db_path, run_id)
        assert len(ledger) == 3
        assert all(r["status"] == "accrued" for r in ledger), (
            "ledger MUST stay accrued until chain confirms — otherwise an "
            "unconfirmed on-chain transfer would already show as paid out"
        )

    def test_duplicate_settle_during_settling_is_409(self, async_client):
        """The settling guard must still apply to async providers."""
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})
        # Second submit while still 'settling' must NOT re-submit to the rail.
        provider = async_client.application.config["SETTLEMENT_PROVIDER"]
        calls_before = provider.settle_calls
        resp = async_client.post("/api/royalty/settle", json={"run_id": run_id})
        assert resp.status_code == 409
        assert provider.settle_calls == calls_before


class TestAsyncStatusAdvancesOnConfirm:
    """GET /api/royalty/status opportunistically polls check_status."""

    def test_status_advances_to_settled_when_chain_confirms(self, async_client):
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})

        # Simulate the chain reaching a terminal on-chain state.
        provider = async_client.application.config["SETTLEMENT_PROVIDER"]
        provider.chain_state = SettlementStatus.SETTLED

        body = async_client.get(f"/api/royalty/status/{run_id}").get_json()
        assert body["settlement_status"] == "settled"
        assert body["tx_hash"].startswith("async-")
        assert provider.check_status_calls == 1

        # Ledger rows must flip atomically with the run.
        db_path = async_client.application.config["DATABASE_PATH"]
        ledger = list_royalties_by_run(db_path, run_id)
        assert all(r["status"] == "settled" for r in ledger), (
            "agent_runs.settlement_status and ledger rows must advance together"
        )

    def test_status_advances_to_failed_when_chain_rejects(self, async_client):
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})

        provider = async_client.application.config["SETTLEMENT_PROVIDER"]
        provider.chain_state = SettlementStatus.FAILED

        body = async_client.get(f"/api/royalty/status/{run_id}").get_json()
        assert body["settlement_status"] == "failed"

        # Ledger rows must stay accrued so a retry can still settle them.
        db_path = async_client.application.config["DATABASE_PATH"]
        ledger = list_royalties_by_run(db_path, run_id)
        assert all(r["status"] == "accrued" for r in ledger)

    def test_status_stays_settling_when_chain_still_pending(self, async_client):
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})
        # provider.chain_state defaults to SETTLING.

        body = async_client.get(f"/api/royalty/status/{run_id}").get_json()
        assert body["settlement_status"] == "settling"
        assert body["tx_hash"].startswith("async-")

    def test_check_status_exception_does_not_break_route(self, async_client):
        """A flaky rail must not 500 a status read."""
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})

        provider = async_client.application.config["SETTLEMENT_PROVIDER"]
        def boom(_tx):
            raise RuntimeError("rail down")
        provider.check_status = boom

        resp = async_client.get(f"/api/royalty/status/{run_id}")
        assert resp.status_code == 200
        body = resp.get_json()
        # State should not advance on a thrown exception.
        assert body["settlement_status"] == "settling"

    def test_status_does_not_poll_accrued_runs(self, async_client):
        """No tx_hash on an accrued run → no rail call wasted."""
        run_id = _seed_run_via_client(async_client)
        # Skip settle so the run is still 'accrued', no tx_hash.
        provider = async_client.application.config["SETTLEMENT_PROVIDER"]
        async_client.get(f"/api/royalty/status/{run_id}").get_json()
        assert provider.check_status_calls == 0


class TestSyncProviderStillSettlesImmediately:
    """Regression guard: the Mock path must still flip to settled in one call."""

    def test_mock_path_flips_settled_count_3(self, client):
        run_id = _seed_run_via_client(client)
        body = client.post("/api/royalty/settle", json={"run_id": run_id}).get_json()
        # Synchronous provider (default Mock) must still report settled_count=3.
        assert body["settled_count"] == 3
        assert body["status"] == "settled"
        assert body["settlement_status"] == "settled"


class TestRecordSettlementSubmissionDAO:
    """Direct DAO tests for the new record_settlement_submission helper."""

    def test_updates_tx_hash_while_settling(self, db_path):
        from app.storage.agent_runs import record_settlement_submission
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)

        assert record_settlement_submission(
            db_path, run_id, tx_hash="async-pending-1", method="async_chain",
        ) is True

        run = get_agent_run(db_path, run_id)
        assert run["settlement_status"] == "settling"  # NOT settled
        assert run["tx_hash"] == "async-pending-1"
        assert run["settlement_method"] == "async_chain"

        # Ledger rows must remain accrued — only confirm_settlement flips them.
        ledger = list_royalties_by_run(db_path, run_id)
        assert all(r["status"] == "accrued" for r in ledger)

    def test_noop_on_settled_run(self, db_path):
        from app.storage.agent_runs import record_settlement_submission
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        confirm_settlement(db_path, run_id, "tx-final", "mock")

        # Run is now 'settled' — a stale submission record MUST NOT overwrite
        # the terminal tx_hash. Returns False (no rowcount).
        assert record_settlement_submission(
            db_path, run_id, tx_hash="stale", method="async",
        ) is False
        run = get_agent_run(db_path, run_id)
        assert run["tx_hash"] == "tx-final"
        assert run["settlement_method"] == "mock"

    def test_noop_on_accrued_run(self, db_path):
        from app.storage.agent_runs import record_settlement_submission
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        # Status is 'accrued', not 'settling'. Skipping claim_settlement.
        assert record_settlement_submission(
            db_path, run_id, tx_hash="x", method="async",
        ) is False
