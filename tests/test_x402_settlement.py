"""Stage 2 / WP-D: the x402 ledger path and the x402 settlement provider.

Part 1 (this half of the file) covers `record_agent_run(presettled=...)`:
the run row, the three ledger rows, the audit event, the unit invariant, and
— the important one — that a run recorded WITHOUT `presettled` is identical
to one recorded before WP-D existed.

Part 2 covers X402SettlementProvider (added in the same work package, see
below) with a fake `w3`.

NOTHING HERE TOUCHES A CHAIN. `no_real_network` (autouse) fails the test if a
socket is opened or a real `Web3.HTTPProvider` is constructed, so a missing
fake shows up as a failure rather than as a live call to sepolia.base.org.
Green tests here prove decoding and control flow; they prove nothing about
Base Sepolia.
"""
import os
import socket
import sqlite3
import tempfile

import pytest
from flask import Flask

from app.services.agent_run_recording import (
    USDC_ATOMIC_PER_CENT,
    X402_FEE_RECEIVABLE_METHOD,
    X402_METHOD,
    record_agent_run,
)
from app.services.skill_registration import register_skill_asset
from app.services.x402_gate import DEFAULT_NETWORK, DEFAULT_USDC_ADDRESS
from app.storage.agent_runs import get_agent_run
from app.storage.audit_log import list_audit_events_by_run
from app.storage.db import init_db
from app.storage.royalty_ledger import list_royalties_by_run

TX_HASH = "0x" + "ab" * 32
PAYER = "0x1111111111111111111111111111111111111111"
CREATOR_WALLET = "0xf2E28A84e8d51ca87CB50768a0Ebe0E29F53F7B7"


# ---------------------------------------------------------------------------
# Guards + fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Fail loudly on any socket, and on any real HTTP RPC provider.

    The second half matters more than the first: X402SettlementProvider's
    only default dependency is `Web3(Web3.HTTPProvider(rpc_url))`, so making
    the constructor itself explode is what proves every test below is running
    against an injected fake.
    """
    def _boom(*args, **kwargs):
        raise AssertionError(
            "x402 settlement tests must not touch the network; inject a fake "
            "w3 instead of letting the provider build an HTTPProvider."
        )

    monkeypatch.setattr(socket.socket, "connect", _boom)

    from web3 import Web3
    monkeypatch.setattr(Web3, "HTTPProvider", _boom)


@pytest.fixture(autouse=True)
def clean_x402_env(monkeypatch):
    """Never inherit the operator's .env for network / asset / RPC / explorer."""
    for key in (
        "X402_NETWORK",
        "X402_USDC_ADDRESS",
        "X402_RPC_URL",
        "X402_EXPLORER_TX_URL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = path
    init_db(app)
    yield path
    os.unlink(path)


def _register_asset(db_path, *, creator_id="zhang_ai", split=(7000, 3000),
                    price_amount=100, currency="USD"):
    """Register through the real path so content_hash etc. are genuine."""
    payload = {
        "name": "x402 test asset",
        "description": "asset used by the WP-D ledger tests",
        "type": "agent",
        "io_schema": {"input": {}, "output": {}},
        "price_amount": price_amount,
        "price_currency": currency,
        "split_rule": {"creator": split[0], "platform": split[1]},
        "wallet_address": CREATOR_WALLET,
    }
    return register_skill_asset(db_path, payload, creator_id)["skill_id"]


def _payment(charge_amount=100, **overrides):
    """The `payment` dict x402_payer.pay_and_retry returns, by construction.

    amount_atomic is a STRING here because that is what the payer carries off
    the wire (PaymentRequirements.amount is a decimal string) — the recorder
    must cope with that shape, not just with an int.
    """
    payment = {
        "method": "x402",
        "tx_hash": TX_HASH,
        "network": DEFAULT_NETWORK,
        "payer": PAYER,
        "payee": CREATOR_WALLET,
        "amount_atomic": str(charge_amount * USDC_ATOMIC_PER_CENT),
        "asset": DEFAULT_USDC_ADDRESS,
        "settle_success": True,
    }
    payment.update(overrides)
    return payment


def _record(db_path, asset_id, *, charge_amount=100, presettled=None):
    return record_agent_run(
        db_path,
        agent_name="x402 test agent",
        caller_id="li_boss",
        task_id="task-x402-1",
        asset_id=asset_id,
        charge_amount=charge_amount,
        charge_currency="USD",
        success=True,
        presettled=presettled,
    )


# ---------------------------------------------------------------------------
# Part 1a — the pre-settled run row
# ---------------------------------------------------------------------------

class TestPresettledRunRow:

    def test_run_is_settling_with_method_and_tx_hash(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())

        run = get_agent_run(db_path, result["run_id"])
        assert run["settlement_status"] == "settling"
        assert run["settlement_method"] == X402_METHOD
        assert run["tx_hash"] == TX_HASH

    def test_run_payment_method_is_on_chain(self, db_path):
        """Real USDC moved, so 'ledger_only' would be a lie."""
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())
        assert get_agent_run(db_path, result["run_id"])["payment_method"] == "on_chain"

    def test_settlement_meta_round_trips_the_payment(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())

        meta = get_agent_run(db_path, result["run_id"])["settlement_meta"]
        assert meta["method"] == "x402"
        assert meta["tx_hash"] == TX_HASH
        assert meta["network"] == DEFAULT_NETWORK
        assert meta["payer"] == PAYER
        assert meta["payee"] == CREATOR_WALLET
        assert meta["asset"] == DEFAULT_USDC_ADDRESS
        # normalised to int on the way in, so check_status can compare it to a
        # decoded log value without re-parsing
        assert meta["amount_atomic"] == 100 * USDC_ATOMIC_PER_CENT

    def test_settlement_meta_drops_unknown_keys(self, db_path):
        """`settle_success` is the payer's word, not a fact we persist."""
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())
        meta = get_agent_run(db_path, result["run_id"])["settlement_meta"]
        assert "settle_success" not in meta


