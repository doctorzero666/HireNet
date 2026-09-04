"""
TaskAnalysisAgent — the v2 task-analysis pipeline (Stage 1 / WP3a).

One class owns the whole conversational pipeline that v1 spreads across
`RequirementAnalysisAgent` + three module functions:

    start / reply   →  clarify with the employer until the requirement is known
    decompose       →  break the requirement into task units
    decide_all      →  shortlist resources per task, evaluate, route

What this is *not*: it is not wired into any route. `app/app.py` still runs v1
end to end; the `HIRENET_TASK_AGENT` flag, the trace table and the route wiring
are WP3b. Nothing here writes to the database.

What changes relative to v1 (each one is a decision recorded in
`docs/stage1-task-analysis-spec.md §1`):

* **Every LLM output goes through `app/services/validation.py`** — no bare
  `json.loads` (audit risk 6). Malformed output is repaired once and then falls
  back; it never takes a route down with a 500.
* **The clarification loop terminates** (D3). v1 has no turn cap anywhere — not
  in the agent, not in the route, not in the browser (audit risk 3). At
  `max_turns` this agent forces the extraction once, and if that fails it stops
  calling the model at all rather than looping on the employer's money.
* **`recommendation` is never null** (D5, via `decision_policy.decide`).
* **`task_description` is carried onto the decision** (D6) — v1 consumes it at
  `job_design.py:126` and never produces it, so every JD today is written from
  an empty description (audit risk 5).
* **Usage is accounted for** (D8) — `resp.usage` is read on every call, priced
  by `app/agents/pricing.py`, and totalled in the state.
* **The whole state is a plain dict** (D4) — `to_state()` / `from_state()`, so
  the session store can move out of a module global later (audit risk 11).
* **A human is always reachable** (R6 / golden case g17) — see
  `shortlist_resources`.

v1 (`app/agents/agents.py`) is untouched and stays the default path.
"""
import copy
import json
import logging
import os
import time
from typing import Callable, Mapping

import jsonschema

import app.agents.agents as agents_module
from app.agents import candidate_profile
from app.agents.decision_policy import decide, sort_evaluations
from app.agents.pricing import estimate_cost_usd
from app.agents.prompts import load_prompt, render_prompt
from app.services.validation import (
    load_schema,
    parse_llm_json,
    validate_llm_output,
    validate_task_decision,
)

logger = logging.getLogger(__name__)


# ─── Constants ────────────────────────────────────────────────────────────────

#: The completion marker v1's state machine keys on (`agents.py:78`). Kept
#: byte-identical: the same prompt text produces it, and WP4 compares the two.
COMPLETION_MARKER = "[REQUIREMENT_COMPLETE]"

MAX_TURNS_ENV = "HIRENET_TASK_AGENT_MAX_TURNS"
DEFAULT_MAX_TURNS = 6

#: Temperatures, copied from the v1 call sites so WP4 measures the agent and not
#: a sampling change: clarify `agents.py:71`, decompose `:136`, evaluate `:200`,
#: forced extraction mirrors `force_generate_strategy` `:364`.
CLARIFY_TEMPERATURE = 0.3
EXTRACT_TEMPERATURE = 0.3
DECOMPOSE_TEMPERATURE = 0.2
EVALUATE_TEMPERATURE = 0.2

#: One repair attempt on a malformed requirement (D3/TIER-1 rule 1). Two would
#: double the worst-case latency of a `/start` call for a rare second-order win.
REQUIREMENT_REPAIR_RETRIES = 1

#: One re-ask when the decomposition output cannot be parsed at all.
DECOMPOSE_RETRIES = 1

#: Cap on per-task repair calls inside one `decompose()` so a model having a bad
#: day cannot turn a 1-call stage into a 6-call stage.
MAX_TASK_REPAIR_CALLS = 2

#: Shown to the employer when even the forced extraction failed to produce a
#: valid requirement. One sentence, Chinese, no jargon, and the agent stops
#: calling the model after it.
EXTRACTION_FAILED_MESSAGE = "抱歉，我没能从这段对话里整理出结构化的需求，请换一种说法重新描述一下你的项目。"

#: Recorded as the evaluation reason when a resource evaluation cannot be
#: parsed. Byte-identical to the fallback v1's routes already use
#: (`app/app.py:378-379`, `:485-486`, `:524-525`).
EVALUATION_FALLBACK_REASON = "评估超时，使用默认分数"

