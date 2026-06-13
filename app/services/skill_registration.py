import hashlib
import json

import jsonschema

from app.services.validation import validate, validate_split_rule
from app.storage.skill_assets import insert_skill_asset

# Fields the registration endpoint accepts from the client.
# Unknown fields are rejected (400) to prevent silent data loss.
# creator_id and content_hash are accepted but IGNORED: the server
# always substitutes the Phase 1 stub creator and computes the hash itself.
_ALLOWED_PAYLOAD_FIELDS = {
    "name", "description", "type", "endpoint_url", "io_schema",
    "price_amount", "price_currency", "price_chain", "split_rule",
    "wallet_address", # Phase 3+: agent's recipient wallet for on-chain settle
    "creator_id",     # Phase 1 stub: accepted but overridden, not trusted
    "content_hash",   # accepted but overridden; server computes its own
}


def _normalize_wallet_address(value: object) -> str | None:
    """Return a checksum-cased EVM address, or None when absent.

    Accepts None, empty string, or "0x" + 40 hex chars (case-insensitive).
    Anything else raises ValueError so the route layer can 400. We don't
    fully checksum-validate here (would require web3); shape check is enough
    to refuse obvious garbage. Sepolia's provider re-validates with Web3.is_address
    at settle time.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"wallet_address must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        return None
    if not stripped.startswith("0x") or len(stripped) != 42:
        raise ValueError(
            f"wallet_address must be 0x-prefixed 40-hex-char EVM address, got {stripped!r}"
        )
    try:
        int(stripped[2:], 16)
    except ValueError:
        raise ValueError(
            f"wallet_address contains non-hex characters: {stripped!r}"
        )
    return stripped


def compute_content_hash(
    name: str,
    description: str,
    asset_type: str,
    io_schema: dict,
    endpoint_url: str | None = None,
) -> str:
    """Return SHA256 hex digest over canonical JSON of the asset's content fields.

    sort_keys=True and compact separators eliminate key-order and whitespace variation.
    endpoint_url is always included (as null when absent) so same-content assets with
    and without endpoint_url produce different hashes when the URL differs.
    """
    canonical = json.dumps(
        {
            "description": description,
            "endpoint_url": endpoint_url,
            "io_schema": io_schema,
            "name": name,
            "type": asset_type,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def register_skill_asset(db_path: str, payload: dict, creator_id: str) -> dict:
    """Validate, hash, and persist a new SkillAsset.

    creator_id comes from the Phase 1 stub config — the client-supplied value
    (if any) is intentionally ignored.  This is a Phase 1 stub for authentication;
    real per-user auth is out of scope until Phase 2.

    content_hash is computed server-side; any client-supplied value is overridden.

    Returns:
        {"skill_id": <uuid>, "content_hash": <64-char hex>}

    Raises:
        ValueError: unknown payload fields, or split_rule basis points != 10000.
        jsonschema.ValidationError: assembled asset fails schema validation.
        KeyError: a required field is missing from payload.
        TypeError: price_amount is not a plain non-negative integer.
    """
    unknown = set(payload.keys()) - _ALLOWED_PAYLOAD_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields in payload: {sorted(unknown)}")

    content_hash = compute_content_hash(
        name=payload["name"],
        description=payload["description"],
        asset_type=payload["type"],
        io_schema=payload["io_schema"],
        endpoint_url=payload.get("endpoint_url"),
    )

    wallet_address = _normalize_wallet_address(payload.get("wallet_address"))

    asset = {
        # Phase 1 stub: creator_id is always the configured stub, never the
        # client-supplied value. Real per-user auth is deferred to Phase 2.
        "creator_id": creator_id,
        "name": payload["name"],
        "description": payload["description"],
        "type": payload["type"],
        "endpoint_url": payload.get("endpoint_url"),
        "io_schema": payload["io_schema"],
        "price_amount": payload["price_amount"],
        "price_currency": payload["price_currency"],
        "price_chain": payload.get("price_chain"),
        "split_rule": payload["split_rule"],
        "content_hash": content_hash,
        "wallet_address": wallet_address,
    }

    validate(asset, "skill_asset")
    validate_split_rule(asset["split_rule"])

    skill_id = insert_skill_asset(db_path, asset)
    return {"skill_id": skill_id, "content_hash": content_hash}
