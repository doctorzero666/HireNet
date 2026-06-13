"""
Phase 3 / U3 acceptance tests — audit log + reconciliation.

Covers:
  - audit_log DAO: insert + list ordering + invalid-event guard;
  - state-machine DAO calls emit one audit row per transition, in the
    same transaction (no audit row on a failed conditional UPDATE);
  - /api/royalty/settle full happy path lands claim + confirm rows;
  - failing provider lands claim + fail rows, error_msg persists;
  - retry path lands four rows: claim → fail → claim → confirm;
  - async provider lands claim + submit; GET /api/royalty/status that
    advances to SETTLED appends a confirm row;
  - reconcile() returns matched=True when charge_amount == ledger sum;
  - reconcile raises LookupError on unknown run_id;
  - reconcile groups ledger rows by (currency, chain) so cross-bucket
    tampering is visible as matched=False;
  - GET /api/audit/run/:id requires a JWT, returns 200 with events +
    reconcile on success, 404 on unknown run_id, 401 on no token.

Re-uses the FailingProvider / AsyncProvider helpers from
test_phase3_u1_settlement so the wiring is verified against the same
shapes the rest of the U1 suite locks in.
"""
import os
import tempfile

import pytest
from flask import Flask

from app.app import create_app
from app.services.agent_run_recording import record_agent_run
from app.services.audit import get_audit_trail, reconcile
from app.services.auth import create_token
from app.services.mock_settlement import MockSettlementProvider
from app.services.settlement import (
    SettlementProvider,
    SettlementResult,
    SettlementStatus,
)
from app.services.skill_registration import register_skill_asset
from app.storage.agent_runs import (
    claim_settlement,
    confirm_settlement,
    fail_settlement,
    get_agent_run,
    record_settlement_submission,
)
from app.storage.audit_log import (
    insert_audit_event,
    list_audit_events_by_run,
)
from app.storage.db import init_db


# Bearer token for the seeded demo user `zhang_ai` — used as the
# authenticated identity for /api/audit/run tests. The audit endpoint is
# gated by @login_required, so every route test that expects 200 must
# attach this header. Choice of user is incidental: the route does not
# yet enforce caller-owns-run (TODO in route docstring), so any valid
# JWT-bound seeded user works.
def _auth_headers(role: str = "creator") -> dict:
    return {"Authorization": f"Bearer {create_token('zhang_ai', role)}"}


# ---------------------------------------------------------------------------
# Test-only providers — mirror the shapes from the U1 suite so a U3 test
# regressing one of these paths breaks at the right layer.
# ---------------------------------------------------------------------------

class FailingProvider(SettlementProvider):
    name = "failing"

    def settle(self, payee_id, amount, currency, chain):
        return SettlementResult(success=False, error="injected failure")

    def check_status(self, tx_hash):
        return SettlementStatus.FAILED


class AsyncProvider(SettlementProvider):
    name = "async"

    def __init__(self):
        self.chain_state = SettlementStatus.SETTLING
        self.settle_calls = 0

    def settle(self, payee_id, amount, currency, chain):
        self.settle_calls += 1
        return SettlementResult(
            success=True,
            tx_hash=f"async-{self.settle_calls:04d}",
            next_status=SettlementStatus.SETTLING,
        )

    def check_status(self, tx_hash):
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


def _new_client(provider):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": path,
        "SETTLEMENT_PROVIDER": provider,
    })
    client = app.test_client()
    return client, path


@pytest.fixture
def failing_client():
    client, path = _new_client(FailingProvider())
    try:
        yield client
    finally:
        os.unlink(path)


@pytest.fixture
def async_client():
    client, path = _new_client(AsyncProvider())
    try:
        yield client
    finally:
        os.unlink(path)


