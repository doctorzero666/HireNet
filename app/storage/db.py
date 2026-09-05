import os
import sqlite3
from contextlib import closing

from flask import Flask


def _open(path: str) -> sqlite3.Connection:
    """Open a connection with row_factory set. Internal use only."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _require_nonneg_int(value: object, field: str) -> int:
    """Raise if value is not a non-negative plain int (bools and floats rejected)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be a non-negative int (basis points), got {type(value).__name__!r}")
    if value < 0:
        raise ValueError(f"{field} must be >= 0, got {value}")
    return value


def _create_tables(conn: sqlite3.Connection) -> None:
    # CHECK constraints enforce domain rules at the DB layer.
    # If upgrading an existing hirenet.db, delete the file so init_db recreates
    # it with these constraints — SQLite does not support ADD CONSTRAINT.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS skill_assets (
            id              TEXT    PRIMARY KEY,
            creator_id      TEXT    NOT NULL,
            name            TEXT    NOT NULL,
            description     TEXT    NOT NULL,
            -- WP-I18N-2 / D-C: optional English display text. Nullable on
            -- purpose: an asset registered through POST /api/skills/register
            -- has no English side, and the API layer falls back to name /
            -- description. NOT part of content_hash (provenance would break)
            -- and NOT part of the bootstrap idempotency match.
            name_en         TEXT,
            description_en  TEXT,
            type            TEXT    NOT NULL,
            endpoint_url    TEXT,
            io_schema       TEXT    NOT NULL,
            price_amount    INTEGER NOT NULL CHECK (price_amount >= 0),
            price_currency  TEXT    NOT NULL,
            price_chain     TEXT,
            split_rule      TEXT    NOT NULL,
            content_hash    TEXT    NOT NULL,
            wallet_address  TEXT,
            created_at      TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
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
            -- Stage 2 / WP-D: opaque JSON blob describing a pay-at-invocation
            -- rail's own view of the payment (x402: network / payer / payee /
            -- amount_atomic / asset). Nullable — every run recorded before
            -- WP-D and every ledger-only run leaves it NULL. It exists so the
            -- x402 settlement provider can look up what the chain is EXPECTED
            -- to show for this tx_hash without a second table.
            settlement_meta   TEXT,
            created_at        TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS royalty_ledger (
            id         TEXT    PRIMARY KEY,
            run_id     TEXT    NOT NULL,
            creator_id TEXT    NOT NULL,
            payee_id   TEXT    NOT NULL,
            party      TEXT    NOT NULL CHECK (party IN ('creator', 'platform', 'tax')),
            asset_id   TEXT    NOT NULL,
            amount     INTEGER NOT NULL CHECK (amount >= 0),
            currency   TEXT    NOT NULL,
            chain      TEXT,
            -- Stage 2 / WP-D widened this from ('accrued','settled'). 'settling'
            -- is only ever written by the x402 pre-settled path: the payer moved
            -- the money at invocation time, so the creator's share is in flight
            -- on-chain but not yet confirmed. Every pre-WP-D writer still writes
            -- only 'accrued' / 'settled'.
            status     TEXT    NOT NULL CHECK (status IN ('accrued', 'settling', 'settled')),
            -- Stage 2 / WP-D, all nullable (NULL on every pre-WP-D row):
            --   settlement_method — which rail moved (or owes) this share;
            --   tx_hash           — the rail's tx id for this share, if any;
            --   note              — free text; used to record that the platform
            --                       fee is a RECEIVABLE from the creator because
            --                       x402 `exact` pays exactly one payee.
            settlement_method TEXT,
            tx_hash           TEXT,
            note              TEXT,
            created_at TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id            TEXT    PRIMARY KEY,
            name          TEXT    NOT NULL,
            -- WP-I18N-2 / D-C: English display name for the seeded demo
            -- identities. Nullable — a self-registered user has only `name`.
            name_en       TEXT,
            role          TEXT    NOT NULL CHECK (role IN ('enterprise', 'creator', 'jobseeker')),
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id            TEXT    PRIMARY KEY,
            run_id        TEXT    NOT NULL,
            event_ordinal INTEGER NOT NULL,
            event         TEXT    NOT NULL CHECK (event IN ('claim', 'submit', 'confirm', 'fail')),
            status_from   TEXT,
            status_to     TEXT    NOT NULL,
            method        TEXT,
            tx_hash       TEXT,
            -- Stage 2 / WP-D: CAIP-2 network the tx_hash lives on (e.g.
            -- "eip155:84532"). Nullable; only the x402 pre-settled event
            -- fills it in today.
            network       TEXT,
            error         TEXT,
            created_at    TEXT    NOT NULL
        );

        -- Stage 1 / D9: one row per step of a task-analysis run (v2 pipeline
        -- only). Columns mirror app/schemas/analysis_trace.json exactly; the
        -- DAO validates against that schema before inserting.
        -- No FK to a session: analysis sessions live in a process-local dict
        -- (app/app.py:23), so there is no table to reference yet.
        CREATE TABLE IF NOT EXISTS analysis_traces (
            trace_id      TEXT    PRIMARY KEY,
            session_id    TEXT    NOT NULL,
            step_no       INTEGER NOT NULL CHECK (step_no >= 0),
            stage         TEXT    NOT NULL CHECK (stage IN ('clarify', 'extract', 'decompose', 'evaluate', 'decide', 'jd')),
            model         TEXT    NOT NULL,
            prompt_json   TEXT    NOT NULL,
            response_text TEXT    NOT NULL,
            parsed_ok     INTEGER NOT NULL CHECK (parsed_ok IN (0, 1)),
            input_tokens  INTEGER,
            output_tokens INTEGER,
            time_ms       INTEGER,
            created_at    TEXT    NOT NULL
        );

        -- Stage 2 / WP-G: the authorization mandate ("pact") store, replacing
        -- the process-local `pact_sessions` dict in app/app.py. One row per
        -- mandate; the DAO is app/storage/pacts.py.
        --
        -- A NEW table, so there is nothing to migrate: _migrate() has no
        -- clause for it and existing databases pick it up here (this whole
        -- script runs on every init_db, and CREATE TABLE IF NOT EXISTS makes
        -- that idempotent).
        --
        -- The status CHECK is the state machine:
        --   pending → approved → settling → settled   (x402 rail)
        --   pending → approved → settled              (legacy rail)
        --   pending → rejected                        (terminal)
        -- `settling` means an invocation that IS the payment is in flight.
        -- Every status change goes through a conditional
        -- `UPDATE … WHERE pact_id = ? AND status = ?`, whose rowcount is what
        -- makes settling a pact exactly-once across threads and processes
        -- (the same claim pattern as agent_runs.claim_settlement).
        --
        -- Nullable columns fall in two groups (see app/storage/pacts.py):
        -- the ones a pact carries from creation with a NULL value, and the
        -- ones written later, where NULL means the key is absent from the
        -- API response entirely. royalty_splits / mcp_result hold JSON.
        CREATE TABLE IF NOT EXISTS pacts (
            pact_id         TEXT    PRIMARY KEY,
            status          TEXT    NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'settling', 'settled')),
            task_id         TEXT    NOT NULL,
            agent_name      TEXT    NOT NULL,
            creator_id      TEXT,
            asset_id        TEXT,
            -- Dollar units (floats), matching the pact object; settle converts
            -- to integer cents via Decimal before anything is billed.
            amount          REAL    CHECK (amount IS NULL OR amount > 0),
            currency        TEXT    NOT NULL,
            created_at      TEXT    NOT NULL,
            approved_at     TEXT,
            -- AP2-shaped mandate fields (Stage 2 / WP-A).
            intent          TEXT,
            amount_cap      REAL    CHECK (amount_cap IS NULL OR amount_cap > 0),
            expires_at      TEXT,
            payee           TEXT,
            approved_by     TEXT,
            approval_method TEXT,
            content_hash    TEXT,
            -- Written at settle time only.
            run_id          TEXT,
            royalty_splits  TEXT,
            tx_hash         TEXT,
            explorer_url    TEXT,
            settled_amount  REAL    CHECK (settled_amount IS NULL OR settled_amount >= 0),
            mcp_result      TEXT,
            -- Stage 2 / WP-R (review F2). Written when a settle signed an
            -- authorization and never learned its fate: the pact STAYS at
            -- 'settling' (so no retry can sign a second one) and these two
            -- columns are the whole reconciliation record. last_error is
            -- prose; payment_pending is the JSON identity of the authorization
            -- in limbo ({nonce, payee, amount_atomic, error}) — the nonce is
            -- the token's replay key, so it is what an operator looks up
            -- on-chain. Both NULL on every other pact.
            last_error      TEXT,
            payment_pending TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_audit_log_run_id ON audit_log (run_id);
        CREATE INDEX IF NOT EXISTS idx_analysis_traces_session ON analysis_traces (session_id, step_no);
    """)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that were introduced after U2, if they are missing from an existing table.

    SQLite does not support ADD COLUMN with NOT NULL unless a DEFAULT is provided, so
    the new columns are added as nullable TEXT here. The service layer guarantees that
    every new write supplies a valid value, preserving the effective constraint.
    Pre-existing rows (U2 data) have their type backfilled to 'skill'.

    Phase 2 / U2: royalty_ledger gains payee_id + party so each split party gets its
    own row. Pre-existing rows are backfilled to ('creator', creator_id) — they were
    the single creator row written in Phase 1.

    Phase 3 / U1: agent_runs.settlement_status expands from ('accrued','settled')
    to ('accrued','settling','settled','failed') so a multi-step provider call
    can be tracked. SQLite cannot ALTER a CHECK constraint, so we rebuild the
    table (CREATE new → INSERT SELECT → DROP old → RENAME). We also add
    settlement_method (DEFAULT 'ledger_only') and tx_hash (nullable) columns
    in the same rebuild so existing rows naturally land on safe defaults.

    Stage 2 / WP-D: five additive, nullable changes for the x402 pre-settled
    path. agent_runs gains settlement_meta (JSON blob, NULL for every existing
    run); audit_log gains network; royalty_ledger gains settlement_method,
    tx_hash and note AND has its status CHECK widened to allow 'settling' —
    which, as with agent_runs above, means a table rebuild. Every pre-existing
    row carries over unchanged with NULL in the new columns; no existing status
    value is rewritten.

    Stage 2 / WP-R: pacts gains last_error + payment_pending (both nullable
    TEXT, no backfill) so a settle whose signed authorization went out with an
    unknown outcome can be left at 'settling' WITH a reconciliation record
    instead of being reset and re-signed.

    WP-I18N-2 / D-C: skill_assets gains name_en + description_en and users
    gains name_en — three nullable TEXT columns, no SQL default and no
    backfill here. NULL means "no English text for this row", which the API
    layer renders as the original `name` / `description`. The English strings
    for the bootstrapped demo rows are written by the bootstraps themselves
    (`UPDATE ... WHERE name_en IS NULL`), NOT here and NOT through
    `compute_content_hash` or the bootstrap `expected` idempotency match —
    putting them in either would fork every already-deployed row into a
    duplicate on the next boot.

    Crash-safety: every ALTER + backfill UPDATE runs inside a single explicit
    transaction. Python's sqlite3 module auto-commits before DDL by default,
    which would otherwise leave the DB in a half-migrated state if a later
    step crashed. We flip isolation_level to None so BEGIN / COMMIT / ROLLBACK
    apply to the whole batch — any failure rolls back to the pre-migration
    schema instead of stranding the DB between versions.
    """
    skill_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(skill_assets)").fetchall()
    }
    ledger_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(royalty_ledger)").fetchall()
    }
    agent_run_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(agent_runs)").fetchall()
    }
    audit_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()
    }
    # Same "empty set = table absent" gate as `pact_cols` below: a hand-built
    # pre-users database must not blow up on an ALTER of a missing table.
    user_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    # Empty set = the table does not exist yet. _migrate always runs after
    # _create_tables (see init_db), so that only happens when a caller migrates
    # a hand-built pre-WP-G database; ALTERing a missing table would explode,
    # so the pacts clause below is gated on the table being there at all.
    pact_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(pacts)").fetchall()
    }
    # Stage 2 / WP-R: two nullable TEXT columns for the "authorization signed,
    # outcome unknown" record. Additive; every existing pact reads NULL, which
    # the DAO turns back into "the key is absent from the API response".
    pact_wpr_columns = [
        column for column in ("last_error", "payment_pending")
        if pact_cols and column not in pact_cols
    ]

    # WP-I18N-2 / D-C: plain nullable ADD COLUMNs, no backfill, no CHECK to
    # widen. `skill_cols` is never empty here (skill_assets is the one table
    # every legacy database has), `user_cols` is gated like `pact_cols`.
    i18n_skill_columns = [
        column for column in ("name_en", "description_en")
        if skill_cols and column not in skill_cols
    ]
    i18n_user_columns = [
        column for column in ("name_en",)
        if user_cols and column not in user_cols
    ]

    # Stage 2 / WP-D: agent_runs.settlement_meta, audit_log.network and the
    # three royalty_ledger columns (+ the widened status CHECK) are all
    # additive and nullable. `rebuild_agent_runs` / `rebuild_ledger` decide
    # between "the Phase 3 table rebuild already covers this" and "plain
    # ALTER on an already-modern table".
    rebuild_agent_runs = (
        "settlement_method" not in agent_run_cols
        or "tx_hash" not in agent_run_cols
    )
    # The ledger status CHECK cannot be ALTERed in SQLite, so gaining any of
    # the WP-D columns triggers a full table rebuild with the wider CHECK.
    rebuild_ledger = (
        "settlement_method" not in ledger_cols
        or "tx_hash" not in ledger_cols
        or "note" not in ledger_cols
    )

    pending = (
        "type" not in skill_cols
        or "endpoint_url" not in skill_cols
        or "wallet_address" not in skill_cols
        or "payee_id" not in ledger_cols
        or "party" not in ledger_cols
        or "event_ordinal" not in audit_cols
        or "network" not in audit_cols
        or "settlement_meta" not in agent_run_cols
        or rebuild_agent_runs
        or rebuild_ledger
        or bool(pact_wpr_columns)
        or bool(i18n_skill_columns)
        or bool(i18n_user_columns)
    )
    if not pending:
        return

    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN")
        try:
            if "type" not in skill_cols:
                conn.execute("ALTER TABLE skill_assets ADD COLUMN type TEXT")
                conn.execute(
                    "UPDATE skill_assets SET type = 'skill' WHERE type IS NULL"
                )

            if "endpoint_url" not in skill_cols:
                conn.execute(
                    "ALTER TABLE skill_assets ADD COLUMN endpoint_url TEXT"
                )

            if "wallet_address" not in skill_cols:
                # MCP wallet integration: every SkillAsset can declare a
                # recipient wallet so Sepolia settlement transfers ETH to the
                # Agent's address instead of the platform's faucet sender.
                # Nullable for backward compat — legacy rows + assets without
                # a wallet fall back to SEPOLIA_TO_ADDRESS at settle time.
                conn.execute(
                    "ALTER TABLE skill_assets ADD COLUMN wallet_address TEXT"
                )

            if "payee_id" not in ledger_cols:
                conn.execute(
                    "ALTER TABLE royalty_ledger ADD COLUMN payee_id TEXT"
                )
                conn.execute(
                    "UPDATE royalty_ledger SET payee_id = creator_id "
                    "WHERE payee_id IS NULL"
                )

            if "party" not in ledger_cols:
                conn.execute(
                    "ALTER TABLE royalty_ledger ADD COLUMN party TEXT"
                )
                conn.execute(
                    "UPDATE royalty_ledger SET party = 'creator' "
                    "WHERE party IS NULL"
                )

            if rebuild_ledger:
                # Stage 2 / WP-D: rebuild royalty_ledger to widen the status
                # CHECK to include 'settling' and to add the three nullable
                # columns. Runs AFTER the payee_id / party ALTERs above so the
                # INSERT … SELECT below can read them. Pre-existing rows carry
                # over verbatim with NULL in every new column — their status
                # values ('accrued' / 'settled') are a strict subset of the new
                # CHECK, so nothing is rejected or rewritten.
                conn.execute("""
                    CREATE TABLE royalty_ledger_new (
                        id         TEXT    PRIMARY KEY,
                        run_id     TEXT    NOT NULL,
                        creator_id TEXT    NOT NULL,
                        payee_id   TEXT    NOT NULL,
                        party      TEXT    NOT NULL CHECK (party IN ('creator', 'platform', 'tax')),
                        asset_id   TEXT    NOT NULL,
                        amount     INTEGER NOT NULL CHECK (amount >= 0),
                        currency   TEXT    NOT NULL,
                        chain      TEXT,
                        status     TEXT    NOT NULL CHECK (status IN ('accrued', 'settling', 'settled')),
                        settlement_method TEXT,
                        tx_hash           TEXT,
                        note              TEXT,
                        created_at TEXT    NOT NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO royalty_ledger_new (
                        id, run_id, creator_id, payee_id, party, asset_id,
                        amount, currency, chain, status,
                        settlement_method, tx_hash, note, created_at
                    )
                    SELECT
                        id, run_id, creator_id, payee_id, party, asset_id,
                        amount, currency, chain, status,
                        NULL, NULL, NULL, created_at
                    FROM royalty_ledger
                """)
                conn.execute("DROP TABLE royalty_ledger")
                conn.execute(
                    "ALTER TABLE royalty_ledger_new RENAME TO royalty_ledger"
                )

            if "network" not in audit_cols:
                # Stage 2 / WP-D: CAIP-2 network for the tx_hash on an audit
                # row. Nullable, no backfill — historical events were all on
                # the mock / anvil / sepolia rails whose network was implied
                # by `method`.
                conn.execute("ALTER TABLE audit_log ADD COLUMN network TEXT")

            if "event_ordinal" not in audit_cols:
                # U3 Phase 3 (codereviewer P1): explicit per-run insertion ordinal
                # so list ordering doesn't rely on created_at + rowid ties. Added
                # nullable here (SQLite forbids ADD COLUMN NOT NULL without a
                # DEFAULT); backfilled per run_id in created_at + rowid order so
                # historical rows preserve their visible sequence.
                conn.execute(
                    "ALTER TABLE audit_log ADD COLUMN event_ordinal INTEGER"
                )
                run_rows = conn.execute(
                    "SELECT DISTINCT run_id FROM audit_log"
                ).fetchall()
                for run_row in run_rows:
                    rid = run_row[0]
                    ordered = conn.execute(
                        "SELECT id FROM audit_log WHERE run_id = ? "
                        "ORDER BY created_at ASC, rowid ASC",
                        (rid,),
                    ).fetchall()
                    for idx, row in enumerate(ordered, start=1):
                        conn.execute(
                            "UPDATE audit_log SET event_ordinal = ? WHERE id = ?",
                            (idx, row[0]),
                        )

            if rebuild_agent_runs:
                # Rebuild agent_runs to widen the settlement_status CHECK and
                # add the two new columns. The new table mirrors _create_tables;
                # SELECT … carries pre-existing rows over with NULL tx_hash and
                # 'ledger_only' as settlement_method (matches the column DEFAULT,
                # spelled explicitly so the INSERT doesn't rely on DDL defaults
                # applying to SELECT projections).
                conn.execute("""
                    CREATE TABLE agent_runs_new (
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
                        settlement_meta   TEXT,
                        created_at        TEXT    NOT NULL
                    )
                """)
                conn.execute("""
                    INSERT INTO agent_runs_new (
                        run_id, agent_name, caller_id, task_id,
                        input_tokens, output_tokens, llm_cost_usd, time_ms,
                        success, asset_ids, royalty_splits,
                        charge_amount, charge_currency, charge_chain,
                        payment_method, settlement_status,
                        settlement_method, tx_hash, settlement_meta, created_at
                    )
                    SELECT
                        run_id, agent_name, caller_id, task_id,
                        input_tokens, output_tokens, llm_cost_usd, time_ms,
                        success, asset_ids, royalty_splits,
                        charge_amount, charge_currency, charge_chain,
                        payment_method, settlement_status,
                        'ledger_only', NULL, NULL, created_at
                    FROM agent_runs
                """)
                conn.execute("DROP TABLE agent_runs")
                conn.execute("ALTER TABLE agent_runs_new RENAME TO agent_runs")
            elif "settlement_meta" not in agent_run_cols:
                # Already-modern agent_runs table (Phase 3 rebuild done):
                # settlement_meta is a plain nullable ADD COLUMN.
                conn.execute("ALTER TABLE agent_runs ADD COLUMN settlement_meta TEXT")

            for column in pact_wpr_columns:
                # Stage 2 / WP-R: nullable TEXT, no backfill and no CHECK to
                # widen, so a plain ADD COLUMN is the whole migration. NULL
                # means "this pact never carried the key" — which is exactly
                # what pacts._row_to_pact already does with every optional
                # column, so no existing response shape changes.
                # The f-string interpolates only the two hardcoded names in
                # `pact_wpr_columns` above — SQLite cannot bind an identifier
                # as a parameter, and no caller-supplied value reaches here.
                conn.execute(f"ALTER TABLE pacts ADD COLUMN {column} TEXT")

            # WP-I18N-2 / D-C. Same f-string posture as the pacts clause
            # above: the interpolated names are the hardcoded literals in the
            # two lists, never anything caller-supplied. No backfill UPDATE —
            # NULL is the correct value for every pre-existing row, and the
            # demo bootstraps fill in the rows they own.
            for column in i18n_skill_columns:
                conn.execute(f"ALTER TABLE skill_assets ADD COLUMN {column} TEXT")
            for column in i18n_user_columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")

            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = previous_isolation


