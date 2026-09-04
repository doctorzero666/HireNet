"""
Schema validation service with retry-with-repair and fallback.

Usage:
    from app.services.validation import validate, parse_llm_json, validate_llm_output

    # Simple validation
    validate(data, "skill_asset")

    # Parse + validate LLM output with fallback
    result = validate_llm_output(raw_str, "requirement", fallback=DEFAULT_REQ)

    # Parse + validate with LLM repair loop
    result = validate_llm_output(raw_str, "task", llm_fn=my_llm_call, max_retries=2)
"""
import copy
import json
from pathlib import Path
from typing import Callable

import jsonschema

_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"
_schema_cache: dict[str, dict] = {}


def _resolve_local_refs(schema: object) -> object:
    """Recursively inline local file $ref values (e.g. "$ref": "foo.json").

    Only resolves simple filenames that exist in _SCHEMA_DIR. Fragment refs
    ("#/...") and URL refs ("https://...") are left untouched.
    """
    if isinstance(schema, dict):
        ref = schema.get("$ref", "")
        if ref and not ref.startswith("#") and "://" not in ref:
            ref_path = _SCHEMA_DIR / ref
            if ref_path.exists():
                with open(ref_path, encoding="utf-8") as f:
                    return _resolve_local_refs(json.load(f))
        return {k: _resolve_local_refs(v) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve_local_refs(item) for item in schema]
    return schema


def load_schema(name: str) -> dict:
    """Return a deep copy of the cached schema so callers cannot mutate the cache.

    Local $ref values (e.g. "$ref": "royalty_split.json") are resolved and inlined
    at load time so the caller sees a fully expanded schema.

    Raises FileNotFoundError immediately (not retried) if the schema file is missing —
    this is a programmer error, not a transient LLM failure.
    """
    if name not in _schema_cache:
        path = _SCHEMA_DIR / f"{name}.json"
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        _schema_cache[name] = _resolve_local_refs(raw)
    return copy.deepcopy(_schema_cache[name])


def validate(data: dict, schema_name: str) -> None:
    """Validate data against the named JSON Schema. Raises jsonschema.ValidationError on failure."""
    schema = load_schema(schema_name)
    jsonschema.validate(instance=data, schema=schema)


# ─── Named validators for the task-analysis pipeline ──────────────────────────
#
# Thin wrappers over `validate()` so the agents layer never has to remember the
# schema file name (and so a rename shows up as one edit here, not a grep across
# app/agents/). They raise jsonschema.ValidationError like `validate` does; no
# new error type, no second validation path.


def validate_requirement(obj: dict) -> None:
    """Validate a structured requirement (app/schemas/requirement.json)."""
    validate(obj, "requirement")


def validate_task(obj: dict) -> None:
    """Validate one decomposed task unit (app/schemas/task.json)."""
    validate(obj, "task")


def validate_task_decision(obj: dict) -> None:
    """Validate one runtime task-routing decision (app/schemas/task_decision.json).

    This is the object inside the `{"decisions": [...]}` wrapper the analysis
    routes return — NOT the four-dimensional settlement `resource_decision`.
    """
    validate(obj, "task_decision")


def validate_analysis_trace(obj: dict) -> None:
    """Validate one analysis trajectory row (app/schemas/analysis_trace.json)."""
    validate(obj, "analysis_trace")


def validate_split_rule(split_rule: dict) -> None:
    """Enforce the accounting invariant: creator + platform + tax must sum to exactly 10000 basis points.

    Amounts are stored as integer basis points (1 bp = 0.01%, 10000 bp = 100%).
    This eliminates floating-point rounding drift in royalty calculations.

    JSON Schema can only bound individual ratios (0–10000), not their sum.
    Call this after schema validation whenever a split_rule is persisted or used
    to compute royalty amounts.

    `tax` defaults to 0 when absent, so legacy Phase 1 rules of the shape
    {"creator": 7000, "platform": 3000} keep validating untouched.

    Raises:
        ValueError: if the basis points do not sum to 10000.
    """
    creator = split_rule.get("creator", 0)
    platform = split_rule.get("platform", 0)
    tax = split_rule.get("tax", 0)
    total = creator + platform + tax
    if total != 10000:
        raise ValueError(
            f"split_rule basis points must sum to 10000, got {total} "
            f"(creator={creator}, platform={platform}, tax={tax})"
        )