def _register_asset(db_path: str, *, creator_id: str = "user_001") -> str:
    payload = {
        "name": "U3 Audit Skill",
        "description": "fixture asset for Phase 3 U3 tests",
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
    db_path = client.application.config["DATABASE_PATH"]
    creator_id = client.application.config["PHASE1_CREATOR_ID"]
    asset_id = _register_asset(db_path, creator_id=creator_id)
    return _record_run(db_path, asset_id)


# ---------------------------------------------------------------------------
# audit_log DAO
# ---------------------------------------------------------------------------

class TestAuditLogDAO:
    def test_insert_and_list_round_trip(self, db_path):
        entry_id = insert_audit_event(
            db_path, "run-1", "claim",
            status_from="accrued", status_to="settling",
        )
        rows = list_audit_events_by_run(db_path, "run-1")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == entry_id
        assert row["run_id"] == "run-1"
        assert row["event"] == "claim"
        assert row["status_from"] == "accrued"
        assert row["status_to"] == "settling"
        assert row["tx_hash"] is None
        assert row["method"] is None
        assert row["error"] is None
        assert row["created_at"]  # ISO timestamp

    def test_list_orders_by_created_at_asc(self, db_path):
        # Insert three events out of natural order; expect them returned
        # oldest-first regardless of insertion sequence.
        insert_audit_event(
            db_path, "run-2", "claim",
            status_from="accrued", status_to="settling",
        )
        insert_audit_event(
            db_path, "run-2", "fail",
            status_from="settling", status_to="failed",
            error="boom",
        )
        insert_audit_event(
            db_path, "run-2", "claim",
            status_from="failed", status_to="settling",
        )
        rows = list_audit_events_by_run(db_path, "run-2")
        assert [r["event"] for r in rows] == ["claim", "fail", "claim"]

    def test_invalid_event_raises(self, db_path):
        with pytest.raises(ValueError, match="event must be one of"):
            insert_audit_event(
                db_path, "run-3", "explode",
                status_from="settling", status_to="failed",
            )

    def test_list_unknown_run_returns_empty(self, db_path):
        assert list_audit_events_by_run(db_path, "no-such-run") == []

    def test_other_run_events_isolated(self, db_path):
        insert_audit_event(
            db_path, "run-a", "claim",
            status_from="accrued", status_to="settling",
        )
        insert_audit_event(
            db_path, "run-b", "claim",
            status_from="accrued", status_to="settling",
        )
        a_rows = list_audit_events_by_run(db_path, "run-a")
        b_rows = list_audit_events_by_run(db_path, "run-b")
        assert len(a_rows) == 1 and a_rows[0]["run_id"] == "run-a"
        assert len(b_rows) == 1 and b_rows[0]["run_id"] == "run-b"


# ---------------------------------------------------------------------------
# DAO state transitions write audit rows in the same transaction
# ---------------------------------------------------------------------------

class TestStateMachineEmitsAuditEvents:
    def test_claim_writes_one_audit_row(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)

        assert claim_settlement(db_path, run_id) is True
        events = list_audit_events_by_run(db_path, run_id)
        assert len(events) == 1
        e = events[0]
        assert e["event"] == "claim"
        assert e["status_from"] == "accrued"
        assert e["status_to"] == "settling"

    def test_claim_from_failed_records_failed_as_from(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        fail_settlement(db_path, run_id, "round-1")
        assert claim_settlement(db_path, run_id) is True

        events = list_audit_events_by_run(db_path, run_id)
        # claim (accrued→settling), fail (settling→failed), claim (failed→settling)
        assert [e["event"] for e in events] == ["claim", "fail", "claim"]
        assert events[2]["status_from"] == "failed"
        assert events[2]["status_to"] == "settling"

    def test_failed_claim_does_not_write_audit(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        # Second claim from 'settling' must fail and NOT write a row —
        # otherwise the audit trail records nonexistent transitions.
        assert claim_settlement(db_path, run_id) is False

        events = list_audit_events_by_run(db_path, run_id)
        assert len(events) == 1  # the original successful claim only

    def test_confirm_writes_audit_with_tx_hash_and_method(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        confirm_settlement(db_path, run_id, "tx-abc", "mock")

        events = list_audit_events_by_run(db_path, run_id)
        confirm_event = events[-1]
        assert confirm_event["event"] == "confirm"
        assert confirm_event["status_from"] == "settling"
        assert confirm_event["status_to"] == "settled"
        assert confirm_event["tx_hash"] == "tx-abc"
        assert confirm_event["method"] == "mock"

    def test_failed_confirm_does_not_write_audit(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        # No claim — status stays 'accrued', confirm conditional WHERE fails.
        assert confirm_settlement(db_path, run_id, "tx", "mock") == 0
        assert list_audit_events_by_run(db_path, run_id) == []

    def test_fail_writes_audit_with_error_msg(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        fail_settlement(db_path, run_id, "rail unreachable")

        events = list_audit_events_by_run(db_path, run_id)
        fail_event = events[-1]
        assert fail_event["event"] == "fail"
        assert fail_event["status_from"] == "settling"
        assert fail_event["status_to"] == "failed"
        assert fail_event["error"] == "rail unreachable"

    def test_failed_fail_does_not_write_audit(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        # status 'accrued', WHERE 'settling' fails.
        assert fail_settlement(db_path, run_id, "boom") is False
        assert list_audit_events_by_run(db_path, run_id) == []

    def test_submit_writes_audit_settling_to_settling(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        assert record_settlement_submission(
            db_path, run_id, tx_hash="async-pending", method="async",
        ) is True

        events = list_audit_events_by_run(db_path, run_id)
        submit_event = events[-1]
        assert submit_event["event"] == "submit"
        assert submit_event["status_from"] == "settling"
        assert submit_event["status_to"] == "settling"
        assert submit_event["tx_hash"] == "async-pending"
        assert submit_event["method"] == "async"

    def test_full_happy_path_emits_two_events(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)
        confirm_settlement(db_path, run_id, "tx-x", "mock")

        events = list_audit_events_by_run(db_path, run_id)
        assert [e["event"] for e in events] == ["claim", "confirm"]


# ---------------------------------------------------------------------------
# /api/royalty/settle → audit trail
# ---------------------------------------------------------------------------

class TestSettleRouteWritesAuditTrail:
    def test_happy_path_records_claim_and_confirm(self, client):
        run_id = _seed_run_via_client(client)
        client.post("/api/royalty/settle", json={"run_id": run_id})

        db_path = client.application.config["DATABASE_PATH"]
        events = list_audit_events_by_run(db_path, run_id)
        assert [e["event"] for e in events] == ["claim", "confirm"]
        # Mock provider yields tx_hash starting with "mock-"
        assert events[-1]["tx_hash"].startswith("mock-")
        assert events[-1]["method"] == "mock"

    def test_failing_provider_records_claim_and_fail(self, failing_client):
        run_id = _seed_run_via_client(failing_client)
        failing_client.post("/api/royalty/settle", json={"run_id": run_id})

        db_path = failing_client.application.config["DATABASE_PATH"]
        events = list_audit_events_by_run(db_path, run_id)
        assert [e["event"] for e in events] == ["claim", "fail"]
        assert "injected failure" in events[-1]["error"]

    def test_retry_after_failure_records_four_events(self, failing_client):
        run_id = _seed_run_via_client(failing_client)
        failing_client.post("/api/royalty/settle", json={"run_id": run_id})

        # Swap to Mock and retry: should record a second claim then confirm.
        failing_client.application.config["SETTLEMENT_PROVIDER"] = (
            MockSettlementProvider()
        )
        failing_client.post("/api/royalty/settle", json={"run_id": run_id})

        db_path = failing_client.application.config["DATABASE_PATH"]
        events = list_audit_events_by_run(db_path, run_id)
        assert [e["event"] for e in events] == [
            "claim", "fail", "claim", "confirm",
        ]
        # Second claim's from-state is 'failed', proving the retry path is
        # what was exercised (not a fresh accrued).
        assert events[2]["status_from"] == "failed"
        assert events[-1]["method"] == "mock"

    def test_async_settle_records_claim_and_submit(self, async_client):
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})

        db_path = async_client.application.config["DATABASE_PATH"]
        events = list_audit_events_by_run(db_path, run_id)
        assert [e["event"] for e in events] == ["claim", "submit"]
        # Submit row carries the rail-issued tx_hash.
        assert events[-1]["tx_hash"].startswith("async-")

    def test_async_status_advance_appends_confirm(self, async_client):
        run_id = _seed_run_via_client(async_client)
        async_client.post("/api/royalty/settle", json={"run_id": run_id})
        # Flip the simulated chain to SETTLED and let /royalty/status advance.
        provider = async_client.application.config["SETTLEMENT_PROVIDER"]
        provider.chain_state = SettlementStatus.SETTLED
        async_client.get(f"/api/royalty/status/{run_id}")

        db_path = async_client.application.config["DATABASE_PATH"]
        events = list_audit_events_by_run(db_path, run_id)
        assert [e["event"] for e in events] == ["claim", "submit", "confirm"]


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_matched_after_record_agent_run(self, db_path):
        # By construction creator + platform + tax == charge_amount, so a
        # freshly recorded run should reconcile without any settle step.
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id, charge_amount=350)
        r = reconcile(db_path, run_id)
        assert r["matched"] is True
        assert r["onchain_amount"] == 350
        assert r["ledger_amount"] == 350
        assert r["currency"] == "USD"
        assert r["settlement_status"] == "accrued"

    def test_matched_after_full_settle(self, client):
        run_id = _seed_run_via_client(client)
        client.post("/api/royalty/settle", json={"run_id": run_id})

        db_path = client.application.config["DATABASE_PATH"]
        r = reconcile(db_path, run_id)
        assert r["matched"] is True
        assert r["onchain_amount"] == r["ledger_amount"] == 100
        assert r["settlement_status"] == "settled"
        assert r["tx_hash"].startswith("mock-")

    def test_unknown_run_id_raises_lookup_error(self, db_path):
        with pytest.raises(LookupError, match="Unknown run_id"):
            reconcile(db_path, "no-such-run")

    def test_mismatched_when_ledger_tampered(self, db_path):
        """A direct UPDATE on royalty_ledger that drops a row's amount must
        be visible as matched=False — the whole point of reconciliation."""
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id, charge_amount=200)

        # Simulate corruption: zero out the platform row.
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE royalty_ledger SET amount = 0 "
                "WHERE run_id = ? AND party = 'platform'",
                (run_id,),
            )
            conn.commit()
        finally:
            conn.close()

        r = reconcile(db_path, run_id)
        assert r["matched"] is False
        assert r["onchain_amount"] == 200
        # creator (140) + tax (20) + platform tampered to 0 == 160 != 200
        assert r["ledger_amount"] < 200

    def test_groups_single_bucket_matches(self, db_path):
        """A clean run has exactly one (currency, chain) bucket — the new
        groups field surfaces it for inspection."""
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id, charge_amount=350)

        r = reconcile(db_path, run_id)
        assert r["groups"] == [
            {"currency": "USD", "chain": None, "amount": 350},
        ]
        assert r["matched"] is True

    def test_cross_currency_corruption_breaks_match(self, db_path):
        """Codex P2: a tampered row that lands in a different (currency, chain)
        bucket must surface matched=False, NOT silently pass because totals
        across buckets happen to coincide. Constitution forbids summing
        across (currency, chain)."""
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id, charge_amount=200)

        # Move the platform row to a different currency — total amount across
        # both rows is still 200, but the run's USD bucket no longer sums to
        # 200 and a phantom EUR bucket appears.
        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE royalty_ledger SET currency = 'EUR' "
                "WHERE run_id = ? AND party = 'platform'",
                (run_id,),
            )
            conn.commit()
        finally:
            conn.close()

        r = reconcile(db_path, run_id)
        # Two buckets now: USD (creator+tax) and EUR (platform). The naive
        # sum-everything reconcile would still return 200 == 200 and falsely
        # report matched=True — the per-bucket logic catches this.
        assert r["matched"] is False
        assert len(r["groups"]) == 2
        currencies = {g["currency"] for g in r["groups"]}
        assert currencies == {"USD", "EUR"}
        # Surfaced ledger_amount is the matching-bucket sum (USD only),
        # which is strictly less than charge_amount once a row leaked away.
        assert r["ledger_amount"] < 200

    def test_cross_chain_corruption_breaks_match(self, db_path):
        """Same as cross-currency but for the chain dimension — (USDC, base)
        and (USDC, ethereum) are distinct ledgers per the constitution."""
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id, charge_amount=200)

        import sqlite3
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE royalty_ledger SET chain = 'ethereum' "
                "WHERE run_id = ? AND party = 'platform'",
                (run_id,),
            )
            conn.commit()
        finally:
            conn.close()

        r = reconcile(db_path, run_id)
        assert r["matched"] is False
        assert len(r["groups"]) == 2
        chains = {g["chain"] for g in r["groups"]}
        assert chains == {None, "ethereum"}


