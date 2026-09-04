"""Stage 2 / WP-G: the pact store in SQLite (`app/storage/pacts.py`).

Four things this file exists to pin, none of which the in-memory dict could
have satisfied:

  * the row → dict conversion reproduces the shape the routes return — every
    column round-trips, NULL base columns stay present, never-written optional
    columns stay ABSENT, and a JSON column explicitly set to None comes back
    present-with-None;
  * `transition_pact` is a conditional claim: a stale `from_status` returns
    False and changes nothing;
  * the status CHECK, not Python, is what rejects a status outside the state
    machine;
  * a pact survives the process — created and approved through one app, read
    and settled through another over the same database file.

Plus the property the lock used to provide: two threads racing to claim one
approved pact produce exactly one winner.

The existing 96 pact tests remain the oracle for the ROUTES' behaviour; this
file is about the store underneath them.
"""
import os
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import datetime, timezone

import pytest
from flask import Flask

from app.app import create_app
from app.services.mock_settlement import MockSettlementProvider
from app.storage.db import _open, init_db
from app.storage.pacts import (
    _ALL_COLUMNS,
    _BASE_COLUMNS,
    _OPTIONAL_COLUMNS,
    PACT_STATUSES,
    create_pact,
    get_pact,
    list_pacts,
    transition_pact,
    update_pact_fields,
)


# ---------------------------------------------------------------------------
# Fixtures / builders
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


def _now():
    return datetime.now(timezone.utc).isoformat()


def _pact(**overrides) -> dict:
    """A minimal pact: only the columns pact_create always fills in."""
    base = {
        "pact_id": "pact-" + os.urandom(6).hex(),
        "status": "pending",
        "task_id": "task-store-001",
        "agent_name": "客服话术生成器",
        "creator_id": "creator-1",
        "asset_id": "asset-1",
        "amount": 60.0,
        "currency": "USD",
        "created_at": _now(),
        "approved_at": None,
        "intent": "Run 客服话术生成器 for task task-store-001",
        "amount_cap": 60.0,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "payee": "0x1234567890abcdef1234567890abcdef0000abcd",
        "approved_by": None,
        "approval_method": None,
        "content_hash": "a" * 64,
    }
    base.update(overrides)
    return base


_SPLITS = {
    "creator": {"amount": 4200, "currency": "USD"},
    "platform": {"amount": 1800, "currency": "USD"},
    "tax": {"amount": 0, "currency": "USD"},
}


# ---------------------------------------------------------------------------
# Schema creation (same style as tests/test_storage.py::TestInitDb)
# ---------------------------------------------------------------------------