# ---------------------------------------------------------------------------
# Part 1b — the ledger rows
# ---------------------------------------------------------------------------

class TestPresettledLedgerRows:

    def test_creator_row_is_settling_and_carries_the_tx(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())

        rows = {r["party"]: r for r in list_royalties_by_run(db_path, result["run_id"])}
        creator = rows["creator"]
        assert creator["status"] == "settling"
        assert creator["settlement_method"] == X402_METHOD
        assert creator["tx_hash"] == TX_HASH
        assert creator["note"] is None

    def test_platform_row_stays_accrued_as_a_receivable(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())

        platform = {
            r["party"]: r for r in list_royalties_by_run(db_path, result["run_id"])
        }["platform"]
        assert platform["status"] == "accrued"
        assert platform["settlement_method"] == X402_FEE_RECEIVABLE_METHOD
        # No tx_hash: claiming one would imply an on-chain payment that x402
        # `exact` (single payee) structurally cannot have made.
        assert platform["tx_hash"] is None
        assert "receivable from the creator" in platform["note"]
        assert TX_HASH in platform["note"]

    def test_tax_row_is_also_a_receivable(self, db_path):
        """Same reasoning as platform — only ONE payee got paid on-chain."""
        asset_id = _register_asset(db_path)
        # Registration only accepts 2-leg rules through the public payload, so
        # swap in the 3-leg rule (creator 7000 / platform 2000 / tax 1000)
        # directly — it still sums to 10000, which is what record_agent_run
        # re-validates.
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE skill_assets SET split_rule = ? WHERE id = ?",
                ('{"creator": 7000, "platform": 2000, "tax": 1000}', asset_id),
            )
            conn.commit()
        finally:
            conn.close()

        result = _record(db_path, asset_id, presettled=_payment())
        tax = {
            r["party"]: r for r in list_royalties_by_run(db_path, result["run_id"])
        }["tax"]
        assert tax["status"] == "accrued"
        assert tax["settlement_method"] == X402_FEE_RECEIVABLE_METHOD
        assert tax["amount"] == 10

    def test_split_amounts_still_sum_to_charge_amount(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, charge_amount=333,
                         presettled=_payment(charge_amount=333))

        rows = list_royalties_by_run(db_path, result["run_id"])
        assert sum(r["amount"] for r in rows) == 333

    def test_split_amounts_identical_to_the_ledger_only_path(self, db_path):
        """Pre-settling changes settlement columns only; never the money."""
        asset_id = _register_asset(db_path)
        legacy = _record(db_path, asset_id, charge_amount=333)
        paid = _record(db_path, asset_id, charge_amount=333,
                       presettled=_payment(charge_amount=333))

        by_party = lambda run_id: {
            r["party"]: r["amount"]
            for r in list_royalties_by_run(db_path, run_id)
        }
        assert by_party(paid["run_id"]) == by_party(legacy["run_id"])


