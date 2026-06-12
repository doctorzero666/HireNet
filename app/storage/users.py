"""
DAO for the `users` table. Thin — schema lives in db.py, business rules in
the routes / services that call these.
"""
import sqlite3
from datetime import datetime, timezone


ALLOWED_ROLES = {"enterprise", "creator", "jobseeker"}

# Phase 1 stub identities that own pre-existing royalty / agent_run rows.
# Seeded into `users` by _seed_demo_users with an unloginable sentinel
# password_hash so an attacker can't register one of these IDs and then
# JWT-login as the owner of those historical rows (would be a U6 IDOR).
RESERVED_USER_IDS = frozenset({"phase1_stub_creator", "phase1_stub_employer"})


def _open(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_user(db_path: str, user_id: str) -> dict | None:
    """Lookup by primary key. Returns dict or None."""
    if not isinstance(user_id, str) or not user_id:
        return None
    with _open(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, role, password_hash, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def create_user(
    db_path: str,
    user_id: str,
    name: str,
    role: str,
    password_hash: str,
) -> dict:
    """Insert a new user. Raises ValueError on validation failure / duplicate id."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")
    if user_id.strip() in RESERVED_USER_IDS:
        raise ValueError(f"user_id is reserved: {user_id.strip()}")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    if role not in ALLOWED_ROLES:
        raise ValueError(f"role must be one of {sorted(ALLOWED_ROLES)}")
    if not isinstance(password_hash, str) or "$" not in password_hash:
        raise ValueError("password_hash must be a 'salt$digest' string")

    user_id = user_id.strip()
    name = name.strip()
    created_at = datetime.now(timezone.utc).isoformat()
    with _open(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO users (id, name, role, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, name, role, password_hash, created_at),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"user_id already exists: {user_id}") from exc

    return {
        "id": user_id,
        "name": name,
        "role": role,
        "created_at": created_at,
    }
