"""Counting / retrying / budget-enforcing wrapper around the real LLM client.

Installed at `app.agents.agents.get_llm_client` for the duration of an eval run
(that one factory is where every production LLM call in the analysis pipeline
comes from — see the map in `tests/conftest.py`), so a single object sees:

    RequirementAnalysisAgent._call_llm        (v1 clarify)
    decompose_tasks                           (v1 decompose)
    _llm_evaluate_resource                    (v1 evaluate)
    TaskAnalysisAgent._chat                   (v2 clarify/extract/decompose/evaluate)
    job_design.design_job                     (both — outside the agent)

It does three jobs the eval cannot do without:

1. **Counts.** Tokens are the primary cost metric in the WP4 report; USD is a
   derived estimate. Per call it records `{model, input_tokens, output_tokens,
   time_ms}` read off `resp.usage`, plus a best-effort `stage` label derived
   from the prompt text and the case/phase context the runner sets.
2. **Retries.** 429 and 5xx are normal on a provider under load; one of them
   mid-run would otherwise turn into a case-level `error` and a 0 score, which
   would be a measurement artefact, not a finding. Exponential backoff, at most
   `max_retries` attempts. 4xx other than 429 is *not* retried — a malformed
   request does not get better by being sent again.
3. **A run-wide token budget.** A runaway conversation on a paid API is the one
   failure mode of this harness that costs real money. When the budget is
   exhausted the proxy sets `budget_exceeded` and raises; the runner checks the
   flag after every case and stops the run cleanly, because the Flask route
   catches exceptions and would otherwise turn the abort into a plain 500.

Nothing here is imported by `app/`, and no test in `tests/` constructs a real
client through it.
"""
from __future__ import annotations

import time

#: Default run-wide cap on input+output tokens across every call the run makes,
#: pipeline and judge alike. Sized so a 20-case v1+v2 comparison cannot silently
#: turn into a large invoice; override with `--budget-tokens`.
DEFAULT_BUDGET_TOKENS = 3_000_000

#: HTTP statuses worth retrying: rate limiting and server-side failures.
RETRYABLE_STATUS = (429, 500, 502, 503, 504)

#: Exception class names that mean "transport hiccup" on the OpenAI SDK.
RETRYABLE_NAMES = (
    "RateLimitError",
    "InternalServerError",
    "APIConnectionError",
    "APITimeoutError",
    "APIConnectionTimeoutError",
)

#: Prompt fingerprints → stage label. Both pipelines send the same prompt text
#: (v2's `app/agents/prompts/*.md` are copies of v1's inline strings), so one
#: table labels calls from either version. Order matters: `force_extract` is
#: appended to a conversation that starts with the clarify system prompt.
_STAGE_MARKERS = (
    ("job_design", "岗位设计 Agent"),
    ("decompose", "任务拆解 Agent"),
    ("evaluate", "评估资源是否能完成任务"),
    ("extract", "现在请直接输出结构化需求 JSON"),
    ("clarify", "需求分析 Agent"),
)


class BudgetExceeded(RuntimeError):
    """Raised by the proxy when the run-wide token budget is spent."""


