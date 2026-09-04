"""Structural scorer for the golden evaluation set (Stage 1 / D12, spec §3).

The score is deliberately mechanical: it answers "did the pipeline produce the
shape the golden set says it should", never "was the answer good". Quality is
the LLM judge's job (`evals/judge.py`) and its 1–5 score is recorded separately
and never averaged into this one.

Spec §3 defines the per-case structural score as the mean of five components:

    1. requirement       ratio of the requirement checks that passed
    2. task_count        0/1 — number of tasks inside `count_range`
    3. must_include      ratio of expected task entries that matched
    4. must_not_include  0/1 — no forbidden keyword appeared
    5. decisions         0/1 — routing distribution inside every stated bound

A component that the case does not assert anything about is **skipped**
(reported as `None`) and left out of the mean, rather than scored 1.0. Scoring
an unstated expectation as a pass would quietly reward cases for saying less.
There is exactly one deliberate exception, contract (a) below.

Two contracts the golden set relies on (golden_set_review.md, ambiguity #9),
both exercised by `g18` and both pinned by tests:

    (a) An **empty `must_include` list scores 1.0**, not "skipped". g18's whole
        point is that no particular task has to exist; the correct behaviour is
        an explicit pass, so that the g18 row is comparable with the others.
    (b) A `count_range` **lower bound of 0 means zero tasks is a pass.** Falls
        out of the inclusive `lo <= n <= hi` test, but it is easy to "fix" into
        a bug (`n and lo <= n`), so it has its own test.

Matching rules, stated once so the report can be read without the source:

* Keyword matching is a case-insensitive substring test. Chinese has no word
  boundaries, so substring is the only workable rule; the English case (g07)
  gets the same treatment for symmetry.
* `must_include[].name_keywords_any` is matched against the **task name only**
  — the golden set names the key `name_keywords_any`, and matching the
  description too would let a task that is *mentioned* count as a task that
  *exists*.
* `must_not_include_keywords` is matched against the task **name and
  description**, because that check is about contamination (a hallucinated
  domain, or an injected instruction bleeding through, as in g15), and
  contamination usually lands in the prose.
* `must_include[].routing` is compared against
  `decisions[].recommendation.decision` joined on `task_id`. When a task has no
  decision row, or the entry omits `routing`, the routing constraint is simply
  not applied — omitted expectations are skipped, never failed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The five component names, in spec order. The report renders them in this order.
COMPONENT_NAMES = (
    "requirement",
    "task_count",
    "must_include",
    "must_not_include",
    "decisions",
)

#: Where the committed golden set lives.
GOLDEN_SET_PATH = Path(__file__).parent / "golden" / "golden_set.json"


def load_golden_set(path: str | Path | None = None) -> dict:
    """Load the golden set JSON (the committed copy by default)."""
    with open(path or GOLDEN_SET_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def select_cases(golden: dict, selector: str) -> list[dict]:
    """Pick cases by `all` or a comma-separated id list, preserving file order.

    An unknown id is an error rather than a silent empty run: a typo in
    `--cases g0l` must not look like "that case passed with no output".
    """
    cases = golden["cases"]
    if selector.strip().lower() == "all":
        return list(cases)
    wanted = [part.strip() for part in selector.split(",") if part.strip()]
    by_id = {case["id"]: case for case in cases}
    unknown = [cid for cid in wanted if cid not in by_id]
    if unknown:
        raise ValueError(f"unknown case id(s): {', '.join(unknown)}")
    order = {case["id"]: i for i, case in enumerate(cases)}
    return sorted((by_id[cid] for cid in wanted), key=lambda c: order[c["id"]])


# ─── low-level helpers ────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _contains_any(haystack: str, keywords: list[str]) -> str | None:
    """Return the first keyword found in `haystack`, else None (case-insensitive)."""
    lowered = haystack.lower()
    for keyword in keywords or []:
        if keyword and keyword.lower() in lowered:
            return keyword
    return None


def routing_by_task_id(decisions: Any) -> dict[str, str]:
    """`task_id` → recommendation decision, from the `{"decisions": [...]}` wrapper.

    `recommendation` is seeded as None by the v1 engine and only overwritten
    when a task has at least one surviving evaluation (agents.py:396), so the
    `or {}` is load-bearing, not defensive noise.
    """
    if isinstance(decisions, dict):
        items = decisions.get("decisions") or []
    elif isinstance(decisions, list):
        items = decisions
    else:
        items = []
    mapping: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        decision = (item.get("recommendation") or {}).get("decision")
        if isinstance(decision, str):
            mapping[str(item.get("task_id", ""))] = decision
    return mapping


def decision_counts(decisions: Any) -> dict[str, int]:
    """How many tasks were routed to agent / human / hybrid (and to nothing)."""
    counts = {"agent": 0, "human": 0, "hybrid": 0, "none": 0}
    if isinstance(decisions, dict):
        items = decisions.get("decisions") or []
    elif isinstance(decisions, list):
        items = decisions
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        decision = (item.get("recommendation") or {}).get("decision")
        if decision in counts:
            counts[decision] += 1
        else:
            counts["none"] += 1
    return counts


# ─── the five components ──────────────────────────────────────────────────────

def score_requirement(expected: dict | None, requirement: Any) -> tuple[float | None, list[dict]]:
    """Component 1 — ratio of asserted requirement fields that came out right.

    `null` in the golden set means "do not check this field" (schema_note), so a
    case that asserts nothing scores `None` and drops out of the mean.
    """
    expected = expected or {}
    checks: list[dict] = []
    req = requirement if isinstance(requirement, dict) else {}

    keywords = expected.get("core_description_keywords_any")
    if keywords:
        hit = _contains_any(_text(req.get("core_description")), keywords)
        checks.append({
            "check": "core_description_keywords_any",
            "expected": keywords,
            "actual": _text(req.get("core_description")),
            "passed": hit is not None,
            "matched": hit,
        })

    for field in ("duration", "budget_hint"):
        want = expected.get(field)
        if want is None:
            continue
        got = req.get(field)
        checks.append({
            "check": field,
            "expected": want,
            "actual": got,
            "passed": got == want,
        })

    if not checks:
        return None, checks
    passed = sum(1 for check in checks if check["passed"])
    return passed / len(checks), checks


def score_task_count(count_range: Any, tasks: list) -> tuple[float | None, dict]:
    """Component 2 — 0/1, is `len(tasks)` inside the inclusive range.

    Contract (b): a lower bound of 0 makes an empty task list a pass.
    """
    if not (isinstance(count_range, (list, tuple)) and len(count_range) == 2):
        return None, {"check": "count_range", "expected": count_range, "actual": len(tasks),
                      "passed": None, "note": "no count_range asserted"}
    low, high = count_range
    count = len(tasks)
    passed = low <= count <= high
    return (1.0 if passed else 0.0), {
        "check": "count_range",
        "expected": [low, high],
        "actual": count,
        "passed": passed,
    }


def _entry_matches(entry: dict, task: dict, routing: dict[str, str]) -> tuple[bool, dict]:
    """Does one task satisfy every constraint the `must_include` entry states."""
    reasons: dict[str, Any] = {}

    keywords = entry.get("name_keywords_any") or []
    hit = _contains_any(_text(task.get("name")), keywords)
    reasons["name_keyword"] = hit
    if keywords and hit is None:
        return False, reasons

    if "type" in entry:
        reasons["type"] = {"expected": entry["type"], "actual": task.get("type")}
        if task.get("type") != entry["type"]:
            return False, reasons

    if "requires_judgment" in entry:
        actual = task.get("requires_judgment")
        reasons["requires_judgment"] = {"expected": entry["requires_judgment"], "actual": actual}
        if bool(actual) != bool(entry["requires_judgment"]):
            return False, reasons

    if "routing" in entry:
        actual = routing.get(str(task.get("id", "")))
        reasons["routing"] = {"expected": entry["routing"], "actual": actual}
        if actual != entry["routing"]:
            return False, reasons

    return True, reasons


def score_must_include(
    must_include: list | None,
    tasks: list,
    decisions: Any,
) -> tuple[float | None, list[dict]]:
    """Component 3 — ratio of expected task entries that some real task satisfied.

    Contract (a): an **empty list scores 1.0**, with an explicit detail row so
    the report shows why the component is a pass rather than looking like a
    silent default.
    """
    entries = list(must_include or [])
    if not entries:
        return 1.0, [{
            "check": "must_include",
            "expected": [],
            "passed": True,
            "note": "must_include is empty — scored 1.0 by contract (golden_set_review §9a)",
        }]

    routing = routing_by_task_id(decisions)
    details: list[dict] = []
    matched = 0
    for entry in entries:
        best: dict | None = None
        hit_task: dict | None = None
        for task in tasks:
            if not isinstance(task, dict):
                continue
            ok, reasons = _entry_matches(entry, task, routing)
            if ok:
                hit_task = task
                best = reasons
                break
            # Keep the most informative near-miss: one that matched the name.
            if best is None or (reasons.get("name_keyword") and not best.get("name_keyword")):
                best = reasons
        details.append({
            "check": "must_include",
            "expected": entry,
            "passed": hit_task is not None,
            "matched_task": (hit_task or {}).get("name") if hit_task else None,
            "closest": best,
        })
        matched += 1 if hit_task else 0

    return matched / len(entries), details


def score_must_not_include(keywords: list | None, tasks: list) -> tuple[float | None, dict]:
    """Component 4 — 0/1, did a forbidden keyword appear in any task name/description.

    An empty keyword list asserts nothing, so the component is skipped (`None`).
    Unlike `must_include` there is no contract forcing it to 1.0 — no case
    depends on it, and awarding a free point for an unstated expectation would
    make cases with fewer assertions score higher.
    """
    words = [w for w in (keywords or []) if w]
    if not words:
        return None, {"check": "must_not_include_keywords", "expected": [], "passed": None,
                      "note": "nothing asserted — component skipped"}
    violations = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        haystack = f"{_text(task.get('name'))}\n{_text(task.get('description'))}"
        hit = _contains_any(haystack, words)
        if hit:
            violations.append({"task": _text(task.get("name")), "keyword": hit})
    return (0.0 if violations else 1.0), {
        "check": "must_not_include_keywords",
        "expected": words,
        "passed": not violations,
        "violations": violations,
    }


#: `expected.decisions` keys → (routing bucket, comparison).
_DECISION_BOUNDS = {
    "agent_min": ("agent", "min"),
    "agent_max": ("agent", "max"),
    "human_min": ("human", "min"),
    "human_max": ("human", "max"),
    "hybrid_min": ("hybrid", "min"),
    "hybrid_max": ("hybrid", "max"),
}


def score_decisions(expected: dict | None, decisions: Any) -> tuple[float | None, dict]:
    """Component 5 — 0/1, is the routing distribution inside every stated bound.

    The golden set keeps these ranges deliberately wide (golden_set_review §10):
    a pass here means "no gross routing failure", not "the routing was good".
    """
    expected = expected or {}
    bounds = {k: v for k, v in expected.items() if k in _DECISION_BOUNDS}
    counts = decision_counts(decisions)
    if not bounds:
        return None, {"check": "decisions", "expected": {}, "actual": counts, "passed": None,
                      "note": "nothing asserted — component skipped"}
    failures = []
    for key, value in bounds.items():
        bucket, kind = _DECISION_BOUNDS[key]
        actual = counts[bucket]
        ok = actual >= value if kind == "min" else actual <= value
        if not ok:
            failures.append({"bound": key, "expected": value, "actual": actual})
    return (0.0 if failures else 1.0), {
        "check": "decisions",
        "expected": bounds,
        "actual": counts,
        "passed": not failures,
        "failures": failures,
    }


# ─── the case-level score ─────────────────────────────────────────────────────

def score_case(case: dict, result: dict | None) -> dict:
    """Score one golden case against one `/api/analyze/decide` response body.

    Args:
        case: a golden-set case dict.
        result: the decide response — `{"requirement", "tasks", "decisions", ...}`.
            Pass `None` when the run errored or returned a non-200; every
            component then scores 0.0 and `structural_score` is 0.0, per WP4
            ("any exception/500 → structural score 0").

    Returns:
        `{"case_id", "category", "structural_score", "components", "details"}`.
        `components` values are floats or `None` (skipped); `structural_score`
        is the mean of the non-None ones, and 0.0 when everything was skipped
        *because the run failed*.
    """
    expected = case.get("expected") or {}
    tasks_expected = expected.get("tasks") or {}

    if result is None:
        return {
            "case_id": case["id"],
            "category": case.get("category"),
            "structural_score": 0.0,
            "components": {name: 0.0 for name in COMPONENT_NAMES},
            "details": {"error": "no result — the run failed; every component scored 0.0"},
        }

    tasks = result.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []
    decisions = result.get("decisions")

    req_score, req_details = score_requirement(expected.get("requirement"), result.get("requirement"))
    count_score, count_details = score_task_count(tasks_expected.get("count_range"), tasks)
    include_score, include_details = score_must_include(
        tasks_expected.get("must_include"), tasks, decisions
    )
    exclude_score, exclude_details = score_must_not_include(
        tasks_expected.get("must_not_include_keywords"), tasks
    )
    decision_score, decision_details = score_decisions(expected.get("decisions"), decisions)

    components = {
        "requirement": req_score,
        "task_count": count_score,
        "must_include": include_score,
        "must_not_include": exclude_score,
        "decisions": decision_score,
    }
    scored = [value for value in components.values() if value is not None]
    structural = sum(scored) / len(scored) if scored else 0.0

    return {
        "case_id": case["id"],
        "category": case.get("category"),
        "structural_score": round(structural, 4),
        "components": components,
        "details": {
            "requirement": req_details,
            "task_count": count_details,
            "must_include": include_details,
            "must_not_include": exclude_details,
            "decisions": decision_details,
        },
    }


def failure_bullets(score: dict, limit: int = 4) -> list[str]:
    """Short, quotable reasons this case lost points — for the report's failure modes.

    Only reports what the scorer actually observed (task names, expected vs
    actual values). No speculation about *why* the model did it.
    """
    bullets: list[str] = []
    details = score.get("details") or {}
    if "error" in details:
        return [str(details["error"])]

    for check in details.get("requirement") or []:
        if check.get("passed"):
            continue
        if check["check"] == "core_description_keywords_any":
            bullets.append(
                f"requirement: none of {check['expected']} in core_description "
                f"({(check.get('actual') or '')[:60]!r})"
            )
        else:
            bullets.append(
                f"requirement.{check['check']}: expected {check['expected']!r}, got {check.get('actual')!r}"
            )

    count = details.get("task_count") or {}
    if count.get("passed") is False:
        bullets.append(f"task count {count['actual']} outside {count['expected']}")

    for entry in details.get("must_include") or []:
        if entry.get("passed") or entry.get("note"):
            continue
        want = entry.get("expected") or {}
        closest = entry.get("closest") or {}
        extra = ""
        for key in ("type", "routing", "requires_judgment"):
            if key in closest and isinstance(closest[key], dict):
                extra = (
                    f"; closest task differed on {key} "
                    f"(expected {closest[key]['expected']!r}, got {closest[key]['actual']!r})"
                )
                break
        bullets.append(f"missing task matching {want.get('name_keywords_any')}{extra}")

    exclude = details.get("must_not_include") or {}
    for violation in exclude.get("violations") or []:
        bullets.append(f"forbidden keyword {violation['keyword']!r} in task {violation['task']!r}")

    decisions = details.get("decisions") or {}
    for failure in decisions.get("failures") or []:
        bullets.append(
            f"routing {failure['bound']}={failure['expected']} violated (actual {failure['actual']})"
        )

    return bullets[:limit]