def _seed_demo_users(conn: sqlite3.Connection) -> None:
    """Seed the 4 Demo users + 2 Phase 1 stub identities on init. Idempotent.

    Demo passwords are 'demo123' — DO NOT REUSE IN PROD. The 4 demo ids/roles
    must match DEMO_IDENTITIES in app/app.py so JWT login and demo cookie
    identity refer to the same person.

    The 2 stub ids (RESERVED_USER_IDS) own pre-existing royalty / agent_run
    rows from Phase 1. We seed them with an unloginable sentinel
    password_hash ("disabled$reserved-stub-user") so verify_password always
    returns False (the digest_hex side fails bytes.fromhex). Combined with
    auth_register rejecting these ids up-front, an attacker can't claim a
    stub identity and then JWT-login as the owner of historical rows.
    """
    from datetime import datetime, timezone
    from app.services.auth import hash_password
    from app.storage.users import RESERVED_USER_IDS

    # Sentinel hash — contains '$' (so create_user's format check is satisfied
    # if anything ever round-trips this through the DAO), but neither side is
    # valid hex, so verify_password short-circuits to False.
    DISABLED_HASH = "disabled$reserved-stub-user"

    # password=None means "hash 'demo123' lazily" so we don't burn ~200ms per
    # PBKDF2 call on every app startup when all rows already exist.
    # WP-I18N-2 / D-C: `name_en` is the English display name; it must match
    # DEMO_IDENTITIES[*]["name"]["en"] in app/app.py, which is what the demo
    # cookie / header path renders. None for the two Phase 1 stubs — their
    # names are already English.
    seed_users = [
        ("li_boss",              "李老板",                 "Boss Li",       "enterprise", None),
        ("zhang_ai",             "张AI",                   "AI Zhang",      "creator",    None),
        ("wang_dev",             "王工",                   "Engineer Wang", "jobseeker",  None),
        ("zhao_design",          "赵设计",                 "Designer Zhao", "creator",    None),
        ("phase1_stub_creator",  "Phase 1 Stub Creator",  None,            "creator",    DISABLED_HASH),
        ("phase1_stub_employer", "Phase 1 Stub Employer", None,            "enterprise", DISABLED_HASH),
    ]
    # Defensive check: the seeded stub ids must stay in sync with the
    # register-route guard.
    assert {uid for uid, _, _, _, ph in seed_users if ph == DISABLED_HASH} == set(RESERVED_USER_IDS), \
        "seeded stub ids must match RESERVED_USER_IDS"

    now = datetime.now(timezone.utc).isoformat()
    existing = {row[0] for row in conn.execute("SELECT id FROM users").fetchall()}
    if not existing.issuperset(uid for uid, *_ in seed_users):
        for uid, name, name_en, role, pw_hash in seed_users:
            if uid in existing:
                continue
            # Lazy: demo passwords get hashed only for the row we're inserting.
            resolved_hash = pw_hash if pw_hash is not None else hash_password("demo123")
            conn.execute(
                "INSERT OR IGNORE INTO users (id, name, name_en, role, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, name, name_en, role, resolved_hash, now),
            )

    # Backfill the English names onto rows that already existed before the
    # WP-I18N-2 migration. `WHERE name_en IS NULL` keeps this idempotent and
    # keeps it from overwriting a name someone changed on purpose; it runs
    # every boot (cheap: 4 no-op UPDATEs) rather than only on the insert path,
    # because the insert path short-circuits as soon as all 6 rows exist.
    for uid, _name, name_en, _role, _ph in seed_users:
        if name_en is None:
            continue
        conn.execute(
            "UPDATE users SET name_en = ? WHERE id = ? AND name_en IS NULL",
            (name_en, uid),
        )
    conn.commit()


def init_db(app: Flask) -> None:
    db_path = app.config["DATABASE_PATH"]
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    with closing(_open(db_path)) as conn:
        _create_tables(conn)
        _migrate(conn)
        _seed_demo_users(conn)