# ---------------------------------------------------------------------------
# Part 1c — the audit trail
# ---------------------------------------------------------------------------

class TestPresettledAuditTrail:

    def test_one_submit_event_with_tx_hash_and_network(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment())

        events = list_audit_events_by_run(db_path, result["run_id"])
        assert len(events) == 1
        event = events[0]
        assert event["event"] == "submit"
        # No prior state: the run was born 'settling', it was never claimed.
        assert event["status_from"] is None
        assert event["status_to"] == "settling"
        assert event["method"] == X402_METHOD
        assert event["tx_hash"] == TX_HASH
        assert event["network"] == DEFAULT_NETWORK

    def test_ledger_only_run_still_writes_no_audit_row(self, db_path):
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id)
        assert list_audit_events_by_run(db_path, result["run_id"]) == []


# ---------------------------------------------------------------------------
# Part 1d — refusals. Every one of these means "the payment and the bill
# disagree", and the only safe answer is to record neither.
# ---------------------------------------------------------------------------

class TestPresettledRefusals:

    def test_amount_atomic_too_small_is_refused(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError, match="does not match charge_amount"):
            _record(db_path, asset_id, charge_amount=100,
                    presettled=_payment(amount_atomic="999999"))

    def test_amount_atomic_off_by_a_factor_of_100_is_refused(self, db_path):
        """The classic cents/atomic confusion: 100 cents is 1_000_000, not 10_000."""
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError, match="does not match charge_amount"):
            _record(db_path, asset_id, charge_amount=100,
                    presettled=_payment(amount_atomic="10000"))

    def test_mismatch_writes_nothing_at_all(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError):
            _record(db_path, asset_id, presettled=_payment(amount_atomic="1"))

        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM royalty_ledger").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
        finally:
            conn.close()

    def test_float_amount_atomic_is_refused(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError, match="amount_atomic"):
            _record(db_path, asset_id,
                    presettled=_payment(amount_atomic=1_000_000.0))

    def test_unknown_method_is_refused(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError, match="presettled.method"):
            _record(db_path, asset_id, presettled=_payment(method="lightning"))

    def test_foreign_asset_contract_is_refused(self, db_path):
        asset_id = _register_asset(db_path)
        with pytest.raises(ValueError, match="not the configured USDC contract"):
            _record(db_path, asset_id,
                    presettled=_payment(asset="0x" + "9" * 40))

    def test_non_usd_currency_is_refused(self, db_path):
        asset_id = _register_asset(db_path, currency="EUR")
        with pytest.raises(ValueError, match="USD/USDC-compatible"):
            record_agent_run(
                db_path,
                agent_name="a", caller_id="li_boss", task_id="t",
                asset_id=asset_id, charge_amount=100, charge_currency="EUR",
                success=True, presettled=_payment(),
            )

    @pytest.mark.parametrize("field", ["tx_hash", "network", "payer", "payee", "asset"])
    def test_missing_required_field_is_refused(self, db_path, field):
        asset_id = _register_asset(db_path)
        payment = _payment()
        del payment[field]
        with pytest.raises(ValueError, match=f"presettled.{field}"):
            _record(db_path, asset_id, presettled=payment)

    def test_env_override_of_usdc_address_is_honoured(self, db_path, monkeypatch):
        """The accepted contract follows X402_USDC_ADDRESS, not a hardcode."""
        other = "0x" + "7" * 40
        monkeypatch.setenv("X402_USDC_ADDRESS", other)
        asset_id = _register_asset(db_path)
        result = _record(db_path, asset_id, presettled=_payment(asset=other))
        assert get_agent_run(db_path, result["run_id"])["settlement_status"] == "settling"


# ---------------------------------------------------------------------------
# Part 1e — the untouched legacy path. This is the regression test that
# matters: WP-D must be invisible to every existing caller.
# ---------------------------------------------------------------------------

_VOLATILE_RUN_KEYS = {"run_id", "created_at", "task_id"}


