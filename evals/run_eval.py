"""Run one agent version over the golden set against the REAL Zhipu API.

    .venv/bin/python -m evals.run_eval --agent v2 --cases all \
        --out evals/reports/raw/2026-09-04-v2

This is the one place in Stage 1 that is *meant* to make live LLM calls. The
pytest suite must never reach the network — `tests/test_evals_scoring.py`
covers the scorer and the judge with canned data, and nothing in `tests/`
imports this module.

What one case does, in order:

  1. fresh Flask app on a fresh temp SQLite DB (same construction as
     `tests/conftest.py`, including the injected MockSettlementProvider so the
     run never dials a chain node);
  2. `POST /api/analyze/start` with the case's `initial_message`;
  3. `POST /api/analyze/reply` with `SimulatedEmployer` answers until
     `is_complete`, or until the employer's hard turn cap — a run that hits the
     cap is recorded `completed=False` and still goes on to step 4, because
     "what does /decide do with an incomplete requirement" is itself a finding;
  4. `POST /api/analyze/decide`;
  5. structural score, optional judge score, and every number the proxy saw.

Anything that raises, and any non-200, is recorded as `error` with structural
score 0 and the run continues to the next case (WP4). The only thing that stops
a run early is the token budget.

Cases run sequentially. Concurrency would cut wall time and cost nothing extra,
but `app.app.analysis_sessions` is a module-level dict and the env flag is
process-global, so a parallel runner would need real isolation to stay honest.
Reproducibility is worth more here than speed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# `.env` carries ZHIPU_API_KEY / ZHIPU_BASE_URL / ZHIPU_MODEL. `create_app()`
# loads it too, but the proxy has to build a real client BEFORE the app exists,
# so the harness loads it itself first. Never printed, never written to a report.
load_dotenv()

import app.agents.agents as agents_module  # noqa: E402
from app.agents.pricing import estimate_cost_usd  # noqa: E402
from app.app import create_app  # noqa: E402
from app.services.mock_settlement import MockSettlementProvider  # noqa: E402
from app.storage.agent_runs import list_agent_runs_by_caller  # noqa: E402
from app.storage.analysis_traces import list_traces  # noqa: E402
from evals.judge import judge_case  # noqa: E402
from evals.llm_proxy import DEFAULT_BUDGET_TOKENS, BudgetExceeded, CountingLLMProxy  # noqa: E402
from evals.scoring import (  # noqa: E402
    decision_counts,
    load_golden_set,
    score_case,
    select_cases,
)
from evals.simulated_employer import DEFAULT_MAX_TURNS, SimulatedEmployer  # noqa: E402

TASK_AGENT_ENV = "HIRENET_TASK_AGENT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cost_usd(records: list[dict]) -> float | None:
    """Estimated USD for a list of proxy call records.

    `None` when nothing could be priced (unknown model). Zhipu moved its
    flagship models to tiered pricing in 2026-08, so this is an order-of-
    magnitude estimate against a flat list price, not an invoice — the report
    repeats that caveat, and tokens stay the primary metric.
    """
    total = 0.0
    priced = 0
    for record in records:
        cost = estimate_cost_usd(record.get("model"), record.get("input_tokens"), record.get("output_tokens"))
        if cost is not None:
            total += cost
            priced += 1
    return round(total, 6) if priced else None


def _make_app(db_path: str):
    return create_app(config={
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "SETTLEMENT_PROVIDER": MockSettlementProvider(),
    })


def _app_accounting(db_path: str, session_id: str | None) -> dict:
    """v2 cross-check material: what the APP thinks the run cost.

    `agent_runs.input_tokens/output_tokens/time_ms` are written from
    `TaskAnalysisAgent.usage_summary()` (D8 via `asset_bootstrap._usage_columns`)
    and are the SESSION total repeated on every row, so they are read, never
    summed. On the v1 path they are NULL by design, and on any path they are
    absent entirely when the run produced no job design to bill.
    """
    out: dict = {
        "agent_runs": [],
        "reported_input_tokens": None,
        "reported_output_tokens": None,
        "reported_time_ms": None,
        "reported_cost_usd": None,
        "analysis_traces": None,
    }
    try:
        runs = list_agent_runs_by_caller(db_path, "phase1_stub_employer")
    except Exception as exc:
        out["agent_runs_error"] = f"{type(exc).__name__}: {exc}"
        runs = []
    out["agent_runs"] = [
        {
            "agent_name": r.get("agent_name"),
            "task_id": r.get("task_id"),
            "input_tokens": r.get("input_tokens"),
            "output_tokens": r.get("output_tokens"),
            "time_ms": r.get("time_ms"),
            "llm_cost_usd": r.get("llm_cost_usd"),
        }
        for r in runs
    ]
    for row in out["agent_runs"]:
        if row["input_tokens"] is not None or row["output_tokens"] is not None:
            out["reported_input_tokens"] = row["input_tokens"]
            out["reported_output_tokens"] = row["output_tokens"]
            out["reported_time_ms"] = row["time_ms"]
            out["reported_cost_usd"] = row["llm_cost_usd"]
            break
    if session_id:
        try:
            out["analysis_traces"] = len(list_traces(db_path, session_id))
        except Exception as exc:
            out["analysis_traces_error"] = f"{type(exc).__name__}: {exc}"
    return out


def run_case(
    case: dict,
    proxy: CountingLLMProxy,
    agent_version: str,
    max_turns: int = DEFAULT_MAX_TURNS,
    judge: bool = True,
    judge_model: str | None = None,
) -> dict:
    """Drive one golden case end to end and return its raw record."""
    import app.app as app_module

    case_id = case["id"]
    proxy.set_context(case_id, "pipeline")
    started = time.perf_counter()

    record: dict = {
        "case_id": case_id,
        "category": case.get("category"),
        "agent": agent_version,
        "started_at": _now_iso(),
        "session_id": None,
        "http": {"start": None, "reply": [], "decide": None},
        "turns": 0,
        "completed": False,
        "hit_turn_cap": False,
        "transcript": [],
        "response": None,
        "error": None,
    }

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    result: dict | None = None
    try:
        flask_app = _make_app(db_path)
        # `analysis_sessions` is a module-level dict shared by every app object
        # in this process; clearing it keeps one case's sessions out of the next.
        app_module.analysis_sessions.clear()

        with flask_app.test_client() as client:
            employer = SimulatedEmployer(case["input"].get("clarifications"), max_turns=max_turns)
            initial = case["input"]["initial_message"]
            record["transcript"].append({"role": "employer", "text": initial})

            resp = client.post("/api/analyze/start", json={"message": initial})
            record["http"]["start"] = resp.status_code
            body = resp.get_json() or {}
            record["session_id"] = body.get("session_id")
            record["transcript"].append({"role": "pipeline", "text": body.get("response")})
            if resp.status_code != 200:
                raise RuntimeError(f"/api/analyze/start returned {resp.status_code}: {body}")

            is_complete = bool(body.get("is_complete"))
            record["turn_count_reported"] = body.get("turn_count")

            while not is_complete and employer.has_turns_left:
                message = employer.next_reply()
                record["transcript"].append({"role": "employer", "text": message})
                resp = client.post(
                    "/api/analyze/reply",
                    json={"session_id": record["session_id"], "message": message},
                )
                record["http"]["reply"].append(resp.status_code)
                body = resp.get_json() or {}
                record["transcript"].append({"role": "pipeline", "text": body.get("response")})
                if resp.status_code != 200:
                    raise RuntimeError(f"/api/analyze/reply returned {resp.status_code}: {body}")
                is_complete = bool(body.get("is_complete"))
                record["turn_count_reported"] = body.get("turn_count", record.get("turn_count_reported"))

            record["turns"] = employer.turns_used
            record["completed"] = is_complete
            record["hit_turn_cap"] = employer.hit_cap and not is_complete
            record["requirement_after_clarify"] = body.get("requirement")

            resp = client.post("/api/analyze/decide", json={"session_id": record["session_id"]})
            record["http"]["decide"] = resp.status_code
            decide_body = resp.get_json() or {}
            if resp.status_code == 200:
                result = decide_body
                record["response"] = decide_body
            else:
                record["response"] = decide_body
                raise RuntimeError(f"/api/analyze/decide returned {resp.status_code}: {decide_body}")

        record["app_accounting"] = _app_accounting(db_path, record["session_id"])

    except BudgetExceeded as exc:
        record["error"] = {"class": "BudgetExceeded", "message": str(exc), "aborted_run": True}
    except Exception as exc:
        record["error"] = {
            "class": type(exc).__name__,
            "message": str(exc)[:2000],
            "traceback": traceback.format_exc()[-2000:],
        }
        if "app_accounting" not in record:
            record["app_accounting"] = _app_accounting(db_path, record["session_id"])
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass

    # ── scoring ──────────────────────────────────────────────────────────────
    record["score"] = score_case(case, result)
    record["decision_counts"] = decision_counts((result or {}).get("decisions"))

    if judge and not proxy.budget_exceeded:
        proxy.set_context(case_id, "judge")
        record["judge"] = judge_case(
            case, result, proxy, judge_model or agents_module.get_model()
        )
        proxy.set_context(case_id, "pipeline")
    else:
        record["judge"] = {
            "score": None, "rationale": None, "repaired": False,
            "error": "judging disabled" if not judge else "token budget exhausted",
            "raw": None,
        }

    pipeline_records = proxy.records_for(case_id, "pipeline")
    judge_records = proxy.records_for(case_id, "judge")
    record["llm_calls"] = pipeline_records + judge_records
    record["usage"] = {
        "pipeline": {**proxy.totals(pipeline_records), "est_cost_usd": _cost_usd(pipeline_records)},
        "judge": {**proxy.totals(judge_records), "est_cost_usd": _cost_usd(judge_records)},
        "by_stage": _by_stage(pipeline_records),
    }
    record["wall_time_s"] = round(time.perf_counter() - started, 2)
    return record


def _by_stage(records: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in records:
        bucket = out.setdefault(r["stage"], {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        bucket["calls"] += 1
        bucket["input_tokens"] += r["input_tokens"] or 0
        bucket["output_tokens"] += r["output_tokens"] or 0
    return out


def _aggregate(records: list[dict]) -> dict:
    """Run-level aggregates. Judge means exclude unscored cases, never zero them."""
    structural = [r["score"]["structural_score"] for r in records]
    judged = [r["judge"]["score"] for r in records if r["judge"].get("score") is not None]
    pipeline_tokens = sum(r["usage"]["pipeline"]["total_tokens"] for r in records)
    judge_tokens = sum(r["usage"]["judge"]["total_tokens"] for r in records)
    pipeline_costs = [r["usage"]["pipeline"]["est_cost_usd"] for r in records
                      if r["usage"]["pipeline"]["est_cost_usd"] is not None]
    judge_costs = [r["usage"]["judge"]["est_cost_usd"] for r in records
                   if r["usage"]["judge"]["est_cost_usd"] is not None]
    return {
        "cases": len(records),
        "mean_structural": round(sum(structural) / len(structural), 4) if structural else None,
        "mean_judge": round(sum(judged) / len(judged), 3) if judged else None,
        "judged_cases": len(judged),
        "mean_turns": round(sum(r["turns"] for r in records) / len(records), 2) if records else None,
        "completed": sum(1 for r in records if r["completed"]),
        "completion_rate": round(sum(1 for r in records if r["completed"]) / len(records), 3) if records else None,
        "errors": sum(1 for r in records if r["error"]),
        "total_llm_calls": sum(r["usage"]["pipeline"]["calls"] + r["usage"]["judge"]["calls"] for r in records),
        "pipeline_input_tokens": sum(r["usage"]["pipeline"]["input_tokens"] for r in records),
        "pipeline_output_tokens": sum(r["usage"]["pipeline"]["output_tokens"] for r in records),
        "pipeline_total_tokens": pipeline_tokens,
        "judge_total_tokens": judge_tokens,
        "total_tokens": pipeline_tokens + judge_tokens,
        "pipeline_est_cost_usd": round(sum(pipeline_costs), 6) if pipeline_costs else None,
        "judge_est_cost_usd": round(sum(judge_costs), 6) if judge_costs else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run_eval",
        description="Run the golden set against one analysis-pipeline version (real LLM calls).",
    )
    parser.add_argument("--agent", choices=["v1", "v2"], required=True,
                        help="which pipeline to exercise; sets HIRENET_TASK_AGENT for the run")
    parser.add_argument("--cases", default="all",
                        help="'all' or a comma-separated id list, e.g. g01,g02")
    parser.add_argument("--out", required=True, help="directory for the raw per-case JSON + summary.json")
    parser.add_argument("--judge", dest="judge", action="store_true", default=True,
                        help="run the LLM judge (default)")
    parser.add_argument("--no-judge", dest="judge", action="store_false",
                        help="skip the LLM judge (cheaper; judge columns come out empty)")
    parser.add_argument("--budget-tokens", type=int, default=DEFAULT_BUDGET_TOKENS,
                        help=f"run-wide token cap across pipeline + judge (default {DEFAULT_BUDGET_TOKENS})")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        help=f"hard cap on employer replies per case (default {DEFAULT_MAX_TURNS})")
    parser.add_argument("--golden", default=None, help="path to a golden set other than the committed one")
    args = parser.parse_args(argv)

    if not os.getenv("ZHIPU_API_KEY"):
        print("ZHIPU_API_KEY is not set (checked .env and the environment); refusing to run.",
              file=sys.stderr)
        return 2

    golden = load_golden_set(args.golden)
    cases = select_cases(golden, args.cases)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    os.environ[TASK_AGENT_ENV] = args.agent
    model = agents_module.get_model()

    real_get_client = agents_module.get_llm_client
    proxy = CountingLLMProxy(real_get_client(), budget_tokens=args.budget_tokens)
    agents_module.get_llm_client = lambda: proxy

    started_at = _now_iso()
    run_start = time.perf_counter()
    records: list[dict] = []
    aborted = False

    print(f"[eval] agent={args.agent} model={model} cases={len(cases)} "
          f"judge={'on' if args.judge else 'off'} budget={args.budget_tokens:,} tokens", flush=True)
    try:
        for index, case in enumerate(cases, start=1):
            print(f"[eval] {index}/{len(cases)} {case['id']} ({case.get('category')}) …",
                  end=" ", flush=True)
            record = run_case(
                case, proxy, args.agent,
                max_turns=args.max_turns, judge=args.judge,
            )
            records.append(record)
            with open(out_dir / f"{case['id']}.json", "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)

            judge_score = record["judge"].get("score")
            print(
                f"structural={record['score']['structural_score']:.2f} "
                f"judge={judge_score if judge_score is not None else '—'} "
                f"turns={record['turns']} complete={record['completed']} "
                f"tokens={record['usage']['pipeline']['total_tokens'] + record['usage']['judge']['total_tokens']:,} "
                f"{record['wall_time_s']}s"
                + (f" ERROR={record['error']['class']}" if record["error"] else ""),
                flush=True,
            )

            if proxy.budget_exceeded:
                aborted = True
                print(f"[eval] token budget {args.budget_tokens:,} exhausted after {case['id']}; "
                      f"stopping. {len(cases) - index} case(s) NOT run.", file=sys.stderr, flush=True)
                break
    finally:
        agents_module.get_llm_client = real_get_client

    summary = {
        "agent": args.agent,
        "model": model,
        "golden_set_version": golden.get("version"),
        "requested_cases": [c["id"] for c in cases],
        "ran_cases": [r["case_id"] for r in records],
        "not_run": [c["id"] for c in cases if c["id"] not in {r["case_id"] for r in records}],
        "judge_enabled": args.judge,
        "budget_tokens": args.budget_tokens,
        "budget_exceeded": proxy.budget_exceeded,
        "aborted": aborted,
        "max_turns": args.max_turns,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "wall_time_s": round(time.perf_counter() - run_start, 2),
        "retry_events": proxy.retry_events,
        "aggregate": _aggregate(records),
        "cases": [
            {
                "case_id": r["case_id"],
                "category": r["category"],
                "structural_score": r["score"]["structural_score"],
                "judge_score": r["judge"].get("score"),
                "turns": r["turns"],
                "completed": r["completed"],
                "error": (r["error"] or {}).get("class"),
            }
            for r in records
        ],
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)

    agg = summary["aggregate"]
    print(f"[eval] done in {summary['wall_time_s']}s — mean structural "
          f"{agg['mean_structural']}, mean judge {agg['mean_judge']}, "
          f"{agg['total_tokens']:,} tokens, {agg['errors']} error(s). "
          f"Raw output in {out_dir}", flush=True)
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
