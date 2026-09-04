"""
Prompt texts for the task-analysis pipeline, one `.md` file per prompt.

Why files: in v1 every prompt is an inline constant or f-string inside
`app/agents/agents.py`, so changing a word is a code diff, diffing two prompt
versions means reading Python string literals, and nothing can render them for
review. WP4 measures v1 against v2 on the same golden cases, so the v2 prompts
start as **byte-identical copies** of the v1 text — `tests/test_prompts.py`
asserts that, and it is the reason this commit deliberately does not improve
any wording. `force_extract.md` is the only new text (D3).

Templating: the two prompts that interpolate values use `string.Template`
(`${name}`) rather than `str.format`, because these prompts are full of literal
JSON braces and `{{`-escaping every one of them is exactly the kind of edit
that silently corrupts a prompt. Render with `render_prompt(name, **values)`;
a missing value raises `KeyError` instead of shipping a `${placeholder}` to the
model.

v1 keeps its own constants — `agents.py` is untouched by this change.
"""
from pathlib import Path
from string import Template

_PROMPT_DIR = Path(__file__).parent

#: name (file stem) → prompt text, loaded once at import. Trailing newlines are
#: stripped so a file that ends with the usual POSIX newline is byte-identical
#: to the Python string literal it was copied from.
_PROMPTS: dict[str, str] = {
    path.stem: path.read_text(encoding="utf-8").rstrip("\n")
    for path in sorted(_PROMPT_DIR.glob("*.md"))
}


def available_prompts() -> list[str]:
    """Names accepted by `load_prompt`, sorted."""
    return sorted(_PROMPTS)


def load_prompt(name: str) -> str:
    """Return the prompt text for `name` (the `.md` file stem).

    Raises:
        KeyError: if there is no such prompt. Loud, because a typo'd prompt name
            would otherwise become an empty system prompt and a plausible-looking
            but meaningless model answer.
    """
    try:
        return _PROMPTS[name]
    except KeyError:
        raise KeyError(
            f"unknown prompt {name!r}; available: {', '.join(available_prompts())}"
        ) from None


def render_prompt(name: str, **values: object) -> str:
    """Load `name` and substitute its `${placeholder}` values.

    Raises:
        KeyError: for an unknown prompt name, or a placeholder with no value.
    """
    return Template(load_prompt(name)).substitute(**values)