class TestPactsTableCreation:
    def _tables(self, path):
        with closing(_open(path)) as conn:
            return {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

    def test_init_db_creates_the_table(self, db_path):
        assert "pacts" in self._tables(db_path)

    def test_re_running_init_db_keeps_existing_pacts(self, db_path):
        """CREATE TABLE IF NOT EXISTS, so a second boot must not clobber rows."""
        created = create_pact(db_path, _pact())

        app = Flask(__name__)
        app.config["DATABASE_PATH"] = db_path
        init_db(app)  # second call must not raise…

        assert get_pact(db_path, created["pact_id"]) == created  # …or drop rows

    def test_a_database_predating_wp_g_gains_the_table(self, db_path):
        """A DB created before WP-G has no `pacts`; init_db adds it.

        There is nothing to migrate (the table is new), so _migrate has no
        clause for it — the CREATE in _create_tables, which runs on every
        init_db, is the whole upgrade path. Dropping the table reproduces
        exactly that starting state.
        """
        with closing(_open(db_path)) as conn:
            with conn:
                conn.execute("DROP TABLE pacts")
        assert "pacts" not in self._tables(db_path)

        app = Flask(__name__)
        app.config["DATABASE_PATH"] = db_path
        init_db(app)

        assert "pacts" in self._tables(db_path)
        created = create_pact(db_path, _pact())
        assert get_pact(db_path, created["pact_id"]) == created


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_every_column_round_trips(self, db_path):
        """Write one value into every column; read every one of them back."""
        pact = _pact(
            status="settled",
            approved_at="2026-09-04T10:00:00+00:00",
            approved_by="li_boss",
            approval_method="ui",
            run_id="run-abc",
            royalty_splits=_SPLITS,
            tx_hash="0xdeadbeef",
            explorer_url="https://sepolia.basescan.org/tx/0xdeadbeef",
            settled_amount=0.01,
            mcp_result={"status": "ok", "preview": ["a", "b"]},
        )
        created = create_pact(db_path, pact)

        assert created == get_pact(db_path, pact["pact_id"])
        # Nothing was dropped and nothing was invented.
        assert set(created) == set(_ALL_COLUMNS)
        for column in _ALL_COLUMNS:
            assert created[column] == pact[column], column

    def test_types_survive_storage(self, db_path):
        """Floats stay floats, ISO strings stay strings, JSON stays structured."""
        created = create_pact(db_path, _pact(amount=42.5, amount_cap=10.0))
        update_pact_fields(
            db_path, created["pact_id"],
            settled_amount=0.01, royalty_splits=_SPLITS,
        )
        stored = get_pact(db_path, created["pact_id"])

        assert isinstance(stored["amount"], float) and stored["amount"] == 42.5
        assert isinstance(stored["amount_cap"], float)
        assert isinstance(stored["settled_amount"], float)
        assert isinstance(stored["expires_at"], str)
        assert stored["expires_at"] == "2099-01-01T00:00:00+00:00"
        assert stored["royalty_splits"] == _SPLITS
        assert stored["royalty_splits"]["creator"]["amount"] == 4200

    def test_null_base_columns_are_present_as_none(self, db_path):
        """A pending pact has always shown approved_at / payee etc. as null."""
        created = create_pact(db_path, _pact(
            creator_id=None, asset_id=None, payee=None, intent=None,
            amount=None, amount_cap=None, expires_at=None, content_hash=None,
        ))
        stored = get_pact(db_path, created["pact_id"])

        for column in _BASE_COLUMNS:
            assert column in stored, f"{column} must always be present"
        for column in ("creator_id", "asset_id", "payee", "intent", "amount",
                       "amount_cap", "expires_at", "content_hash",
                       "approved_at", "approved_by", "approval_method"):
            assert stored[column] is None, column

    def test_unwritten_optional_columns_are_absent(self, db_path):
        """`run_id`/`tx_hash`/… must not appear before a settle writes them.

        The pact route contract the existing tests assert: a pending pact has
        no `run_id` key, and a legacy settle's body carries none of the x402
        keys. NULL therefore has to mean "absent", not "null".
        """
        created = create_pact(db_path, _pact())

        for column in _OPTIONAL_COLUMNS:
            assert column not in created, column
        assert created == get_pact(db_path, created["pact_id"])

    def test_a_json_column_written_as_none_is_present_as_none(self, db_path):
        """`mcp_result: null` is a real settle response (asset with no endpoint).

        This is the one case NULL-means-absent could not express, which is why
        the JSON columns store `json.dumps(None)` — the text 'null' — instead.
        """
        created = create_pact(db_path, _pact())
        update_pact_fields(db_path, created["pact_id"], mcp_result=None)
        stored = get_pact(db_path, created["pact_id"])

        assert "mcp_result" in stored
        assert stored["mcp_result"] is None
        # …and it stays distinguishable from the never-written neighbours.
        assert "royalty_splits" not in stored

    def test_get_pact_returns_none_for_an_unknown_id(self, db_path):
        assert get_pact(db_path, "pact-does-not-exist") is None

    def test_create_rejects_an_unknown_field(self, db_path):
        with pytest.raises(ValueError, match="unknown pact field"):
            create_pact(db_path, _pact(wallet_address="0xdead"))

    def test_create_requires_the_identifying_columns(self, db_path):
        pact = _pact()
        del pact["task_id"]
        with pytest.raises(ValueError, match="task_id is required"):
            create_pact(db_path, pact)

    def test_list_pacts_filters_by_status(self, db_path):
        pending = create_pact(db_path, _pact(status="pending"))
        approved = create_pact(db_path, _pact(status="approved"))

        ids = {p["pact_id"] for p in list_pacts(db_path)}
        assert ids == {pending["pact_id"], approved["pact_id"]}
        assert [p["pact_id"] for p in list_pacts(db_path, status="approved")] \
            == [approved["pact_id"]]
        assert list_pacts(db_path, status="settled") == []


# ---------------------------------------------------------------------------
# transition_pact — the conditional claim that replaced _pact_lock
# ---------------------------------------------------------------------------

class TestTransition:
    def test_a_matching_from_status_moves_the_row_and_writes_its_fields(self, db_path):
        created = create_pact(db_path, _pact(status="approved"))

        assert transition_pact(
            db_path, created["pact_id"], "approved", "settled",
            run_id="run-1", royalty_splits=_SPLITS,
        ) is True

        stored = get_pact(db_path, created["pact_id"])
        assert stored["status"] == "settled"
        assert stored["run_id"] == "run-1"
        assert stored["royalty_splits"] == _SPLITS

    def test_a_stale_from_status_returns_false_and_changes_nothing(self, db_path):
        """The losing caller must not write a byte."""
        created = create_pact(db_path, _pact(status="settled"))
        before = get_pact(db_path, created["pact_id"])

        moved = transition_pact(
            db_path, created["pact_id"], "approved", "settled",
            run_id="run-should-not-be-written",
        )

        assert moved is False
        assert get_pact(db_path, created["pact_id"]) == before
        assert "run_id" not in get_pact(db_path, created["pact_id"])

    def test_an_unknown_pact_id_returns_false(self, db_path):
        assert transition_pact(
            db_path, "pact-nope", "approved", "settled"
        ) is False

    def test_the_check_constraint_rejects_a_status_outside_the_machine(self, db_path):
        """The DB is the authority on the state machine, not the caller."""
        created = create_pact(db_path, _pact(status="approved"))

        with pytest.raises(sqlite3.IntegrityError):
            transition_pact(db_path, created["pact_id"], "approved", "paid")

        assert get_pact(db_path, created["pact_id"])["status"] == "approved"

    def test_the_check_constraint_rejects_an_unknown_status_at_insert(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            create_pact(db_path, _pact(status="in-progress"))

    def test_every_status_the_state_machine_names_is_accepted(self, db_path):
        """PACT_STATUSES and the CHECK must not drift apart."""
        for status in PACT_STATUSES:
            created = create_pact(db_path, _pact(status=status))
            assert get_pact(db_path, created["pact_id"])["status"] == status

    def test_transition_refuses_status_as_a_field(self, db_path):
        created = create_pact(db_path, _pact(status="approved"))
        with pytest.raises(ValueError, match="to_status"):
            transition_pact(
                db_path, created["pact_id"], "approved", "settled",
                status="rejected",
            )

    def test_update_pact_fields_cannot_change_the_status(self, db_path):
        """Every status change goes through a conditional transition."""
        created = create_pact(db_path, _pact(status="approved"))
        with pytest.raises(ValueError, match="status cannot be updated"):
            update_pact_fields(db_path, created["pact_id"], status="settled")

    def test_an_unknown_column_never_reaches_the_sql(self, db_path):
        created = create_pact(db_path, _pact())
        with pytest.raises(ValueError, match="unknown pact column"):
            update_pact_fields(db_path, created["pact_id"], amount_paid=1)
        with pytest.raises(ValueError, match="unknown pact column"):
            transition_pact(
                db_path, created["pact_id"], "pending", "approved",
                nonsense="x",
            )

    def test_update_pact_fields_reports_a_missing_row(self, db_path):
        assert update_pact_fields(db_path, "pact-nope", tx_hash="0x1") is False


# ---------------------------------------------------------------------------
# Restart survival — the whole point of the work package
# ---------------------------------------------------------------------------

def _app_on(db_path):
    """A fresh app instance over an existing database file."""
    return create_app(config={
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "SETTLEMENT_PROVIDER": MockSettlementProvider(),
    })


def test_a_pact_survives_the_process_that_created_it():
    """Create + approve on app A; read and settle on app B, same DB file.

    App B never saw app A's memory. Before WP-G this was a 404: the pact lived
    in a module-level dict that a restart (or a second worker) wiped.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        app_a = _app_on(db_path)
        client_a = app_a.test_client()
        created = client_a.post("/api/pact/create", json={
            "task_id": "task-restart-1",
            "agent_name": "客服话术生成器",
            "creator_id": "creator-1",
            "amount": 60,
            "currency": "USD",
        })
        assert created.status_code == 201, created.get_json()
        pact_id = created.get_json()["pact_id"]
        assert client_a.post(f"/api/pact/approve/{pact_id}").status_code == 200

        # ── the "restart": a brand-new app object over the same file ────────
        app_b = _app_on(db_path)
        client_b = app_b.test_client()

        status = client_b.get(f"/api/pact/status/{pact_id}")
        assert status.status_code == 200
        body = status.get_json()
        assert body["status"] == "approved"
        assert body["approved_at"]
        assert body["content_hash"] == created.get_json()["content_hash"]

        settled = client_b.post(f"/api/pact/settle/{pact_id}")
        assert settled.status_code == 200, settled.get_json()
        assert settled.get_json()["status"] == "settled"
        assert settled.get_json()["run_id"]

        # And app A, still alive, sees the settle app B performed.
        assert client_a.get(
            f"/api/pact/status/{pact_id}"
        ).get_json()["status"] == "settled"
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Concurrency — exactly one claim, without a process-local lock
# ---------------------------------------------------------------------------

def test_two_threads_racing_to_claim_one_pact_produce_one_winner(db_path):
    """Same shape as the route-level double-billing test, one layer down.

    `_pact_lock` used to make the check-and-set atomic within one process.
    The conditional UPDATE has to do it without any Python-side coordination,
    which is also what makes it hold across workers.
    """
    created = create_pact(db_path, _pact(status="approved"))
    pact_id = created["pact_id"]

    N = 2
    barrier = threading.Barrier(N)
    results: list[bool] = []
    results_lock = threading.Lock()

    def claim(run_id):
        barrier.wait()  # release both threads simultaneously
        won = transition_pact(
            db_path, pact_id, "approved", "settled", run_id=run_id,
        )
        with results_lock:
            results.append(won)

    threads = [
        threading.Thread(target=claim, args=(f"run-{i}",)) for i in range(N)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [False, True], results

    # One row, one terminal state, and exactly one of the two run_ids.
    with closing(_open(db_path)) as conn:
        rows = conn.execute(
            "SELECT * FROM pacts WHERE pact_id = ?", (pact_id,)
        ).fetchall()
    assert len(rows) == 1
    stored = get_pact(db_path, pact_id)
    assert stored["status"] == "settled"
    assert stored["run_id"] in {"run-0", "run-1"}
