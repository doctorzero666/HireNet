"""The employer side of an eval conversation (Stage 1 / WP4).

The pipeline asks clarification questions; something has to answer them the
same way every time or the eval is not reproducible. This is that something:
a scripted employer that reads `case.input.clarifications` in order.

Two behaviours matter and both come straight from the WP4 brief:

* **When the script runs out** it keeps answering, with the fixed line
  `"按你的专业判断决定即可，不需要再问我。"` — a real employer who has said
  everything they have to say does not go silent, and going silent would let a
  chatty model look better than it is.
* **There is a hard cap on turns** (default 8). v1 has no turn cap of its own
  (audit risk 3 — the reason D3 exists), so a v1 conversation can ask questions
  forever. The cap is what makes the eval terminate; a run that hits it is
  recorded with `completed=False` and is a *finding*, not a crash.

The cap counts employer replies, i.e. `/api/analyze/reply` calls. `/start` is
not a reply, so a case with an 8-turn cap makes at most 9 conversational
requests.
"""
from __future__ import annotations

#: What the employer says once `clarifications` is exhausted. Fixed text: it is
#: part of the eval protocol, so changing it changes the numbers.
DEFAULT_REPLY = "按你的专业判断决定即可，不需要再问我。"

#: Hard cap on employer replies per case.
DEFAULT_MAX_TURNS = 8


class SimulatedEmployer:
    """Deterministic employer for one golden case.

    Usage:
        employer = SimulatedEmployer(case["input"]["clarifications"])
        while not is_complete and employer.has_turns_left:
            post("/api/analyze/reply", message=employer.next_reply())
    """

    def __init__(
        self,
        clarifications: list[str] | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        default_reply: str = DEFAULT_REPLY,
    ):
        if max_turns < 0:
            raise ValueError("max_turns must be >= 0")
        self.clarifications: list[str] = list(clarifications or [])
        self.max_turns = max_turns
        self.default_reply = default_reply
        self.turns_used = 0
        self.scripted_used = 0

    @property
    def has_turns_left(self) -> bool:
        """Is the employer still allowed to reply."""
        return self.turns_used < self.max_turns

    @property
    def script_exhausted(self) -> bool:
        """Have all scripted answers been handed out."""
        return self.scripted_used >= len(self.clarifications)

    @property
    def hit_cap(self) -> bool:
        """Did this employer stop because of the cap rather than because the run finished."""
        return self.turns_used >= self.max_turns

    def next_reply(self) -> str:
        """The next employer message.

        Raises:
            RuntimeError: if called after the cap — the caller is supposed to
                check `has_turns_left`, and silently returning something here
                would let a run exceed its own budget.
        """
        if not self.has_turns_left:
            raise RuntimeError(
                f"SimulatedEmployer: turn cap {self.max_turns} already reached; "
                "check `has_turns_left` before calling next_reply()"
            )
        self.turns_used += 1
        if not self.script_exhausted:
            reply = self.clarifications[self.scripted_used]
            self.scripted_used += 1
            return reply
        return self.default_reply