def _status_of(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def is_retryable(exc: Exception) -> bool:
    """429 / 5xx / transport errors are retryable; everything else is not."""
    status = _status_of(exc)
    if status is not None:
        return status in RETRYABLE_STATUS
    return type(exc).__name__ in RETRYABLE_NAMES


def classify_stage(messages) -> str:
    """Best-effort label for a call, from the prompt text it carries.

    Informational only — the authoritative cross-check in the report compares
    the agent's own `usage_summary()` against this proxy's totals, not these
    labels. A prompt this table does not recognise is `"other"`, never guessed.
    """
    blob = "\n".join(
        str(m.get("content", "")) for m in (messages or []) if isinstance(m, dict)
    )
    for stage, marker in _STAGE_MARKERS:
        if marker in blob:
            return stage
    return "other"


class _Completions:
    def __init__(self, owner: "CountingLLMProxy"):
        self._owner = owner

    def create(self, **kwargs):
        return self._owner._create(**kwargs)


class _Chat:
    def __init__(self, owner: "CountingLLMProxy"):
        self.completions = _Completions(owner)


class CountingLLMProxy:
    """OpenAI-compatible façade that measures, retries and caps.

    Attributes:
        records: one dict per *successful* call —
            `{case_id, phase, stage, model, input_tokens, output_tokens,
              total_tokens, time_ms, attempts}`.
        budget_exceeded: sticky flag; the runner stops the run when it is set.
    """

    def __init__(
        self,
        client,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        max_retries: int = 5,
        base_delay: float = 2.0,
        sleep=time.sleep,
        clock=time.perf_counter,
    ):
        self._client = client
        self.budget_tokens = budget_tokens
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._sleep = sleep
        self._clock = clock
        self.records: list[dict] = []
        self.total_tokens = 0
        self.budget_exceeded = False
        self.retry_events: list[dict] = []
        self.case_id: str | None = None
        self.phase: str = "pipeline"
        self.chat = _Chat(self)

    # ── context the runner sets so every call can be attributed ──────────────

    def set_context(self, case_id: str | None, phase: str = "pipeline") -> None:
        self.case_id = case_id
        self.phase = phase

    # ── measurement ──────────────────────────────────────────────────────────

    def records_for(self, case_id: str, phase: str | None = None) -> list[dict]:
        return [
            r for r in self.records
            if r["case_id"] == case_id and (phase is None or r["phase"] == phase)
        ]

    @staticmethod
    def totals(records: list[dict]) -> dict:
        """Sum a list of call records into the numbers the report prints."""
        return {
            "calls": len(records),
            "input_tokens": sum(r["input_tokens"] or 0 for r in records),
            "output_tokens": sum(r["output_tokens"] or 0 for r in records),
            "total_tokens": sum(r["total_tokens"] or 0 for r in records),
            "time_ms": sum(r["time_ms"] or 0 for r in records),
        }

    @property
    def budget_remaining(self) -> int:
        return max(0, self.budget_tokens - self.total_tokens)

    # ── the call ─────────────────────────────────────────────────────────────

    def _create(self, **kwargs):
        if self.total_tokens >= self.budget_tokens:
            self.budget_exceeded = True
            raise BudgetExceeded(
                f"token budget {self.budget_tokens} exhausted "
                f"({self.total_tokens} used); aborting before another call"
            )

        stage = classify_stage(kwargs.get("messages"))
        started = self._clock()
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_exc = exc
                if not is_retryable(exc) or attempt == self.max_retries:
                    raise
                delay = self.base_delay * (2 ** (attempt - 1))
                self.retry_events.append({
                    "case_id": self.case_id,
                    "phase": self.phase,
                    "stage": stage,
                    "attempt": attempt,
                    "error": f"{type(exc).__name__}: {exc}",
                    "sleep_s": delay,
                })
                self._sleep(delay)
                continue

            usage = getattr(resp, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "completion_tokens", None)
            total = getattr(usage, "total_tokens", None)
            if total is None:
                total = (input_tokens or 0) + (output_tokens or 0)

            record = {
                "case_id": self.case_id,
                "phase": self.phase,
                "stage": stage,
                "model": kwargs.get("model") or getattr(resp, "model", None),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total,
                "time_ms": int((self._clock() - started) * 1000),
                "attempts": attempt,
            }
            self.records.append(record)
            self.total_tokens += total or 0
            if self.total_tokens >= self.budget_tokens:
                # Flag it now; the *next* call raises. The response we already
                # paid for is still returned — throwing it away would waste it.
                self.budget_exceeded = True
            return resp

        # Unreachable: the loop either returns or raises.
        raise last_exc if last_exc else RuntimeError("CountingLLMProxy: retry loop fell through")