# ---------------------------------------------------------------------------
# GET /api/audit/run/<run_id>
# ---------------------------------------------------------------------------

class TestAuditRunRoute:
    def test_returns_events_and_reconcile(self, client):
        run_id = _seed_run_via_client(client)
        client.post("/api/royalty/settle", json={"run_id": run_id})

        resp = client.get(f"/api/audit/run/{run_id}", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["run_id"] == run_id
        assert [e["event"] for e in body["events"]] == ["claim", "confirm"]
        assert body["reconcile"]["matched"] is True
        assert body["reconcile"]["onchain_amount"] == 100
        assert body["reconcile"]["ledger_amount"] == 100
        assert body["reconcile"]["settlement_status"] == "settled"

    def test_returns_empty_events_before_any_transition(self, client):
        # Recorded but never settled → reconcile still works, no events.
        db_path = client.application.config["DATABASE_PATH"]
        creator_id = client.application.config["PHASE1_CREATOR_ID"]
        asset_id = _register_asset(db_path, creator_id=creator_id)
        run_id = _record_run(db_path, asset_id)

        resp = client.get(f"/api/audit/run/{run_id}", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["events"] == []
        assert body["reconcile"]["matched"] is True
        assert body["reconcile"]["settlement_status"] == "accrued"

    def test_unknown_run_id_returns_404(self, client):
        resp = client.get("/api/audit/run/no-such-run", headers=_auth_headers())
        assert resp.status_code == 404
        assert "Unknown run_id" in resp.get_json()["error"]

    def test_failing_provider_trail_visible_in_route(self, failing_client):
        run_id = _seed_run_via_client(failing_client)
        failing_client.post("/api/royalty/settle", json={"run_id": run_id})

        body = failing_client.get(
            f"/api/audit/run/{run_id}", headers=_auth_headers(),
        ).get_json()
        assert [e["event"] for e in body["events"]] == ["claim", "fail"]
        assert "injected failure" in body["events"][-1]["error"]
        # Even on failure, ledger rows stay accrued and still sum to charge —
        # the chain-vs-ledger reconcile is independent of settle outcome.
        assert body["reconcile"]["matched"] is True
        assert body["reconcile"]["settlement_status"] == "failed"

    def test_no_token_returns_401(self, client):
        """Codex P1: audit endpoint without a Bearer token must 401."""
        run_id = _seed_run_via_client(client)
        resp = client.get(f"/api/audit/run/{run_id}")
        assert resp.status_code == 401
        assert resp.get_json() == {"error": "Authentication required"}

    def test_garbage_token_returns_401(self, client):
        run_id = _seed_run_via_client(client)
        resp = client.get(
            f"/api/audit/run/{run_id}",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# get_audit_trail thin wrapper
# ---------------------------------------------------------------------------

class TestGetAuditTrailService:
    def test_delegates_to_dao(self, db_path):
        asset_id = _register_asset(db_path)
        run_id = _record_run(db_path, asset_id)
        claim_settlement(db_path, run_id)

        events = get_audit_trail(db_path, run_id)
        assert len(events) == 1
        assert events[0]["event"] == "claim"
