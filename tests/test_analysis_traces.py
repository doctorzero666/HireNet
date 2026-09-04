"""
Stage 1 / WP3b — `analysis_traces` DAO + `scripts/replay_trace.py`.

The table is the only durable record of what the v2 pipeline actually said to
the model and got back. These tests pin three things: a record round-trips
unchanged, a record that violates `analysis_trace.json` never reaches the
table, and the replay CLI prints the run in step order (and fails loudly on an
unknown session instead of printing nothing).
"""
import json
import os
import subprocess
import sys
import tempfile

import jsonschema
import pytest

from app.storage.analysis_traces import build_trace, insert_trace, list_traces
from app.storage.db import _open, _create_tables

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import replay_trace  # noqa: E402


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    with _open(path) as conn:
        _create_tables(conn)
    yield path
    os.unlink(path)


def make_record(
    session_id="sess1",
    step_no=0,
    stage="clarify",
    messages=({"role": "user", "content": "搭建智能客服系统"},),
    **overrides,
) -> dict:
    record = build_trace(
        trace_id=f"{session_id}-{step_no}",
        session_id=session_id,
        step_no=step_no,
        stage=stage,
        model="glm-4-plus",
        messages=list(messages),
        response_text="请问是一次性交付还是长期运营？",
        parsed_ok=True,
        input_tokens=11,
        output_tokens=22,
        time_ms=345,
    )
    record.update(overrides)
    return record


class TestInsertAndList:
    def test_round_trip_preserves_every_column(self, db_path):
        record = make_record()
        trace_id = insert_trace(db_path, record)
        assert trace_id == record["trace_id"]

        rows = list_traces(db_path, "sess1")
        assert len(rows) == 1
        assert rows[0] == record

    def test_parsed_ok_comes_back_as_a_bool_not_an_int(self, db_path):
        insert_trace(db_path, make_record(parsed_ok=False))
        row = list_traces(db_path, "sess1")[0]
        assert row["parsed_ok"] is False

    def test_null_usage_stays_null(self, db_path):
        """`0` and "the provider told us nothing" are different facts."""
        insert_trace(
            db_path,
            make_record(input_tokens=None, output_tokens=None, time_ms=None),
        )
        row = list_traces(db_path, "sess1")[0]
        assert row["input_tokens"] is None
        assert row["output_tokens"] is None
        assert row["time_ms"] is None

    def test_rows_come_back_ordered_by_step_no_not_insertion_order(self, db_path):
        for step_no in (2, 0, 3, 1):
            insert_trace(db_path, make_record(step_no=step_no))
        rows = list_traces(db_path, "sess1")
        assert [r["step_no"] for r in rows] == [0, 1, 2, 3]

    def test_sessions_do_not_bleed_into_each_other(self, db_path):
        insert_trace(db_path, make_record(session_id="sess1"))
        insert_trace(db_path, make_record(session_id="sess2"))
        assert [r["session_id"] for r in list_traces(db_path, "sess2")] == ["sess2"]

    def test_unknown_session_is_an_empty_list(self, db_path):
        assert list_traces(db_path, "nope") == []

    def test_build_trace_serialises_the_messages_array(self):
        record = make_record()
        assert json.loads(record["prompt_json"]) == [
            {"role": "user", "content": "搭建智能客服系统"}
        ]
        # Chinese survives as Chinese, not as \uXXXX escapes.
        assert "搭建智能客服系统" in record["prompt_json"]

    def test_created_at_is_an_iso_timestamp(self):
        assert make_record()["created_at"].startswith("20")


class TestValidationRejection:
    """A malformed record must fail at the call site, never land in the table."""

    def test_unknown_stage_is_rejected(self, db_path):
        with pytest.raises(jsonschema.ValidationError):
            insert_trace(db_path, make_record(stage="brainstorm"))
        assert list_traces(db_path, "sess1") == []

    def test_negative_step_no_is_rejected(self, db_path):
        with pytest.raises(jsonschema.ValidationError):
            insert_trace(db_path, make_record(step_no=-1))
        assert list_traces(db_path, "sess1") == []

    def test_missing_required_field_is_rejected(self, db_path):
        record = make_record()
        del record["model"]
        with pytest.raises(jsonschema.ValidationError):
            insert_trace(db_path, record)
        assert list_traces(db_path, "sess1") == []

    def test_extra_field_is_rejected(self, db_path):
        """`additionalProperties: false` — a typo'd column name is a bug."""
        with pytest.raises(jsonschema.ValidationError):
            insert_trace(db_path, make_record(cost_usd=0.001))
        assert list_traces(db_path, "sess1") == []

    def test_non_boolean_parsed_ok_is_rejected(self, db_path):
        with pytest.raises(jsonschema.ValidationError):
            insert_trace(db_path, make_record(parsed_ok="yes"))
        assert list_traces(db_path, "sess1") == []


class TestReplayCLI:
    def _seed(self, db_path):
        insert_trace(db_path, make_record(step_no=0, stage="clarify"))
        insert_trace(
            db_path,
            make_record(
                step_no=1,
                stage="decompose",
                response_text="x" * 500,
                parsed_ok=False,
            ),
        )
        insert_trace(
            db_path,
            make_record(step_no=2, stage="decide", model="policy", messages=[]),
        )

    def test_prints_every_step_in_order(self, db_path, capsys):
        self._seed(db_path)
        assert replay_trace.main(["sess1", "--db", db_path]) == 0
        out = capsys.readouterr().out
        assert "session sess1 — 3 step(s)" in out
        assert out.index("[0] clarify") < out.index("[1] decompose") < out.index("[2] decide")
        assert "model=glm-4-plus" in out
        assert "model=policy" in out
        assert "parsed_ok=False" in out
        assert "in=11 out=22" in out
        assert "time_ms=345" in out

    def test_truncates_long_text_by_default(self, db_path, capsys):
        self._seed(db_path)
        replay_trace.main(["sess1", "--db", db_path])
        out = capsys.readouterr().out
        assert "use --full" in out
        assert "x" * 500 not in out

    def test_full_flag_prints_everything(self, db_path, capsys):
        self._seed(db_path)
        replay_trace.main(["sess1", "--db", db_path, "--full"])
        out = capsys.readouterr().out
        assert "x" * 500 in out
        assert "use --full" not in out

    def test_unknown_session_exits_1_with_a_message(self, db_path, capsys):
        self._seed(db_path)
        assert replay_trace.main(["ghost", "--db", db_path]) == 1
        err = capsys.readouterr().err
        assert "no traces for session 'ghost'" in err

    def test_missing_database_exits_1(self, capsys):
        assert replay_trace.main(["sess1", "--db", "/nonexistent/hirenet.db"]) == 1
        assert "database not found" in capsys.readouterr().err

    def test_runs_as_a_subprocess(self, db_path):
        """It is a CLI: it has to work from the shell, not just as an import."""
        self._seed(db_path)
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "replay_trace.py"),
             "sess1", "--db", db_path],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "[0] clarify" in proc.stdout
        assert "[2] decide" in proc.stdout

    def test_subprocess_exit_code_1_on_unknown_session(self, db_path):
        self._seed(db_path)
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "replay_trace.py"),
             "ghost", "--db", db_path],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 1
        assert "no traces" in proc.stderr


class TestTableIsCreatedByInitDb:
    def test_create_app_creates_the_table(self):
        """The table must exist after normal boot, not only in this test file."""
        from app.app import create_app

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            create_app(config={"TESTING": True, "DATABASE_PATH": path})
            with _open(path) as conn:
                names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            assert "analysis_traces" in names
        finally:
            os.unlink(path)