def _extract_first_json_object(text: str) -> str:
    """Find and return the first complete {...} substring from text that may contain prose."""
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found in text", text, 0)
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < len(text):
                i += 2  # skip escaped character
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        i += 1
    raise json.JSONDecodeError("Unterminated JSON object", text, start)


def parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and extract the first JSON object from raw LLM output.

    Handles:
    - Plain JSON strings
    - ```json ... ``` and ``` ... ``` fences
    - Prose text before/after the JSON object (common LLM behaviour)
    """
    cleaned = raw.strip()
    # Strip markdown code fences
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        stripped = cleaned.rstrip()
        if stripped.endswith("```"):
            cleaned = stripped[: stripped.rfind("```")]
        cleaned = cleaned.strip()

    # Fast path: direct parse (no surrounding prose)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Slow path: LLM added explanatory text before/after the JSON object
    return json.loads(_extract_first_json_object(cleaned))


def _default_repair_prompt(raw: str, schema_name: str, error: str) -> str:
    schema = load_schema(schema_name)
    return (
        f"The following JSON output is invalid:\n{raw}\n\n"
        f"Validation error: {error}\n\n"
        f"Please output ONLY a corrected JSON that satisfies this schema:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n\n"
        "Rules: output ONLY the JSON object, no explanation, no markdown fences."
    )


def validate_llm_output(
    raw: str,
    schema_name: str,
    llm_fn: Callable[[str], str] | None = None,
    repair_prompt_fn: Callable[[str, str, str], str] | None = None,
    max_retries: int = 2,
    fallback: dict | None = None,
) -> dict:
    """
    Parse and validate an LLM output string against a named JSON Schema.

    On parse or validation failure:
      1. If llm_fn is provided: send a repair prompt and retry (up to max_retries times).
      2. If fallback is provided: validate it against the schema (a buggy fallback must fail
         loudly, not be silently swallowed), then return it.
      3. Otherwise: raise the last exception.

    Note: a missing schema file raises FileNotFoundError immediately and is NOT retried —
    this is a programmer error, not a transient LLM failure.

    Args:
        raw: Raw string from LLM (may contain markdown fences or surrounding prose).
        schema_name: Name of the schema file (without .json).
        llm_fn: Callable that takes a repair prompt string and returns a new raw string.
        repair_prompt_fn: Optional custom prompt builder (raw, schema_name, error) -> str.
        max_retries: How many repair attempts to make (default 2).
        fallback: Dict to return if all attempts fail. Validated against the schema before
                  returning — a buggy fallback raises ValidationError, not a silent wrong result.
    """
    prompt_builder = repair_prompt_fn or _default_repair_prompt
    last_error: Exception | None = None
    current_raw = raw

    for attempt in range(max_retries + 1):
        try:
            data = parse_llm_json(current_raw)
            validate(data, schema_name)
            return data
        except (json.JSONDecodeError, jsonschema.ValidationError, ValueError) as exc:
            last_error = exc
            if attempt < max_retries and llm_fn is not None:
                repair_prompt = prompt_builder(current_raw, schema_name, str(exc))
                current_raw = llm_fn(repair_prompt)
            # else: out of retries or no llm_fn — fall through to fallback/raise

    if fallback is not None:
        validate(fallback, schema_name)  # bug in caller's fallback must fail loudly
        return fallback
    if last_error is None:
        raise RuntimeError(
            "validate_llm_output: retry loop completed without setting last_error — "
            "this is a bug in validate_llm_output itself"
        )
    raise last_error