#: v1's fallback also carried `confidence: 0.5`, which lets a *failed* evaluation
#: out-score a real one and win the task. Stage 1 scores a failed evaluation 0:
#: an evaluation that did not happen is not evidence for anything.
EVALUATION_FALLBACK_CONFIDENCE = 0.0

#: v1's shortlist cap (`agents.py:269`).
SHORTLIST_MAX = 3

#: The advisory task-type vocabulary (D10). Out-of-vocabulary types are logged
#: and kept — `"general"` (app.py:369 and three siblings) and `"engineering"`
#: (test_e2e_phase1.py:60) are both live in this repo, and rejecting them here
#: would break four routes and a test file for no Stage 1 benefit.
TASK_TYPES = ("technical", "creative", "analytical", "strategic", "operational")


# ─── Echo / placeholder guards (WP5, golden case g15) ─────────────────────────
#
# What went wrong on g15 (`evals/reports/2026-09-04-v1-vs-v2.md` §5): the
# employer message was a prompt injection, the model answered by printing the
# system prompt back, and that prompt *contains* both the completion marker
# (rule 4) and the empty JSON template. v2's prose-tolerant `parse_llm_json`
# then found the template, the repair round-trip filled in enum values that the
# schema accepts, and the run completed at turn 0 on a requirement whose
# `core_description` was the literal string `核心需求描述`.
#
# v1 survived the same response by accident: its stricter parser choked. The
# lesson is not "parse less" — it is that a parser tolerant of prose has to
# know the difference between the model's answer and the model quoting us.

#: `parsed_ok=False` reasons stamped on the trace record (D9) so a replay says
#: *why* a turn produced nothing, instead of only that it did.
PROMPT_ECHO_REASON = "prompt_echo"
PLACEHOLDER_REASON = "template_placeholder"
SHORT_DESCRIPTION_REASON = "core_description_too_short"

#: A `core_description` shorter than this is not a requirement, whatever the
#: schema says (`minLength: 1` only rules out the empty string). Four characters
#: is deliberately small: `官网改版` is a real four-character description, and
#: this guard exists to catch `""` / `"-"` / `"无"`, not to second-guess brevity.
MIN_CORE_DESCRIPTION_CHARS = 4

#: A line of the system prompt has to be at least this long before it is used
#: as an echo signature. Short lines ("规则：") appear in ordinary answers.
ECHO_SIGNATURE_MIN_CHARS = 8

#: Prompts whose JSON template the model might echo back at us.
_TEMPLATE_PROMPTS = ("requirement_system", "force_extract")