class TestLedgerOnlyPathUnchanged:

    def test_run_row_matches_a_run_recorded_the_old_way(self, db_path):
        """Field-by-field comparison against a run recorded with no presettled."""
        asset_id = _register_asset(db_path)
        a = get_agent_run(db_path, _record(db_path, asset_id)["run_id"])
        b = get_agent_run(db_path, _record(db_path, asset_id)["run_id"])

        stripped_a = {k: v for k, v in a.items() if k not in _VOLATILE_RUN_KEYS}
        stripped_b = {k: v for k, v in b.items() if k not in _VOLATILE_RUN_KEYS}
        assert stripped_a == stripped_b

    def test_run_row_keeps_the_pre_wp_d_defaults(self, db_path):
        asset_id = _register_asset(db_path)
        run = get_agent_run(db_path, _record(db_path, asset_id)["run_id"])
        assert run["settlement_status"] == "accrued"
        assert run["payment_method"] == "ledger_only"
        assert run["settlement_method"] == "ledger_only"
        assert run["tx_hash"] is None
        assert run["settlement_meta"] is None

    def test_ledger_rows_keep_the_pre_wp_d_defaults(self, db_path):
        asset_id = _register_asset(db_path)
        rows = list_royalties_by_run(db_path, _record(db_path, asset_id)["run_id"])
        assert len(rows) == 3
        for row in rows:
            assert row["status"] == "accrued"
            assert row["settlement_method"] is None
            assert row["tx_hash"] is None
            assert row["note"] is None


# ---------------------------------------------------------------------------
# Part 1f — migrating a database written by the code at HEAD~ (Phase 3 / U3
# schema: agent_runs already rebuilt, royalty_ledger and audit_log not).
# ---------------------------------------------------------------------------

# Verbatim from app/storage/db.py as of commit 7bac0fd (pre-WP-D), trimmed to
# the three tables WP-D touches. If a migration test ever needs updating
# because THIS changed, the migration is no longer backward compatible.
_PRE_WP_D_DDL = """
    CREATE TABLE agent_runs (
        run_id            TEXT    PRIMARY KEY,
        agent_name        TEXT    NOT NULL,
        caller_id         TEXT    NOT NULL,
        task_id           TEXT    NOT NULL,
        input_tokens      INTEGER,
        output_tokens     INTEGER,
        llm_cost_usd      TEXT,
        time_ms           INTEGER,
        success           INTEGER NOT NULL CHECK (success IN (0, 1)),
        asset_ids         TEXT    NOT NULL,
        royalty_splits    TEXT    NOT NULL,
        charge_amount     INTEGER NOT NULL CHECK (charge_amount >= 0),
        charge_currency   TEXT    NOT NULL,
        charge_chain      TEXT,
        payment_method    TEXT    NOT NULL CHECK (payment_method IN ('ledger_only', 'on_chain', 'fiat')),
        settlement_status TEXT    NOT NULL CHECK (settlement_status IN ('accrued', 'settling', 'settled', 'failed')),
        settlement_method TEXT    NOT NULL DEFAULT 'ledger_only',
        tx_hash           TEXT,
        created_at        TEXT    NOT NULL
    );
    CREATE TABLE royalty_ledger (
        id         TEXT    PRIMARY KEY,
        run_id     TEXT    NOT NULL,
        creator_id TEXT    NOT NULL,
        payee_id   TEXT    NOT NULL,
        party      TEXT    NOT NULL CHECK (party IN ('creator', 'platform', 'tax')),
        asset_id   TEXT    NOT NULL,
        amount     INTEGER NOT NULL CHECK (amount >= 0),
        currency   TEXT    NOT NULL,
        chain      TEXT,
        status     TEXT    NOT NULL CHECK (status IN ('accrued', 'settled')),
        created_at TEXT    NOT NULL
    );
    CREATE TABLE audit_log (
        id            TEXT    PRIMARY KEY,
        run_id        TEXT    NOT NULL,
        event_ordinal INTEGER NOT NULL,
        event         TEXT    NOT NULL CHECK (event IN ('claim', 'submit', 'confirm', 'fail')),
        status_from   TEXT,
        status_to     TEXT    NOT NULL,
        method        TEXT,
        tx_hash       TEXT,
        error         TEXT,
        created_at    TEXT    NOT NULL
    );
"""


