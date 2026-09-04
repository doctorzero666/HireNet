import os
import tempfile

import pytest

from app.app import create_app
from app.services.mock_settlement import MockSettlementProvider


@pytest.fixture
def client():
    # Inject MockSettlementProvider explicitly so the test suite stays
    # hermetic regardless of `.env` (HIRENET_SETTLEMENT_PROVIDER may now
    # default to `anvil`, which would otherwise try to dial localhost:8545
    # during create_app and crash hundreds of tests on CI / dev machines
    # without Anvil running). Tests that need a different provider build
    # their own client and pass config={"SETTLEMENT_PROVIDER": <other>}.
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    flask_app = create_app(config={
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "SETTLEMENT_PROVIDER": MockSettlementProvider(),
    })
    with flask_app.test_client() as c:
        yield c
    os.unlink(db_path)


@pytest.fixture
def app_db_path(client):
    """The temp DB behind the `client` fixture, for tests that read rows back.

    Stage 1 / WP3b: analysis_traces and agent_runs assertions need to open the
    same database the request just wrote to.
    """
    return client.application.config["DATABASE_PATH"]


# ──────────────────────────────────────────────────────────────────────────────
# LLM fakes — shared by the Stage 1 analysis-pipeline test files
#
# Every production LLM call in the analysis pipeline funnels through exactly one
# factory, `app.agents.agents.get_llm_client()`:
#
#   app/agents/agents.py:51   RequirementAnalysisAgent.__init__ -> get_llm_client()
#   app/agents/agents.py:120  decompose_tasks                   -> get_llm_client()
#   app/agents/agents.py:170  _llm_evaluate_resource            -> get_llm_client()
#   app/agents/agents.py:304  CareerStrategyAgent.__init__      -> get_llm_client()
#   app/agents/job_design.py:11 get_llm_client()                -> delegates to it
#
# so patching that one name is enough to keep the whole pipeline off the network.
# `no_real_llm_client` is the belt-and-braces guard: it replaces the `OpenAI`
# symbol each module actually binds, so any code path that skips the factory
# blows up loudly instead of quietly dialling api.bigmodel.cn.
# ──────────────────────────────────────────────────────────────────────────────

class FakeUsage:
    """Stand-in for `resp.usage` (OpenAI field names)."""

    def __init__(self, prompt_tokens: int = 11, completion_tokens: int = 22):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content
        self.role = "assistant"


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)
        self.finish_reason = "stop"


class FakeCompletion:
    """Stand-in for the object returned by `chat.completions.create(...)`."""

    def __init__(self, content: str, usage: FakeUsage):
        self.choices = [_FakeChoice(content)]
        self.usage = usage
        self.model = "fake-model"


class _FakeCompletions:
    def __init__(self, owner: "FakeLLMClient"):
        self._owner = owner

    def create(self, **kwargs):
        return self._owner._next_response(**kwargs)


class _FakeChat:
    def __init__(self, owner: "FakeLLMClient"):
        self.completions = _FakeCompletions(owner)


class FakeLLMClient:
    """Scripted stand-in for the Zhipu (OpenAI-compatible) client.

    Queue responses with `queue(...)`; each `chat.completions.create(...)` pops
    the next one. A queued `Exception` instance is raised instead of returned,
    and a queued callable is invoked with the create() kwargs and must return
    the response text. Running out of scripted responses is an AssertionError,
    never a silent default — an unscripted call means the test is not saying
    what it thinks it is saying.
    """

    def __init__(self, *responses):
        self.responses: list = list(responses)
        self.calls: list[dict] = []
        self.chat = _FakeChat(self)

    def queue(self, *responses) -> "FakeLLMClient":
        self.responses.extend(responses)
        return self

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _next_response(self, **kwargs):
        # Snapshot the call: production code passes `messages=self.history`,
        # a live list it keeps appending to, so storing the reference would
        # record the conversation as it ends up, not as it was sent.
        recorded = dict(kwargs)
        if isinstance(recorded.get("messages"), list):
            recorded["messages"] = [dict(m) for m in recorded["messages"]]
        self.calls.append(recorded)
        if not self.responses:
            raise AssertionError(
                f"FakeLLMClient: unscripted LLM call #{len(self.calls)} "
                f"(model={kwargs.get('model')!r}); queue another response"
            )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(**kwargs)
        return FakeCompletion(item, FakeUsage())


@pytest.fixture
def no_real_llm_client(monkeypatch):
    """Make constructing the real OpenAI client raise, everywhere it is bound.

    Opt in per test module with an autouse wrapper fixture; deliberately not
    autouse here so the pre-existing suite keeps its current behaviour.
    """
    def _boom(*args, **kwargs):
        raise AssertionError(
            "A test tried to construct the real OpenAI client. Analysis tests "
            "must run against FakeLLMClient (see the `fake_llm` fixture)."
        )

    import app.agents.agents as agents_module
    import app.agents.application_agent as application_agent_module

    monkeypatch.setattr(agents_module, "OpenAI", _boom)
    monkeypatch.setattr(application_agent_module, "OpenAI", _boom)
    return _boom


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a scripted FakeLLMClient as the pipeline's one LLM factory."""
    import app.agents.agents as agents_module

    client = FakeLLMClient()
    monkeypatch.setattr(agents_module, "get_llm_client", lambda: client)
    return client