def _iter_strings(value: object):
    """Yield every string *value* inside a nested dict/list (keys excluded)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _template_placeholders() -> frozenset[str]:
    """Every literal string in the prompts' example JSON, read from the prompts.

    Derived from the prompt files rather than hard-coded, so editing
    `requirement_system.md` cannot leave a stale list behind: whatever the
    prompt shows the model as a placeholder is exactly what this rejects.
    """
    placeholders: set[str] = set()
    for name in _TEMPLATE_PROMPTS:
        try:
            template = parse_llm_json(load_prompt(name))
        except (KeyError, json.JSONDecodeError, ValueError):
            logger.warning("no JSON template found in prompt %r; echo guard is weaker", name)
            continue
        placeholders.update(s.strip() for s in _iter_strings(template) if s.strip())
    return frozenset(placeholders)


def _prompt_echo_signatures() -> tuple[str, ...]:
    """Distinctive lines of the system prompt that a normal answer never repeats.

    Two of them: the prompt's opening line, and the first line of its rules
    block (the first numbered line). Both are long, specific and about *how to
    behave*, so an employer-facing answer has no reason to contain them —
    whereas a reply that merely discusses 需求 shares no full line with the
    prompt at all.
    """
    lines = [line.strip() for line in load_prompt("requirement_system").splitlines()]
    usable = [line for line in lines if len(line) >= ECHO_SIGNATURE_MIN_CHARS]
    signatures = usable[:1]
    signatures += [line for line in usable if line.startswith("1.")][:1]
    return tuple(dict.fromkeys(signatures))


#: Built once at import, from the prompt files.
TEMPLATE_PLACEHOLDERS = _template_placeholders()
PROMPT_ECHO_SIGNATURES = _prompt_echo_signatures()


def is_prompt_echo(text: str) -> bool:
    """True when the response quotes the system prompt back at us (g15)."""
    return any(signature in text for signature in PROMPT_ECHO_SIGNATURES)


def requirement_rejection_reason(requirement: dict) -> str | None:
    """None if this is a real requirement, else why it is not one.

    Schema-valid is not the same as meaningful: the empty template in the
    prompt validates once its enum fields are filled in.
    """
    core = (requirement.get("core_description") or "").strip()
    if len(core) < MIN_CORE_DESCRIPTION_CHARS:
        return SHORT_DESCRIPTION_REASON
    for value in _iter_strings(requirement):
        if value.strip() in TEMPLATE_PLACEHOLDERS:
            return PLACEHOLDER_REASON
    return None


def _relaxed_task_schema() -> dict:
    """`task.json` with the `type` enum removed (D10: advisory, not enforced)."""
    schema = load_schema("task")
    type_prop = schema.get("properties", {}).get("type")
    if isinstance(type_prop, dict):
        type_prop.pop("enum", None)
    return schema


#: Built once at import; the enum is checked separately so it can warn instead
#: of reject.
RELAXED_TASK_SCHEMA = _relaxed_task_schema()


# ─── Resource shortlisting (R6) ───────────────────────────────────────────────

def shortlist_resources(
    task: dict,
    pool: list[dict],
    max_size: int = SHORTLIST_MAX,
) -> list[dict]:
    """Pick the resources worth spending an LLM evaluation on for one task.

    Starts from v1's type→resource table (`agents.py:231-269`) and closes the
    hole that table has: v1 shortlists **agents only** for `operational` tasks
    (`agents.py:258-259`) and only appends humans when the task is recurring, so
    a one-off on-site job — "install smart lockers in 20 stores", golden case
    g17 — is scored against 文案撰写 Agent and 数据分析 Agent and can never be
    routed to a human. `human` was unreachable by construction, not by judgment.

    So a human candidate is forced into the shortlist when any of:

    * ``requires_judgment`` is true — the one field the decomposition prompt
      produces specifically to mean "a person has to decide this";
    * the task is ``operational`` and not recurring — v1's blind spot: one-off
      physical / on-site work;
    * no agent in the pool matches the task type at all — an empty agent
      shortlist must fall back to people, not to whatever agent happens to exist.

    The cap stays at v1's 3 (cost), and the forced human is inserted *inside*
    the cap rather than appended after it, so truncation cannot silently undo
    the rule.
    """
    agents = {r["id"]: r for r in pool if r.get("type") == "agent"}
    humans = [r for r in pool if r.get("type") == "human"]
    candidates = {r["id"]: r for r in humans}

    task_type = task.get("type", "")
    is_recurring = task.get("is_recurring", False)

    agent_content = agents.get("agent_content")
    agent_code = agents.get("agent_code")
    agent_data = agents.get("agent_data")
    candidate_b = candidates.get("candidate_b")
    first_candidate = humans[0] if humans else None

    # v1's table, unchanged (agents.py:249-261).
    if task_type == "creative":
        type_agents = [agent_content]
        selected = [r for r in [agent_content, first_candidate] if r]
    elif task_type == "technical":
        type_agents = [agent_code]
        selected = [r for r in [agent_code, first_candidate] if r]
    elif task_type == "analytical":
        type_agents = [agent_data]
        selected = [r for r in [agent_data, first_candidate] if r]
    elif task_type == "strategic":
        type_agents = [agent_content]
        pm = candidate_b or first_candidate
        selected = [r for r in [pm, agent_content] if r]
    elif task_type == "operational":
        type_agents = [agent_content, agent_data]
        selected = [r for r in [agent_content, agent_data] if r]
    else:
        type_agents = [agent_content, agent_code, agent_data]
        selected = [r for r in [agent_content, agent_code, agent_data] if r]

    if is_recurring:
        for human in humans:
            if human not in selected:
                selected.append(human)

    if _human_required(task, [a for a in type_agents if a]):
        selected = _force_human(selected, humans, max_size)

    return selected[:max_size]


def _human_required(task: dict, type_agents: list[dict]) -> bool:
    """Whether a human must appear in the shortlist regardless of task type."""
    if task.get("requires_judgment"):
        return True
    if task.get("type") == "operational" and not task.get("is_recurring", False):
        return True
    return not type_agents


def _force_human(selected: list[dict], humans: list[dict], max_size: int) -> list[dict]:
    """Guarantee a human survives the `[:max_size]` truncation."""
    if not humans:
        # Nothing we can do — the pool has no people in it. Say so, loudly:
        # every task will route to an agent or to the D5 human fallback with no
        # candidate attached, and that is a fixture problem, not a routing one.
        logger.warning("resource pool contains no human candidates; human routing is unreachable")
        return selected
    if any(r.get("type") == "human" for r in selected[:max_size]):
        return selected
    human = next((h for h in humans if h not in selected), humans[0])
    keep = [r for r in selected if r is not human][: max_size - 1]
    return keep + [human]


# ─── The agent ────────────────────────────────────────────────────────────────

class TaskAnalysisAgent:
    """Multi-turn requirement analysis → task decomposition → resource routing.

    All conversational state lives in `self.state`, a plain JSON-serialisable
    dict (D4). Everything else — the client, the model id, the resource pool,
    the cost lookup, the trace hook — is injected collaborators, so
    `from_state(state, llm_client=...)` fully reconstructs an agent.
    """

    def __init__(
        self,
        llm_client=None,
        model: str | None = None,
        max_turns: int | None = None,
        resource_pool: list[dict] | None = None,
        cost_lookup: Mapping[str, str] | None = None,
        on_llm_call: Callable[[dict], None] | None = None,
    ):
        """
        Args:
            llm_client: OpenAI-compatible client. Defaults to
                `app.agents.agents.get_llm_client()`, resolved through the
                module object so the existing `fake_llm` test seam
                (monkeypatching that one name) keeps working.
            model: model id. Defaults to `app.agents.agents.get_model()`.
            max_turns: clarification calls allowed before forced extraction.
                Defaults to `$HIRENET_TASK_AGENT_MAX_TURNS`, else 6.
            resource_pool: resources to route against. Defaults, lazily, to the
                same pool v1 uses (`candidate_profile.get_all_resources()`).
            cost_lookup: resource id → cost hint, passed to the decision policy.
            on_llm_call: called with one record dict after **every** LLM call —
                `{stage, model, messages, response_text, parsed_ok,
                input_tokens, output_tokens, time_ms, cost_usd}`. WP3b uses it
                to write `analysis_traces` rows; this class never touches the DB.
                An exception raised by the hook is logged and swallowed: losing
                telemetry must not lose the employer's analysis.
        """
        self.client = llm_client if llm_client is not None else agents_module.get_llm_client()
        self.model = model if model is not None else agents_module.get_model()
        self.max_turns = _resolve_max_turns(max_turns)
        self._resource_pool = resource_pool
        self.cost_lookup = cost_lookup
        self.on_llm_call = on_llm_call
        self.state: dict = _empty_state()

    # ── state (D4) ────────────────────────────────────────────────────────────

    def to_state(self) -> dict:
        """Return the full agent state as a plain, JSON-serialisable dict."""
        return copy.deepcopy(self.state)

    @classmethod
    def from_state(cls, state: dict, **ctor_kwargs) -> "TaskAnalysisAgent":
        """Rebuild an agent from `to_state()` output plus injected collaborators."""
        agent = cls(**ctor_kwargs)
        agent.state = _normalise_state(state)
        return agent

    @property
    def turn_count(self) -> int:
        return self.state["turn_count"]

    @property
    def requirement(self) -> dict | None:
        return self.state["requirement"]

    @property
    def is_complete(self) -> bool:
        return self.state["requirement"] is not None

    # ── conversation ──────────────────────────────────────────────────────────

    def start(self, message: str) -> dict:
        """Open the conversation with the employer's initial description.

        Resets the conversational state (history, turns, requirement, tasks,
        decisions) but **not** `usage` — money already spent stays on the bill.
        """
        self.state["initial_input"] = message
        self.state["history"] = [
            {"role": "system", "content": load_prompt("requirement_system")},
            {"role": "user", "content": message},
        ]
        self.state["turn_count"] = 0
        self.state["requirement"] = None
        self.state["forced_extraction_done"] = False
        self.state["tasks"] = []
        self.state["decisions"] = []
        return self._advance()

    def reply(self, message: str) -> dict:
        """Continue the conversation with the employer's answer."""
        if self._gave_up():
            # D3: forced extraction already failed. Repeating the same LLM calls
            # would spend money to produce the same failure, so return the same
            # message without calling the model at all.
            return self._payload(EXTRACTION_FAILED_MESSAGE)
        self.state["history"].append({"role": "user", "content": message})
        return self._advance()

    def usage_summary(self) -> dict:
        """Totals for this session: calls, tokens, wall time, estimated cost.

        `total_cost_usd` is None when nothing could be priced, and
        `unpriced_calls` says how many calls are missing from it — a cost total
        that silently omits calls is worse than no total.
        """
        usage = self.state["usage"]
        by_stage: dict[str, int] = {}
        for call in usage["calls"]:
            by_stage[call["stage"]] = by_stage.get(call["stage"], 0) + 1
        return {
            "call_count": len(usage["calls"]),
            "total_input_tokens": usage["total_input_tokens"],
            "total_output_tokens": usage["total_output_tokens"],
            "total_time_ms": usage["total_time_ms"],
            "total_cost_usd": usage["total_cost_usd"],
            "unpriced_calls": usage["unpriced_calls"],
            "by_stage": by_stage,
        }

    # ── decomposition ─────────────────────────────────────────────────────────

    def decompose(self) -> list[dict]:
        """Break the extracted requirement into task units.

        Each item is validated against `app/schemas/task.json`; the `type` enum
        is advisory (D10 — logged, never a rejection). An item that fails for
        any other reason gets one repair attempt through
        `validation.validate_llm_output`, and is dropped with a warning if the
        repair does not fix it: a task missing `id` or `name` would KeyError
        three stages later, where the cause is invisible.

        Returns the validated tasks (possibly empty — v1 raised here and 500'd
        the route instead).
        """
        requirement = self.state["requirement"]
        if not requirement:
            raise ValueError("decompose() called before a requirement was extracted")

        messages = [
            {"role": "system", "content": load_prompt("decomposition_system")},
            {"role": "user", "content": self._decomposition_user_prompt(requirement)},
        ]

        raw_tasks: list = []
        for attempt in range(DECOMPOSE_RETRIES + 1):
            record = self._chat("decompose", messages, DECOMPOSE_TEMPERATURE)
            parsed = self._parse_task_list(record["response_text"])
            self._emit(record, parsed is not None)
            if parsed is not None:
                raw_tasks = parsed
                break
            logger.warning(
                "decomposition output could not be parsed (attempt %d/%d)",
                attempt + 1,
                DECOMPOSE_RETRIES + 1,
            )

        tasks = self._validate_task_items(raw_tasks)
        self.state["tasks"] = tasks
        return tasks

    # ── routing ───────────────────────────────────────────────────────────────

    def decide_all(self, resources: list[dict] | None = None) -> dict:
        """Shortlist, evaluate and route every decomposed task.

        Returns the wrapper object `{"decisions": [...]}` — §7.2 of the audit:
        `_build_decision_summary` and `generate_jd_report` both call
        `.get("decisions", [])` on it, so a bare list breaks the backend.

        Every element is validated against `app/schemas/task_decision.json`
        before it is returned. A failure there is *our* bug, not the model's
        (the LLM's contribution is sanitised in `_evaluate_resource` first), so
        it raises rather than degrading quietly.
        """
        pool = resources if resources is not None else self._pool()
        decisions = []

        for task in self.state["tasks"]:
            shortlist = shortlist_resources(task, pool)
            evaluations = sort_evaluations(
                [self._evaluate_resource(resource, task) for resource in shortlist]
            )
            task_decision = {
                "task_id": task.get("id", ""),
                "task_name": task.get("name", ""),
                "task_type": task.get("type", ""),
                # D6 / audit risk 5: v1 never wrote this, and job_design.py:126
                # reads it — every JD so far was written from an empty description.
                "task_description": task.get("description", ""),
                "evaluations": evaluations,
                "recommendation": decide(evaluations, task, cost_lookup=self.cost_lookup),
            }
            for key in ("estimated_hours", "requires_judgment", "is_recurring"):
                if key in task:
                    task_decision[key] = task[key]

            validate_task_decision(task_decision)
            decisions.append(task_decision)

        self.state["decisions"] = decisions
        return {"decisions": decisions}

    # ── internals: conversation ───────────────────────────────────────────────

    def _advance(self) -> dict:
        """One clarification turn, plus extraction / forced extraction if due."""
        record = self._chat("clarify", self.state["history"], CLARIFY_TEMPERATURE)
        text = record["response_text"]
        self.state["history"].append({"role": "assistant", "content": text})
        self.state["turn_count"] += 1

        if is_prompt_echo(text):
            # The model is quoting our own system prompt, which contains both
            # the marker and the empty JSON template (g15). Anything extracted
            # from it would be our text, not the employer's requirement, so this
            # turn is simply not a completion — same as a parse failure.
            logger.warning("clarify response echoes the system prompt; skipping extraction")
            self._emit(record, False, reason=PROMPT_ECHO_REASON)
        elif COMPLETION_MARKER in text:
            # The LAST marker, not the first: text before it can only be the
            # model narrating (or quoting) the instruction to emit one.
            requirement = self._extract_requirement(text.rsplit(COMPLETION_MARKER, 1)[1], record)
            if requirement is not None:
                self.state["requirement"] = requirement
                return self._payload(text)
            # Compat with v1 (`app.py:176-179`): when the marker is there but the
            # JSON is unusable, `is_complete` stays False and the raw text is
            # still handed to the user, who sees what the model actually said.
        else:
            self._emit(record, True)

        if self.state["turn_count"] >= self.max_turns and not self.state["forced_extraction_done"]:
            return self._forced_extraction(text)

        return self._payload(text)

    def _forced_extraction(self, last_response: str) -> dict:
        """D3: at the turn cap, ask once for the requirement JSON and stop."""
        self.state["forced_extraction_done"] = True
        logger.info("turn cap %d reached; forcing requirement extraction", self.max_turns)

        messages = list(self.state["history"]) + [
            {"role": "user", "content": load_prompt("force_extract")}
        ]
        record = self._chat("extract", messages, EXTRACT_TEMPERATURE)
        requirement = self._extract_requirement(record["response_text"], record)

        if requirement is None:
            logger.warning("forced extraction failed; the agent will stop calling the LLM")
            return self._payload(EXTRACTION_FAILED_MESSAGE)

        self.state["requirement"] = requirement
        # The employer's last visible turn is still the model's own words; the
        # forced JSON is machinery, not conversation.
        return self._payload(last_response)

    def _gave_up(self) -> bool:
        return self.state["forced_extraction_done"] and self.state["requirement"] is None

    def _extract_requirement(self, raw: str, source_record: dict) -> dict | None:
        """Parse + validate a requirement, repairing once through the same client.

        `source_record` is the not-yet-emitted record of the call that produced
        `raw`; its `parsed_ok` is only knowable here. Records are emitted in call
        order, so a trace reads: clarify(parsed_ok=false) → extract(parsed_ok=true).

        Returns None (never raises) when the requirement cannot be salvaged —
        v1's route swallowed every exception here (`app.py:178-179`), and a 500
        on a clarification turn would drop the whole conversation.
        """
        pending = [source_record]

        def flush(ok: bool, reason: str | None = None) -> None:
            if pending:
                self._emit(pending.pop(), ok, reason=reason)

        def repair(repair_prompt: str) -> str:
            flush(False)
            record = self._chat(
                "extract",
                [{"role": "user", "content": repair_prompt}],
                EXTRACT_TEMPERATURE,
            )
            pending.append(record)
            return record["response_text"]

        try:
            requirement = validate_llm_output(
                raw,
                "requirement",
                llm_fn=repair,
                max_retries=REQUIREMENT_REPAIR_RETRIES,
            )
        except Exception:
            logger.warning("requirement extraction failed after repair", exc_info=True)
            flush(False)
            return None

        # Schema-valid, but is it the employer's requirement or our own template
        # coming back at us (g15)? A rejection here is treated exactly like a
        # parse failure: the turn is not a completion and the conversation goes on.
        rejection = requirement_rejection_reason(requirement)
        if rejection is not None:
            logger.warning("rejecting extracted requirement (%s): %s", rejection, requirement)
            flush(False, reason=rejection)
            return None

        flush(True)
        return requirement

    # ── internals: decomposition ──────────────────────────────────────────────

    def _decomposition_user_prompt(self, requirement: dict) -> str:
        """v1's user prompt (`agents.py:122-128`), defaults included."""
        return render_prompt(
            "decomposition_user",
            project_name=requirement.get("project_name", "未知"),
            core_description=requirement.get("core_description", ""),
            tasks_hint=", ".join(requirement.get("tasks_hint", [])),
            duration=requirement.get("duration", "unknown"),
            team_context=requirement.get("team_context", "未知"),
        )

    @staticmethod
    def _parse_task_list(raw: str) -> list | None:
        """Pull the task array out of a decomposition response, or None."""
        try:
            data = parse_llm_json(raw)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return data["tasks"]
        return None

    def _validate_task_items(self, raw_tasks: list) -> list[dict]:
        """Validate each task, repairing at most `MAX_TASK_REPAIR_CALLS` of them."""
        validated: list[dict] = []
        repairs_left = MAX_TASK_REPAIR_CALLS

        for item in raw_tasks:
            error = _task_schema_error(item)
            if error is None:
                _warn_on_advisory_type(item)
                validated.append(item)
                continue

            if repairs_left <= 0:
                logger.warning("dropping invalid task (no repair budget left): %s", error)
                continue

            repairs_left -= 1
            repaired = self._repair_task(item, error)
            if repaired is None:
                continue
            _warn_on_advisory_type(repaired)
            validated.append(repaired)

        return validated

    def _repair_task(self, item: object, error: str) -> dict | None:
        """One repair round-trip for a single malformed task item.

        Uses `validation.validate_llm_output`'s own repair prompt so the wording
        of repair prompts lives in one place. Note the repaired item is held to
        the full `task.json` schema, enum included: when we are explicitly
        asking the model for a schema-conformant task, insisting on the
        vocabulary is fair — the advisory rule (D10) exists to protect *inbound*
        types that other routes already emit, not to license a second bad guess.
        """
        logger.warning("task item failed schema validation, attempting one repair: %s", error)
        pending: list[dict] = []

        def repair(repair_prompt: str) -> str:
            record = self._chat(
                "decompose",
                [{"role": "user", "content": repair_prompt}],
                DECOMPOSE_TEMPERATURE,
            )
            # Whether this output is usable is only known after
            # validate_llm_output has judged it, so the record is held back and
            # stamped below rather than guessed at here.
            pending.append(record)
            return record["response_text"]

        try:
            repaired = validate_llm_output(
                json.dumps(item, ensure_ascii=False),
                "task",
                llm_fn=repair,
                max_retries=1,
            )
        except Exception:
            logger.warning("task repair failed; dropping the task", exc_info=True)
            for record in pending:
                self._emit(record, False)
            return None
        for index, record in enumerate(pending):
            self._emit(record, index == len(pending) - 1)
        return repaired

    # ── internals: evaluation ─────────────────────────────────────────────────

    def _evaluate_resource(self, resource: dict, task: dict) -> dict:
        """One LLM call scoring one resource against one task (v1's L3).

        Never raises: an unparseable or nonsensical evaluation becomes the
        `confidence: 0` fallback record. v1 let this exception reach the route
        as a 500 (`agents.py:404`), which threw away every other evaluation in
        the run because one of them came back malformed.
        """
        prompt = render_prompt(
            "resource_evaluation",
            resource_name=resource["name"],
            resource_kind="AI Agent" if resource["type"] == "agent" else "人类候选人",
            capability_desc=(
                resource.get("capability_summary")
                or "、".join(resource.get("capabilities", []))
            ),
            task_name=task.get("name", ""),
            task_description=task.get("description", ""),
            task_type=task.get("type", ""),
            requires_judgment="是" if task.get("requires_judgment") else "否",
        )
        record = self._chat(
            "evaluate", [{"role": "user", "content": prompt}], EVALUATE_TEMPERATURE
        )

        evaluation = _coerce_evaluation(record["response_text"])
        self._emit(record, evaluation is not None)
        if evaluation is None:
            logger.warning(
                "evaluation of %s for task %s unusable; scoring it %s",
                resource.get("id"),
                task.get("id"),
                EVALUATION_FALLBACK_CONFIDENCE,
            )
            evaluation = {
                "confidence": EVALUATION_FALLBACK_CONFIDENCE,
                "reason": EVALUATION_FALLBACK_REASON,
                "strengths": [],
            }

        # Resource identity is ours, not the model's (v1 `agents.py:225-227`).
        evaluation["resource_id"] = resource["id"]
        evaluation["resource_name"] = resource["name"]
        evaluation["resource_type"] = resource["type"]
        return evaluation

    # ── internals: LLM plumbing and accounting (D8) ───────────────────────────

    def _pool(self) -> list[dict]:
        if self._resource_pool is None:
            self._resource_pool = candidate_profile.get_all_resources()
        return self._resource_pool

    def _chat(self, stage: str, messages: list[dict], temperature: float) -> dict:
        """Make one LLM call, account for it, and return its (unemitted) record."""
        started = time.monotonic()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        time_ms = int((time.monotonic() - started) * 1000)

        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        input_tokens = _int_or_none(getattr(usage, "prompt_tokens", None))
        output_tokens = _int_or_none(getattr(usage, "completion_tokens", None))
        cost_usd = estimate_cost_usd(self.model, input_tokens, output_tokens)

        call = {
            "stage": stage,
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "time_ms": time_ms,
            "cost_usd": cost_usd,
        }
        self._account(call)

        record = dict(call)
        # Snapshot: `messages` is often `self.state["history"]`, a live list the
        # agent keeps appending to.
        record["messages"] = [dict(m) for m in messages]
        record["response_text"] = text
        return record

    def _account(self, call: dict) -> None:
        usage = self.state["usage"]
        usage["calls"].append(call)
        if call["input_tokens"] is not None:
            usage["total_input_tokens"] += call["input_tokens"]
        if call["output_tokens"] is not None:
            usage["total_output_tokens"] += call["output_tokens"]
        usage["total_time_ms"] += call["time_ms"]
        if call["cost_usd"] is None:
            usage["unpriced_calls"] += 1
        else:
            usage["total_cost_usd"] = round((usage["total_cost_usd"] or 0.0) + call["cost_usd"], 8)

    def _emit(self, record: dict, parsed_ok: bool, reason: str | None = None) -> None:
        """Hand one finished call to the `on_llm_call` hook (WP3b writes traces).

        `reason` is set only when there is one (`prompt_echo`,
        `template_placeholder`, `core_description_too_short`), so an ordinary
        record keeps exactly the fields it always had. The trace writer
        (`app/app.py:_v2_trace_writer`) picks the columns it needs by name, so
        the extra key is a trace-reader's hint, not a schema change.
        """
        record["parsed_ok"] = bool(parsed_ok)
        if reason is not None:
            record["reason"] = reason
        if self.on_llm_call is None:
            return
        try:
            self.on_llm_call(record)
        except Exception:
            logger.exception("on_llm_call hook raised; continuing without the trace")

    def _payload(self, response: str) -> dict:
        """The four keys the routes return (audit §7.2) plus `turn_count` (D3)."""
        return {
            "response": response,
            "is_complete": self.is_complete,
            "requirement": self.state["requirement"],
            "turn_count": self.state["turn_count"],
        }


