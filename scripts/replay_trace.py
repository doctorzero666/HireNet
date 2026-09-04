#!/usr/bin/env python3
"""
Stage 1 / D9 — replay one task-analysis run, step by step.

    python scripts/replay_trace.py <session_id> [--db PATH] [--full]

Prints every `analysis_traces` row for the session in `step_no` order: which
stage it was, which model answered, whether the output parsed, what it cost in
tokens and wall time, then the prompt and the raw response.

Prompt and response are truncated to 200 characters by default — the point of
the default view is "where did this run go wrong", and a 4KB system prompt
buries that. `--full` prints them whole for the one step you then care about.

Exits 1 when the session has no traces: a silent empty listing reads like
"the run was clean" when it usually means the wrong session id, the wrong DB,
or a v1 run (v1 writes no traces at all).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.storage.analysis_traces import list_traces  # noqa: E402

TRUNCATE_AT = 200

DEFAULT_DB_PATH = os.getenv(
    "HIRENET_DB_PATH", os.path.join(os.path.expanduser("~"), ".hirenet", "hirenet.db")
)


def _clip(text: str, full: bool) -> str:
    """Truncate for the default view; mark it so nobody reads a cut as the end."""
    if full or len(text) <= TRUNCATE_AT:
        return text
    return text[:TRUNCATE_AT] + f"… [+{len(text) - TRUNCATE_AT} chars, use --full]"


def _format_prompt(prompt_json: str, full: bool) -> str:
    """Render the stored messages array as `role: content` lines.

    Falls back to the raw string when it is not the expected JSON — a trace
    written by something else is still worth showing, just not worth crashing on.
    """
    try:
        messages = json.loads(prompt_json)
    except (json.JSONDecodeError, TypeError):
        return _clip(str(prompt_json), full)
    if not isinstance(messages, list):
        return _clip(str(prompt_json), full)
    if not messages:
        return "(no messages — not an LLM step)"
    return "\n".join(
        f"    {m.get('role', '?')}: {_clip(str(m.get('content', '')), full)}"
        for m in messages
        if isinstance(m, dict)
    )


def _format_tokens(row: dict) -> str:
    def one(value: object) -> str:
        return "?" if value is None else str(value)

    return f"in={one(row.get('input_tokens'))} out={one(row.get('output_tokens'))}"


def render(rows: list[dict], session_id: str, full: bool) -> str:
    lines = [
        f"session {session_id} — {len(rows)} step(s)",
        "=" * 72,
    ]
    for row in rows:
        time_ms = row.get("time_ms")
        lines.append(
            f"[{row['step_no']}] {row['stage']}  model={row['model']}  "
            f"parsed_ok={row['parsed_ok']}  {_format_tokens(row)}  "
            f"time_ms={'?' if time_ms is None else time_ms}"
        )
        lines.append("  prompt:")
        lines.append(_format_prompt(row["prompt_json"], full))
        lines.append("  response:")
        lines.append(f"    {_clip(row['response_text'], full)}")
        lines.append("-" * 72)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="replay_trace.py",
        description="Replay one task-analysis session from the analysis_traces table.",
    )
    parser.add_argument("session_id", help="the analysis session id to replay")
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"print prompts and responses in full instead of the first {TRUNCATE_AT} chars",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"error: database not found: {args.db}", file=sys.stderr)
        return 1

    rows = list_traces(args.db, args.session_id)
    if not rows:
        print(
            f"error: no traces for session {args.session_id!r} in {args.db}\n"
            "       (v1 runs write no traces — check HIRENET_TASK_AGENT and the session id)",
            file=sys.stderr,
        )
        return 1

    print(render(rows, args.session_id, args.full))
    return 0


if __name__ == "__main__":
    sys.exit(main())
