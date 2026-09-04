"""Turn two raw eval directories into the v1-vs-v2 Markdown comparison.

    .venv/bin/python -m evals.report \
        evals/reports/raw/2026-09-04-v1 evals/reports/raw/2026-09-04-v2 \
        --out evals/reports/2026-09-04-v1-vs-v2.md

Everything in the output is computed from the raw JSON — including the D13
verdict, which is a mechanical comparison, not a judgement call:

    PASS  ⇔  mean(structural, v2) ≥ mean(structural, v1)
             AND  pipeline tokens(v2) ≤ 1.2 × pipeline tokens(v1)

"Top failure modes" are derived by grouping the scorer's own failure reasons —
the module never speculates about *why* a model did something, it only counts
and quotes what the scorer observed.

Reading a run that aborted on budget: the summary carries `not_run`, and those
cases are listed as such and excluded from every mean. Nothing is extrapolated.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from evals.scoring import failure_bullets

#: D13's cost ceiling: v2 may not cost more than this multiple of v1.
COST_CEILING_MULTIPLE = 1.2


def d13_verdict(
    v1_mean_structural: float | None,
    v2_mean_structural: float | None,
    v1_pipeline_tokens: int,
    v2_pipeline_tokens: int,
) -> dict:
    """The D13 gate, as arithmetic.

        PASS ⇔ mean structural(v2) ≥ mean structural(v1)
               AND pipeline tokens(v2) ≤ 1.2 × pipeline tokens(v1)

    A missing mean (a run with no scored cases) is a FAIL on the quality half,
    never a pass by default: "we could not measure it" must not read as "it was
    at least as good".

    Cost is measured on **pipeline** tokens. The judge does identical work for
    both versions and is harness overhead, not product cost; folding it in
    would dilute a real cost regression toward the ratio 1.0.
    """
    ceiling = COST_CEILING_MULTIPLE * v1_pipeline_tokens
    quality_ok = (
        v1_mean_structural is not None
        and v2_mean_structural is not None
        and v2_mean_structural >= v1_mean_structural
    )
    cost_ok = v2_pipeline_tokens <= ceiling
    return {
        "quality_ok": quality_ok,
        "cost_ok": cost_ok,
        "ceiling": ceiling,
        "ratio": (v2_pipeline_tokens / v1_pipeline_tokens) if v1_pipeline_tokens else None,
        "verdict": "PASS" if (quality_ok and cost_ok) else "FAIL",
    }


def load_run(directory: str | Path) -> dict:
    """Load `summary.json` plus every per-case record from one raw directory."""
    path = Path(directory)
    with open(path / "summary.json", encoding="utf-8") as handle:
        summary = json.load(handle)
    cases: dict[str, dict] = {}
    for case_id in summary.get("ran_cases", []):
        case_path = path / f"{case_id}.json"
        if case_path.exists():
            with open(case_path, encoding="utf-8") as handle:
                cases[case_id] = json.load(handle)
    return {"dir": str(path), "summary": summary, "cases": cases}


def _fmt(value, spec: str = "", dash: str = "—") -> str:
    if value is None:
        return dash
    if isinstance(value, bool):
        return "yes" if value else "**no**"
    if spec:
        return format(value, spec)
    return str(value)


def _tokens(record: dict, bucket: str = "pipeline") -> int:
    return record["usage"][bucket]["total_tokens"]


def _case_row(case_id: str, category: str, v1: dict | None, v2: dict | None) -> str:
    def cell(record, getter, spec="", dash="—"):
        return dash if record is None else _fmt(getter(record), spec, dash)

    return "| " + " | ".join([
        case_id,
        category or "—",
        cell(v1, lambda r: r["score"]["structural_score"], ".2f"),
        cell(v2, lambda r: r["score"]["structural_score"], ".2f"),
        cell(v1, lambda r: r["judge"].get("score")),
        cell(v2, lambda r: r["judge"].get("score")),
        cell(v1, lambda r: r["turns"]),
        cell(v2, lambda r: r["turns"]),
        cell(v1, lambda r: r["completed"]),
        cell(v2, lambda r: r["completed"]),
        cell(v1, lambda r: r["usage"]["pipeline"]["calls"]),
        cell(v2, lambda r: r["usage"]["pipeline"]["calls"]),
        cell(v1, lambda r: f"{r['usage']['pipeline']['input_tokens']:,}/{r['usage']['pipeline']['output_tokens']:,}"),
        cell(v2, lambda r: f"{r['usage']['pipeline']['input_tokens']:,}/{r['usage']['pipeline']['output_tokens']:,}"),
        cell(v1, lambda r: r["usage"]["pipeline"]["est_cost_usd"], ".4f"),
        cell(v2, lambda r: r["usage"]["pipeline"]["est_cost_usd"], ".4f"),
        cell(v1, lambda r: (r["error"] or {}).get("class"), dash="—") or "—",
        cell(v2, lambda r: (r["error"] or {}).get("class"), dash="—") or "—",
    ]) + " |"


#: Failure-bullet text → the family the report groups it under. Checked in order.
_FAILURE_FAMILIES = (
    ("run failed / no usable response", ("no result — the run failed",)),
    ("requirement enum wrong (duration / budget_hint)", ("requirement.duration", "requirement.budget_hint")),
    ("requirement description missed the case's keywords", ("requirement: none of",)),
    ("task count outside the expected range", ("task count",)),
    ("expected task missing or mis-typed / mis-routed", ("missing task matching",)),
    ("forbidden keyword leaked into a task", ("forbidden keyword",)),
    ("routing distribution outside the expected bounds", ("routing ",)),
)


def _family(bullet: str) -> str:
    for family, markers in _FAILURE_FAMILIES:
        if any(marker in bullet for marker in markers):
            return family
    return "other"


def failure_modes(run: dict, top: int = 3) -> list[str]:
    """The `top` most common scorer-observed failure families, with real quotes."""
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for case_id, record in run["cases"].items():
        seen: set[str] = set()
        for bullet in failure_bullets(record["score"], limit=6):
            family = _family(bullet)
            if family not in seen:
                counts[family] += 1
                seen.add(family)
            if len(examples[family]) < 2:
                examples[family].append(f"`{case_id}` — {bullet}")

    lines = []
    for family, count in counts.most_common(top):
        quotes = "; ".join(examples[family])
        lines.append(f"- **{family}** — {count}/{len(run['cases'])} cases. {quotes}")
    if not lines:
        lines.append("- No structural failures recorded in this run.")
    return lines


def crosscheck_rows(run: dict) -> list[str]:
    """Per-case: what the app billed vs what the proxy counted.

    The app's number comes from `TaskAnalysisAgent.usage_summary()` and covers
    the agent only. The proxy also sees `design_job`, which runs outside the
    agent, so `delta` is expected to be positive and to equal the `job_design`
    stage total. A negative or wildly mismatched delta means the accounting is
    wrong somewhere and the cost half of D13 cannot be trusted.
    """
    rows = []
    for case_id, record in sorted(run["cases"].items()):
        accounting = record.get("app_accounting") or {}
        app_in = accounting.get("reported_input_tokens")
        app_out = accounting.get("reported_output_tokens")
        app_total = None if app_in is None and app_out is None else (app_in or 0) + (app_out or 0)
        proxy_total = _tokens(record)
        jd = (record["usage"].get("by_stage") or {}).get("job_design") or {}
        jd_total = (jd.get("input_tokens", 0) + jd.get("output_tokens", 0)) if jd else 0
        delta = None if app_total is None else proxy_total - app_total
        agreed = "—" if delta is None else ("yes" if delta == jd_total else "**no**")
        rows.append(
            f"| {case_id} | {_fmt(app_total, ',') if app_total is not None else '—'} "
            f"| {proxy_total:,} | {_fmt(delta, ',') if delta is not None else '—'} "
            f"| {jd_total:,} ({jd.get('calls', 0)} calls) | {agreed} "
            f"| {_fmt(accounting.get('analysis_traces'))} |"
        )
    return rows


def build_report(v1: dict, v2: dict, commands: list[str]) -> str:
    a1, a2 = v1["summary"]["aggregate"], v2["summary"]["aggregate"]
    all_ids = sorted(set(v1["cases"]) | set(v2["cases"]))
    categories = {}
    for run in (v1, v2):
        for case_id, record in run["cases"].items():
            categories.setdefault(case_id, record.get("category"))

    # ── D13, computed, not asserted ──────────────────────────────────────────
    s1, s2 = a1["mean_structural"], a2["mean_structural"]
    t1, t2 = a1["pipeline_total_tokens"], a2["pipeline_total_tokens"]
    gate = d13_verdict(s1, s2, t1, t2)
    ceiling, quality_ok, cost_ok, verdict = (
        gate["ceiling"], gate["quality_ok"], gate["cost_ok"], gate["verdict"])

    lines: list[str] = []
    add = lines.append

    add(f"# Stage 1 baseline — v1 vs v2 on the {len(all_ids)}-case golden set")
    add("")
    add(f"Golden set `{v1['summary'].get('golden_set_version')}` "
        f"(`evals/golden/golden_set.json`, every case still "
        f"`review_status: draft-needs-human-review`). "
        f"Model `{v1['summary'].get('model')}` for both the pipeline and the judge. "
        f"Run {v1['summary'].get('started_at')} → {v2['summary'].get('finished_at')} UTC.")
    add("")
    if v1["summary"].get("aborted") or v2["summary"].get("aborted"):
        add("> **This report is partial.** At least one run stopped on its token budget. "
            "Cases listed under *Not run* below were never executed and are excluded from "
            "every mean. Nothing is extrapolated.")
        add("")
    for label, run in (("v1", v1), ("v2", v2)):
        if run["summary"].get("not_run"):
            add(f"- Not run ({label}): {', '.join(run['summary']['not_run'])}")

    # ── 1. per-case ──────────────────────────────────────────────────────────
    add("")
    add("## 1. Per-case results")
    add("")
    add("Structural score is the spec §3 mean of five components (see `evals/README.md`); "
        "judge score is 1–5 from the LLM judge and is never mixed into it. "
        "Tokens/USD are the **pipeline** only — judge tokens are harness overhead and are "
        "reported separately in §2.")
    add("")
    add("| case | category | struct v1 | struct v2 | judge v1 | judge v2 | turns v1 | turns v2 "
        "| done v1 | done v2 | calls v1 | calls v2 | in/out tok v1 | in/out tok v2 "
        "| est $ v1 | est $ v2 | err v1 | err v2 |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for case_id in all_ids:
        add(_case_row(case_id, categories.get(case_id), v1["cases"].get(case_id), v2["cases"].get(case_id)))

    # ── 2. aggregates ────────────────────────────────────────────────────────
    add("")
    add("## 2. Aggregates")
    add("")
    add("| metric | v1 | v2 |")
    add("|---|---|---|")
    rows = [
        ("cases scored", a1["cases"], a2["cases"]),
        ("mean structural score", _fmt(s1, ".4f"), _fmt(s2, ".4f")),
        ("mean judge score (1–5)", _fmt(a1["mean_judge"], ".3f"), _fmt(a2["mean_judge"], ".3f")),
        ("cases the judge could score", f"{a1['judged_cases']}/{a1['cases']}", f"{a2['judged_cases']}/{a2['cases']}"),
        ("mean turns", _fmt(a1["mean_turns"], ".2f"), _fmt(a2["mean_turns"], ".2f")),
        ("completion rate", f"{a1['completed']}/{a1['cases']} ({_fmt(a1['completion_rate'], '.0%')})",
         f"{a2['completed']}/{a2['cases']} ({_fmt(a2['completion_rate'], '.0%')})"),
        ("errored cases", a1["errors"], a2["errors"]),
        ("pipeline LLM calls",
         f"{sum(r['usage']['pipeline']['calls'] for r in v1['cases'].values()):,}",
         f"{sum(r['usage']['pipeline']['calls'] for r in v2['cases'].values()):,}"),
        ("pipeline input tokens", f"{a1['pipeline_input_tokens']:,}", f"{a2['pipeline_input_tokens']:,}"),
        ("pipeline output tokens", f"{a1['pipeline_output_tokens']:,}", f"{a2['pipeline_output_tokens']:,}"),
        ("**pipeline total tokens**", f"**{t1:,}**", f"**{t2:,}**"),
        ("judge tokens", f"{a1['judge_total_tokens']:,}", f"{a2['judge_total_tokens']:,}"),
        ("all-in tokens (pipeline + judge)", f"{a1['total_tokens']:,}", f"{a2['total_tokens']:,}"),
        ("pipeline est. cost (USD)", _fmt(a1["pipeline_est_cost_usd"], ".4f"), _fmt(a2["pipeline_est_cost_usd"], ".4f")),
        ("judge est. cost (USD)", _fmt(a1["judge_est_cost_usd"], ".4f"), _fmt(a2["judge_est_cost_usd"], ".4f")),
        ("wall time (s)", v1["summary"]["wall_time_s"], v2["summary"]["wall_time_s"]),
        ("retries (429/5xx)", len(v1["summary"].get("retry_events") or []),
         len(v2["summary"].get("retry_events") or [])),
    ]
    for name, left, right in rows:
        add(f"| {name} | {left} | {right} |")
    add("")
    add("**Cost caveat.** USD is an *estimate*: `app.agents.pricing` prices every call at a flat "
        "list rate (glm-4-plus at ¥0.05/1K, converted at ¥7.15/USD). Zhipu moved its flagship "
        "models to tiered pricing in 2026-08, so the real invoice will differ. **Tokens are the "
        "primary cost metric in this report**; treat the dollar column as an order of magnitude.")

    # ── 3. D13 ───────────────────────────────────────────────────────────────
    add("")
    add("## 3. D13 verdict")
    add("")
    add("D13: flip the default to v2 only if v2 is **≥ v1 on structural accuracy** and "
        f"**not worse than +20% on cost**. Both halves computed from §2, on pipeline tokens "
        "(the judge is harness overhead and does the same work for both versions):")
    add("")
    add(f"- quality: mean structural v2 `{_fmt(s2, '.4f')}` ≥ v1 `{_fmt(s1, '.4f')}` → "
        f"**{'PASS' if quality_ok else 'FAIL'}**"
        + ("" if s1 is None or s2 is None else f" (delta {s2 - s1:+.4f})"))
    add(f"- cost: v2 `{t2:,}` tokens ≤ 1.2 × v1 `{t1:,}` = `{ceiling:,.0f}` → "
        f"**{'PASS' if cost_ok else 'FAIL'}**"
        + (f" (v2 is {t2 / t1:.2f}× v1)" if t1 else ""))
    add("")
    add(f"### D13 = **{verdict}**")
    add("")
    add("WP5 acts on this line: PASS ⇒ flip `HIRENET_TASK_AGENT` default to v2; "
        "FAIL ⇒ v1 stays default and the retrospective says why.")

    # ── 4. cross-check ───────────────────────────────────────────────────────
    add("")
    add("## 4. Accounting cross-check (v2)")
    add("")
    add("`agent_runs.input_tokens/output_tokens` are written from "
        "`TaskAnalysisAgent.usage_summary()` (D8) and cover the **agent only**. The proxy also "
        "counts `design_job`, which runs outside the agent, so `delta` should equal the "
        "`job_design` stage total exactly. A case with no job design writes no `agent_runs` row "
        "with usage, and shows `—`.")
    add("")
    add("| case | app-reported tokens | proxy-counted tokens | delta | job_design stage | delta == job_design? | analysis_traces rows |")
    add("|---|---|---|---|---|---|---|")
    for row in crosscheck_rows(v2):
        add(row)
    add("")
    add("For reference, the same table for v1 would be all `—`: the v1 path passes no `usage` to "
        "the recorder, so those four `agent_runs` columns stay NULL — which is exactly the gap "
        "D8 exists to close.")

    # ── 5. failure modes ─────────────────────────────────────────────────────
    add("")
    add("## 5. Top failure modes")
    add("")
    add("Grouped from the structural scorer's own per-check output. These are observations, "
        "not diagnoses — each bullet quotes what the scorer saw.")
    add("")
    add("**v1**")
    add("")
    lines.extend(failure_modes(v1))
    add("")
    add("**v2**")
    add("")
    lines.extend(failure_modes(v2))

    # ── 6. judge caveat ──────────────────────────────────────────────────────
    add("")
    add("## 6. Judge caveat (D12)")
    add("")
    add(f"The judge is `{v1['summary'].get('model')}` — **the same model family that produced the "
        "answers it is grading**. That is a known and accepted Stage 1 shortcut, not a neutral "
        "evaluation: a model tends to like output that looks like its own, and it cannot catch a "
        "mistake it would also make. D12 accepts it only on the condition that **a human "
        "spot-checks at least 20% of the judge scores** (4 of 20 cases per version, chosen to "
        "include the lowest and the highest score). That spot-check has **not** been done yet, "
        "and no decision should rest on the judge column until it is. The structural column "
        "needs no such caveat — it is arithmetic over the golden set.")
    add("")
    add("The golden set itself is still `draft-needs-human-review` on all 20 cases "
        "(`evals/golden/golden_set.json`, review sheet in the orchestration workspace). "
        "Expectations that a reviewer later changes will change these numbers.")

    # ── 7. reproduction ──────────────────────────────────────────────────────
    add("")
    add("## 7. Exact commands and wall time")
    add("")
    add("```")
    for command in commands:
        add(command)
    add("```")
    add("")
    total_wall = (v1["summary"]["wall_time_s"] or 0) + (v2["summary"]["wall_time_s"] or 0)
    add(f"- v1 run: {v1['summary']['wall_time_s']}s ({v1['summary']['started_at']} → {v1['summary']['finished_at']})")
    add(f"- v2 run: {v2['summary']['wall_time_s']}s ({v2['summary']['started_at']} → {v2['summary']['finished_at']})")
    add(f"- **total eval wall time: {total_wall:.0f}s ({total_wall / 60:.1f} min)**")
    add(f"- token budget: {v1['summary']['budget_tokens']:,} per run; "
        f"exceeded: v1={v1['summary']['budget_exceeded']}, v2={v2['summary']['budget_exceeded']}")
    add(f"- raw per-case JSON: `{v1['dir']}/`, `{v2['dir']}/`")
    add("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.report",
        description="Build the v1-vs-v2 Markdown comparison from two raw eval directories.",
    )
    parser.add_argument("v1_dir", help="raw directory produced by --agent v1")
    parser.add_argument("v2_dir", help="raw directory produced by --agent v2")
    parser.add_argument("--out", required=True, help="path of the Markdown report to write")
    parser.add_argument("--command", action="append", default=None,
                        help="a command line to record in §7 (repeatable); defaults are inferred")
    args = parser.parse_args(argv)

    v1 = load_run(args.v1_dir)
    v2 = load_run(args.v2_dir)
    commands = args.command or [
        f".venv/bin/python -m evals.run_eval --agent v1 --cases all --out {args.v1_dir}",
        f".venv/bin/python -m evals.run_eval --agent v2 --cases all --out {args.v2_dir}",
        f".venv/bin/python -m evals.report {args.v1_dir} {args.v2_dir} --out {args.out}",
    ]

    markdown = build_report(v1, v2, commands)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    print(f"wrote {out_path} ({len(markdown):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