# ─── Module helpers ───────────────────────────────────────────────────────────

def _empty_state() -> dict:
    return {
        "history": [],
        "requirement": None,
        "initial_input": "",
        "turn_count": 0,
        "tasks": [],
        "decisions": [],
        "usage": {
            "calls": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_time_ms": 0,
            "total_cost_usd": None,
            "unpriced_calls": 0,
        },
        "forced_extraction_done": False,
    }


def _normalise_state(state: dict) -> dict:
    """Deep-copy a state dict and fill in any key an older session is missing."""
    merged = _empty_state()
    incoming = copy.deepcopy(state or {})
    usage = incoming.pop("usage", None)
    merged.update(incoming)
    if isinstance(usage, dict):
        merged["usage"].update(usage)
    return merged


def _resolve_max_turns(explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit)
    raw = os.getenv(MAX_TURNS_ENV)
    if not raw:
        return DEFAULT_MAX_TURNS
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using %d", MAX_TURNS_ENV, raw, DEFAULT_MAX_TURNS)
        return DEFAULT_MAX_TURNS
    if value < 1:
        logger.warning("%s=%d must be >= 1; using %d", MAX_TURNS_ENV, value, DEFAULT_MAX_TURNS)
        return DEFAULT_MAX_TURNS
    return value