@pytest.fixture
def pre_wp_d_db():
    """A DB at the pre-WP-D schema carrying one row in each affected table."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_PRE_WP_D_DDL)
        conn.execute(
            "INSERT INTO agent_runs (run_id, agent_name, caller_id, task_id, "
            "success, asset_ids, royalty_splits, charge_amount, charge_currency, "
            "payment_method, settlement_status, settlement_method, tx_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old-run", "legacy", "li_boss", "t-1", 1, '["a-1"]', "{}", 100,
             "USD", "ledger_only", "settled", "mock", "mock-deadbeef",
             "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO royalty_ledger (id, run_id, creator_id, payee_id, party, "
            "asset_id, amount, currency, chain, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old-entry", "old-run", "zhang_ai", "zhang_ai", "creator", "a-1",
             70, "USD", None, "settled", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO audit_log (id, run_id, event_ordinal, event, status_from, "
            "status_to, method, tx_hash, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("old-audit", "old-run", 1, "confirm", "settling", "settled", "mock",
             "mock-deadbeef", None, "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    yield path
    os.unlink(path)


def _columns(path, table):
    # PRAGMA takes no bind parameters; `table` is a literal from this file.
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


class TestWpDMigration:

    @pytest.fixture(autouse=True)
    def migrated(self, pre_wp_d_db):
        app = Flask(__name__)
        app.config["DATABASE_PATH"] = pre_wp_d_db
        init_db(app)
        return pre_wp_d_db

    def test_new_columns_exist(self, pre_wp_d_db):
        assert "settlement_meta" in _columns(pre_wp_d_db, "agent_runs")
        assert "network" in _columns(pre_wp_d_db, "audit_log")
        assert {"settlement_method", "tx_hash", "note"} <= _columns(
            pre_wp_d_db, "royalty_ledger"
        )

    def test_existing_run_row_is_untouched_except_the_new_null_column(
        self, pre_wp_d_db
    ):
        run = get_agent_run(pre_wp_d_db, "old-run")
        assert run["settlement_status"] == "settled"
        assert run["settlement_method"] == "mock"
        assert run["tx_hash"] == "mock-deadbeef"
        assert run["charge_amount"] == 100
        assert run["created_at"] == "2026-01-01T00:00:00+00:00"
        assert run["settlement_meta"] is None

    def test_existing_ledger_row_is_untouched_except_new_null_columns(
        self, pre_wp_d_db
    ):
        rows = list_royalties_by_run(pre_wp_d_db, "old-run")
        assert len(rows) == 1
        row = rows[0]
        assert row["amount"] == 70
        assert row["status"] == "settled"
        assert row["party"] == "creator"
        assert row["created_at"] == "2026-01-01T00:00:00+00:00"
        assert row["settlement_method"] is None
        assert row["tx_hash"] is None
        assert row["note"] is None

    def test_existing_audit_row_is_untouched_except_new_null_column(
        self, pre_wp_d_db
    ):
        events = list_audit_events_by_run(pre_wp_d_db, "old-run")
        assert len(events) == 1
        assert events[0]["event"] == "confirm"
        assert events[0]["tx_hash"] == "mock-deadbeef"
        assert events[0]["network"] is None

    def test_widened_ledger_status_check_accepts_settling(self, pre_wp_d_db):
        conn = sqlite3.connect(pre_wp_d_db)
        try:
            conn.execute(
                "UPDATE royalty_ledger SET status = 'settling' WHERE id = 'old-entry'"
            )
            conn.commit()
            assert conn.execute(
                "SELECT status FROM royalty_ledger WHERE id = 'old-entry'"
            ).fetchone()[0] == "settling"
        finally:
            conn.close()

    def test_ledger_status_check_still_rejects_garbage(self, pre_wp_d_db):
        conn = sqlite3.connect(pre_wp_d_db)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE royalty_ledger SET status = 'paid' WHERE id = 'old-entry'"
                )
        finally:
            conn.close()

    def test_migration_is_idempotent(self, pre_wp_d_db):
        app = Flask(__name__)
        app.config["DATABASE_PATH"] = pre_wp_d_db
        init_db(app)
        init_db(app)
        assert len(list_royalties_by_run(pre_wp_d_db, "old-run")) == 1
