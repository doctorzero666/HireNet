"""
Shared language-directive support for the analysis pipeline (WP-I18N / I2).

`lang` is an optional per-session flag threaded down to every LLM call in the
requirement-analysis pipeline (v1 `app/agents/agents.py`, v2
`app/agents/task_analysis.TaskAnalysisAgent`) and to `design_job`
(`app/agents/job_design.py`). When it is `"en"`, every call gets ONE extra
line appended to its system prompt at request time.

This module intentionally does NOT touch the prompt constants
(`REQUIREMENT_SYSTEM_PROMPT`, `DECOMPOSITION_SYSTEM_PROMPT`,
`JOB_DESIGN_SYSTEM_PROMPT`) or the prompt files under `app/agents/prompts/`.
Those stay byte-identical whether or not `lang` is used — the eval baseline
and `tests/test_prompts.py` depend on that. `with_lang_messages` only
modifies the *messages list actually sent to the LLM client*, built fresh on
every call from the untouched constants/files.
"""

#: Appended verbatim to the system prompt of every LLM call in an English
#: session. Spec-exact string (WP-I18N §3) — do not reformat or reword.
LANG_SUFFIX = "\n\nOutput language: respond and produce all JSON string values in English."

#: The only two values `lang` may take once normalised. Anything else is a
#: 400 at the route boundary (see `normalize_lang`).
SUPPORTED_LANGS = ("zh", "en")

#: Today's behaviour, unlabelled by the client, is Chinese output — this is
#: the default `normalize_lang` returns for a missing/empty `lang`.
DEFAULT_LANG = "zh"


def normalize_lang(value: object) -> str | None:
    """Validate a `lang` value from a request body.

    Returns:
        `"zh"` (today's behaviour) when `value` is `None`, missing, or the
        empty string; `value` itself when it is `"zh"` or `"en"`; `None` for
        anything else — the caller turns that into the 400
        `{"error": "unsupported lang"}` response.
    """
    if value is None or value == "":
        return DEFAULT_LANG
    if value in SUPPORTED_LANGS:
        return value
    return None


def with_lang_messages(messages: list[dict], lang: str | None) -> list[dict]:
    """Return `messages` with the EN directive applied to the system prompt.

    No-op when `lang != "en"`: returns the SAME list object, unmodified. This
    is the path that must stay byte-identical to pre-i18n behaviour — the
    eval baseline and `tests/test_prompts.py` both call production functions
    with no `lang` and compare the wire format to the v1 constants.

    When `lang == "en"`, returns a NEW list (the input is never mutated):
    the existing leading system message gets `LANG_SUFFIX` appended, or — if
    there is no system message at all (several call sites send only a
    "user" message, e.g. the resource-evaluation prompt) — a new leading
    system message is inserted, its content being `LANG_SUFFIX` itself. That
    keeps "the system prompt ends with the exact suffix" true for every call,
    including ones that never had a system prompt before.
    """
    if lang != "en":
        return messages
    copied = [dict(m) for m in messages]
    if copied and copied[0].get("role") == "system":
        copied[0]["content"] = copied[0]["content"] + LANG_SUFFIX
    else:
        copied.insert(0, {"role": "system", "content": LANG_SUFFIX})
    return copied