def _int_or_none(value: object) -> int | None:
    """Token counts: keep `None` as `None` — 0 and "unknown" are different facts."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _task_schema_error(item: object) -> str | None:
    """None if the item satisfies `task.json` (type enum aside), else the error."""
    try:
        jsonschema.validate(instance=item, schema=RELAXED_TASK_SCHEMA)
    except jsonschema.ValidationError as exc:
        return exc.message
    return None


def _warn_on_advisory_type(task: dict) -> None:
    """D10: an out-of-vocabulary task type is a warning, never a rejection."""
    task_type = task.get("type")
    if task_type not in TASK_TYPES:
        logger.warning(
            "task %r has out-of-vocabulary type %r (allowed: %s) — kept, see D10",
            task.get("id"),
            task_type,
            ", ".join(TASK_TYPES),
        )


def _coerce_evaluation(raw: str) -> dict | None:
    """Parse one resource evaluation and make it schema-safe, or return None.

    `task_decision.json` types the evaluation fields, so a model that answers
    `"confidence": "high"` would fail validation of the whole decision and take
    down a run that is otherwise fine. Known keys that are the wrong type are
    dropped (or, for `confidence`, treated as a failed evaluation); unknown keys
    are kept — the schema allows them and they are useful in a trace.
    """
    try:
        parsed = parse_llm_json(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None

    confidence = parsed.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not 0 <= confidence <= 1:
        return None

    evaluation = dict(parsed)
    evaluation["confidence"] = float(confidence)
    if not isinstance(parsed.get("can_complete"), bool):
        evaluation.pop("can_complete", None)
    for key in ("reason", "estimated_time"):
        if not isinstance(parsed.get(key), str):
            evaluation.pop(key, None)
    strengths = parsed.get("strengths")
    if not (isinstance(strengths, list) and all(isinstance(s, str) for s in strengths)):
        evaluation.pop("strengths", None)
    return evaluation
