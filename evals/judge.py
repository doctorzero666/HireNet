"""LLM judge for the golden set (Stage 1 / D12).

The structural scorer in `evals/scoring.py` measures shape. This measures
quality, on the 1–5 scale each golden case defines in its own `judge_rubric`.
The two are recorded side by side and never averaged together (spec §3).

Honesty constraints baked into this module:

* **The judge is the same model family as the thing it judges** (Zhipu GLM via
  `app.agents.agents.get_model()`). That is a known bias and D12 accepts it for
  Stage 1 *on the condition* that a human spot-checks a sample of the scores.
  The report is required to repeat that caveat; see `evals/README.md`.
* **A judge that cannot be parsed scores `None`, never a default.** Substituting
  a 3 for an unreadable answer would quietly drag every mean toward the middle.
  `None` shows up as "—" in the report and is excluded from the mean.
* Parsing goes through `app.services.validation.parse_llm_json` — the same
  fence-stripping / prose-tolerant parser the production pipeline uses — plus a
  jsonschema check. No bare `json.loads` on model output (CLAUDE.md TIER 1 #1).

Why the schema is inline here rather than in `app/schemas/`:
`validation.load_schema` only reads `app/schemas/`, and the judge is an eval
artefact, not part of the product surface. Adding a file there would put an
eval-only contract inside the app's locked schema directory.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from app.services.validation import parse_llm_json
from evals.scoring import routing_by_task_id

PROMPT_PATH = Path(__file__).parent / "prompts" / "judge.md"

#: The judge's output contract. Kept minimal on purpose: a judge that has to
#: fill in more fields spends its attention on formatting instead of judging.
JUDGE_SCHEMA = {
    "type": "object",
    "required": ["score", "rationale"],
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {"type": "string", "minLength": 1},
    },
}

#: Judge sampling temperature. Low, not zero: 0 on this provider is not a
#: guarantee of determinism anyway, and the report never claims reproducibility
#: of judge scores — only of the structural ones.
JUDGE_TEMPERATURE = 0.1

#: How much of each free-text field reaches the judge. The judge only needs to
#: recognise the shape of the answer, and an unbounded task description would
#: let one case dominate the token budget.
_MAX_FIELD_CHARS = 600


def load_rubric_prompt(path: str | Path | None = None) -> str:
    """Read the judge system prompt from `evals/prompts/judge.md`."""
    with open(path or PROMPT_PATH, encoding="utf-8") as handle:
        return handle.read()


def _clip(value, limit: int = _MAX_FIELD_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def build_judge_input(case: dict, result: dict | None) -> str:
    """Render the user message: the employer's words, the rubric, the output.

    Deliberately hands over a *reduced* view — requirement, task list, routing —
    rather than the raw response body. `jd_report` and `summary` are downstream
    renderings of the same decisions; including them would let a verbose JD
    inflate a score the rubric is asking about the tasks.
    """
    payload = result or {}
    tasks = payload.get("tasks") or []
    routing = routing_by_task_id(payload.get("decisions"))

    lines = [
        "# 雇主原话",
        f"初始需求：{case['input']['initial_message']}",
    ]
    for i, answer in enumerate(case["input"].get("clarifications") or [], start=1):
        lines.append(f"澄清回答 {i}：{answer}")

    lines += [
        "",
        "# 本例评分标准",
        case.get("judge_rubric", "1–5：任务拆解是否合理、路由是否站得住。"),
        "",
        "# 流水线输出",
    ]

    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        lines.append("## 结构化需求")
        for key in ("project_name", "core_description", "duration", "budget_hint", "team_context", "urgency"):
            if key in requirement:
                lines.append(f"- {key}: {_clip(requirement.get(key), 300)}")
    else:
        lines.append("## 结构化需求\n- （没有产出结构化需求）")

    lines.append("## 任务与路由")
    if not tasks:
        lines.append("- （没有产出任何任务）")
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id", ""))
        lines.append(
            f"- [{task_id}] {_clip(task.get('name'), 120)} | type={task.get('type')} "
            f"| hours={task.get('estimated_hours')} | requires_judgment={task.get('requires_judgment')} "
            f"| 路由={routing.get(task_id, '（无决策）')}"
        )
        description = task.get("description")
        if description:
            lines.append(f"  描述：{_clip(description)}")

    lines += ["", "请按系统提示的格式只输出 JSON。"]
    return "\n".join(lines)


def _repair_prompt(raw: str, error: str) -> str:
    return (
        "你上一条输出无法被解析为合法 JSON。\n"
        f"原始输出：\n{raw[:1500]}\n\n"
        f"错误：{error}\n\n"
        '只输出这个对象，不要 markdown 代码块，不要解释：'
        '{"score": 1到5之间的整数, "rationale": "一到两句中文"}'
    )


def _parse(raw: str) -> dict:
    """parse_llm_json + schema check. Raises on anything unusable."""
    data = parse_llm_json(raw)
    jsonschema.validate(data, JUDGE_SCHEMA)
    return data


def judge_case(
    case: dict,
    result: dict | None,
    client,
    model: str,
    system_prompt: str | None = None,
    temperature: float = JUDGE_TEMPERATURE,
) -> dict:
    """Score one case with the LLM judge. One call, plus at most one repair call.

    Args:
        case: golden-set case (its `judge_rubric` is the primary criterion).
        result: the `/api/analyze/decide` response body, or None if the run failed.
        client: an OpenAI-compatible client — in a real run this is the
            `CountingLLMProxy`, so judge tokens land in the same budget.
        model: model id to judge with.

    Returns:
        `{"score": int|None, "rationale": str|None, "repaired": bool,
          "error": str|None, "raw": str|None}`.
        `score` is None whenever the judge could not be read; the caller must
        exclude those from any mean rather than substituting a value.
    """
    if result is None:
        # Nothing to judge. Spending a call to have a model confirm that an
        # errored run is bad would only add noise and cost.
        return {
            "score": None,
            "rationale": None,
            "repaired": False,
            "error": "run failed — not judged",
            "raw": None,
        }

    system = system_prompt if system_prompt is not None else load_rubric_prompt()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": build_judge_input(case, result)},
    ]

    def call(msgs) -> str:
        resp = client.chat.completions.create(model=model, messages=msgs, temperature=temperature)
        return (resp.choices[0].message.content or "").strip()

    raw = ""
    try:
        raw = call(messages)
    except Exception as exc:  # network / budget / provider error
        return {"score": None, "rationale": None, "repaired": False,
                "error": f"{type(exc).__name__}: {exc}", "raw": None}

    try:
        data = _parse(raw)
        return {"score": data["score"], "rationale": data["rationale"],
                "repaired": False, "error": None, "raw": raw}
    except Exception as first_error:
        # `first_error` is unbound after the except block (PEP 3110), so both
        # the text and the message are copied out before we leave it.
        first_raw = raw
        first_message = f"{type(first_error).__name__}: {first_error}"

    # One repair attempt, then give up (WP4: "repair once, else score=None").
    try:
        repaired_raw = call(messages + [
            {"role": "assistant", "content": first_raw},
            {"role": "user", "content": _repair_prompt(first_raw, first_message)},
        ])
        data = _parse(repaired_raw)
        return {"score": data["score"], "rationale": data["rationale"],
                "repaired": True, "error": None, "raw": repaired_raw}
    except Exception as second_error:
        return {
            "score": None,
            "rationale": None,
            "repaired": True,
            "error": f"unparseable after one repair: {type(second_error).__name__}: {second_error}",
            "raw": first_raw,
        }
