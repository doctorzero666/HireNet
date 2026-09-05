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

WP-I18N-2 adds the other half — the parts of a response that are NOT LLM
prose:

* `resolve_request_lang(request, session_lang=None)` — the single place any
  route learns which language the caller asked for (`?lang=` on a GET, the
  body's `lang` on a POST, else the session's, else `DEFAULT_LANG`).
* `pick` / `localize` — resolve the `{"zh": ..., "en": ...}` seed literals
  (`MOCK_PROFILES`, `DEMO_JOBS`, `DEMO_IDENTITIES`, the decision-policy
  strings) at serialisation time. With no `lang`, both return exactly the
  Chinese value the caller sees today, so the v1 wire format is unchanged.
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


def resolve_request_lang(request, session_lang: str | None = None) -> str | None:
    """The language for THIS request, read off the Flask `request` object.

    One helper for every route so the `lang` convention is stated once
    (WP-I18N-2 / D-A):

      * `?lang=` query parameter wins — the only place a GET can carry it;
      * else the JSON body's `lang` key — how the POST routes have always
        taken it;
      * else `session_lang` (e.g. `analysis_sessions[sid]["lang"]`, so
        /decide keeps the language /start chose);
      * else `DEFAULT_LANG` ("zh"), i.e. today's unlabelled behaviour.

    Returns `None` for a value that is present but unsupported (`"fr"`),
    mirroring `normalize_lang`. Routes that must reject it turn that into the
    400 `{"error": "unsupported lang"}` they already return; routes that are
    lenient can pass the `None` straight into `pick`/`with_lang_messages`,
    both of which treat it as the default (Chinese) path.
    """
    raw = request.args.get("lang")
    if raw is None:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            raw = body.get("lang")
    if raw is None or raw == "":
        return session_lang or DEFAULT_LANG
    return normalize_lang(raw)


def is_bilingual(value: object) -> bool:
    """True for a `{"zh": ..., "en": ...}` seed node.

    The shape check is deliberately narrow: a `"zh"` key must be present and
    no key outside `SUPPORTED_LANGS` may be. That keeps `{}` and any real
    payload dict (which will have other keys) out, so `localize` can walk a
    whole response without guessing.
    """
    return (
        isinstance(value, dict)
        and "zh" in value
        and set(value) <= set(SUPPORTED_LANGS)
    )


def pick(value: object, lang: str | None = None) -> object:
    """Resolve ONE bilingual seed node; pass anything else through unchanged.

    `pick({"zh": "张伟", "en": "Wei Zhang"}, "en") == "Wei Zhang"`, and
    `pick("plain", "en") == "plain"`. A missing/unknown `lang` resolves to
    `DEFAULT_LANG`, so every caller that has not been taught about `lang`
    yet keeps seeing exactly the Chinese string it sees today.

    Shallow on purpose — use `localize` to resolve a whole nested structure.
    """
    if not is_bilingual(value):
        return value
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    return value.get(lang, value["zh"])


def localize(value: object, lang: str | None = None) -> object:
    """Deep-resolve every bilingual node inside `value`.

    Walks dicts and lists, replacing each `{"zh": ..., "en": ...}` node with
    its `lang` side (recursing into the result, so a bilingual list of
    bilingual items resolves too). Everything else is returned as-is.

    Containers are rebuilt rather than mutated: the seed literals
    (`MOCK_PROFILES`, `DEMO_JOBS`, …) are module-level constants shared by
    every request, and localising in place would leave the first caller's
    language burned into them for everyone after.
    """
    if is_bilingual(value):
        return localize(pick(value, lang), lang)
    if isinstance(value, dict):
        return {key: localize(item, lang) for key, item in value.items()}
    if isinstance(value, list):
        return [localize(item, lang) for item in value]
    if isinstance(value, tuple):
        return tuple(localize(item, lang) for item in value)
    return value
