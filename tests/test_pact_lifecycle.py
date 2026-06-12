"""
Task D: Cobo Pact lifecycle tests.

Covers:
- create → pending
- approve / reject from pending
- settle (approved → settled) triggers the U4 record_agent_run path
- bad state transitions return 400
- unknown pact_id returns 404
- settle's royalty side effect lands in royalty_ledger for the asset's creator

Uses the existing `client` fixture (fresh DB per test, Job Design asset
auto-bootstrapped into config["JOB_DESIGN_ASSET_ID"]).
"""
from app.storage.royalty_ledger import list_royalties_by_creator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create(client, **overrides):
    body = {
        "task_id": "task-001",
        "agent_name": "客服话术生成器",
        "creator_id": "creator-1",
        "amount": 60,
        "currency": "USD",
    }
    body.update(overrides)
    resp = client.post("/api/pact/create", json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _approve(client, pact_id):
    return client.post(f"/api/pact/approve/{pact_id}")


def _settle(client, pact_id):
    return client.post(f"/api/pact/settle/{pact_id}")


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestPactCreate:
    def test_returns_pending_with_pact_id(self, client):
        pact = _create(client)
        assert pact["status"] == "pending"
        assert pact["pact_id"].startswith("pact-")
        assert pact["task_id"] == "task-001"
        assert pact["agent_name"] == "客服话术生成器"
        assert pact["creator_id"] == "creator-1"
        assert pact["amount"] == 60
        assert pact["currency"] == "USD"
        assert pact["approved_at"] is None
        assert pact["created_at"]  # ISO timestamp present

    def test_default_currency_is_usd_when_omitted(self, client):
        # Omitting currency entirely should pick up "USD".
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10,
        })
        assert resp.status_code == 201, resp.get_json()
        assert resp.get_json()["currency"] == "USD"

    def test_default_currency_is_usd_when_explicit_null(self, client):
        # Passing currency=None explicitly must also resolve to "USD" — the
        # original `data.get("currency", "USD")` returned the stored None and
        # then exploded inside record_agent_run with a TypeError. The fix
        # collapses None / empty / whitespace back to "USD".
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10, "currency": None,
        })
        assert resp.status_code == 201, resp.get_json()
        assert resp.get_json()["currency"] == "USD"

    def test_each_pact_gets_unique_id(self, client):
        ids = {_create(client)["pact_id"] for _ in range(5)}
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestPactStatus:
    def test_returns_current_state(self, client):
        pact = _create(client)
        resp = client.get(f"/api/pact/status/{pact['pact_id']}")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "pending"

    def test_unknown_pact_404(self, client):
        resp = client.get("/api/pact/status/pact-deadbeef")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

class TestPactApprove:
    def test_pending_to_approved(self, client):
        pact = _create(client)
        resp = _approve(client, pact["pact_id"])
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "approved"
        assert body["approved_at"]  # ISO timestamp now set

    def test_reject_non_pending_400(self, client):
        pact = _create(client)
        _approve(client, pact["pact_id"])  # → approved
        resp = _approve(client, pact["pact_id"])  # double-approve
        assert resp.status_code == 400
        assert "approved" in resp.get_json()["error"]

    def test_unknown_pact_404(self, client):
        resp = _approve(client, "pact-nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------

class TestPactReject:
    def test_pending_to_rejected(self, client):
        pact = _create(client)
        resp = client.post(f"/api/pact/reject/{pact['pact_id']}")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "rejected"

    def test_cannot_reject_approved_pact_400(self, client):
        pact = _create(client)
        _approve(client, pact["pact_id"])
        resp = client.post(f"/api/pact/reject/{pact['pact_id']}")
        assert resp.status_code == 400

    def test_unknown_pact_404(self, client):
        resp = client.post("/api/pact/reject/pact-nope")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# settle: state transition + royalty side effect
# ---------------------------------------------------------------------------

class TestPactSettle:
    def test_full_create_approve_settle_flow(self, client):
        pact = _create(client, amount=60)
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["status"] == "settled"
        assert body["run_id"]  # uuid attached
        # 60 USD → 6000 basis pts. JOB_DESIGN asset split 70/30 → 4200 / 1800.
        s = body["royalty_splits"]
        assert s["creator"]["amount"] == 4200
        assert s["platform"]["amount"] == 1800
        # JOB_DESIGN asset has no tax field; tax bucket is 0.
        assert s["tax"]["amount"] == 0
        # Sum invariant holds.
        assert s["creator"]["amount"] + s["platform"]["amount"] + s["tax"]["amount"] == 6000

    def test_settle_writes_to_royalty_ledger(self, client):
        pact = _create(client, amount=60)
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        run_id = resp.get_json()["run_id"]

        # The creator bound to the JOB_DESIGN asset is PHASE1_CREATOR_ID, not
        # the pact's creator_id field (which is informational in Demo).
        creator_id = client.application.config["PHASE1_CREATOR_ID"]
        rows = list_royalties_by_creator(
            client.application.config["DATABASE_PATH"], creator_id,
        )
        matching = [r for r in rows if r["run_id"] == run_id]
        assert len(matching) == 1
        assert matching[0]["amount"] == 4200
        assert matching[0]["currency"] == "USD"
        assert matching[0]["status"] == "accrued"

    def test_settle_records_run_with_pact_task_id(self, client):
        pact = _create(client, task_id="pact-task-xyz", amount=10)
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        run_id = resp.get_json()["run_id"]

        # The run row should carry the pact's task_id, not a fabricated one.
        from app.storage.agent_runs import get_agent_run
        run = get_agent_run(client.application.config["DATABASE_PATH"], run_id)
        assert run["task_id"] == "pact-task-xyz"
        assert run["caller_id"] == client.application.config["PHASE1_CALLER_ID"]
        assert run["agent_name"] == pact["agent_name"]

    def test_cannot_settle_pending_pact_400(self, client):
        pact = _create(client)
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 400
        assert "approved" in resp.get_json()["error"]

    def test_cannot_settle_rejected_pact_400(self, client):
        pact = _create(client)
        client.post(f"/api/pact/reject/{pact['pact_id']}")
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 400

    def test_cannot_double_settle_400(self, client):
        pact = _create(client, amount=10)
        _approve(client, pact["pact_id"])
        first = _settle(client, pact["pact_id"])
        assert first.status_code == 200
        second = _settle(client, pact["pact_id"])
        assert second.status_code == 400

    def test_unknown_pact_404(self, client):
        resp = _settle(client, "pact-nope")
        assert resp.status_code == 404

    def test_currency_mismatch_fails_settlement(self, client):
        # JOB_DESIGN asset is USD; a CNY pact gets caught by the pre-flight
        # check and returns 400 (was 500 from record_agent_run before the fix).
        # The pact must stay in 'approved' so the caller can retry — the status
        # flip is gated behind the currency check.
        pact = _create(client, amount=10, currency="CNY")
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 400
        assert "currency" in resp.get_json()["error"].lower()
        # Status unchanged: still 'approved', not 'settled'.
        status_resp = client.get(f"/api/pact/status/{pact['pact_id']}")
        assert status_resp.get_json()["status"] == "approved"

    def test_settle_float_amount_uses_decimal_precision(self, client):
        # Regression: 0.29 * 100 in float arithmetic produces 28.999…, which
        # int() truncates to 28 — silently stealing a cent. Decimal conversion
        # must keep the full 29 cents so the 70/30 split adds back to 29.
        pact = _create(client, amount=0.29)
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 200, resp.get_json()
        s = resp.get_json()["royalty_splits"]
        assert s["creator"]["amount"] + s["platform"]["amount"] + s["tax"]["amount"] == 29

    def test_settle_string_amount_is_coerced_not_concatenated(self, client):
        # Regression: "60" * 100 in Python string multiplication produces a
        # 200-char repeating string. Decimal(str(...)) must parse it to 60.00
        # → 6000 cents, identical to the int-amount path.
        pact = _create(client, amount="60")
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 200, resp.get_json()
        s = resp.get_json()["royalty_splits"]
        assert s["creator"]["amount"] + s["platform"]["amount"] + s["tax"]["amount"] == 6000

    def test_settle_uses_round_half_up_not_bankers(self, client):
        # Regression (P0-4): Python's round() on Decimal uses banker's rounding
        # — Decimal('2.5') → 2, not 3. For amount=0.025 that meant we billed
        # 2 cents instead of 3, silently underbilling the creator on every
        # *.5-cent amount whose integer part is even. The fix uses
        # to_integral_value(ROUND_HALF_UP) so 2.5 → 3 cents as expected.
        pact = _create(client, amount=0.025)
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 200, resp.get_json()
        s = resp.get_json()["royalty_splits"]
        assert s["creator"]["amount"] + s["platform"]["amount"] + s["tax"]["amount"] == 3

    # Note: the legacy "settle rejects non-numeric amount" path is no longer
    # reachable because pact_create now rejects bad amounts up front
    # (see TestPactCreateValidation::test_create_rejects_non_numeric_amount).


# ---------------------------------------------------------------------------
# create-time validation (Bug 4): missing fields / bad amount / null currency
# ---------------------------------------------------------------------------

class TestPactCreateValidation:
    """pact_create must reject malformed bodies at the door so settle never
    sees a pact it can't bill. Each case here used to produce a 201 followed
    by a 500 at /pact/settle."""

    def test_missing_task_id_returns_400(self, client):
        resp = client.post("/api/pact/create", json={
            "agent_name": "a", "amount": 10,
        })
        assert resp.status_code == 400
        assert "task_id" in resp.get_json()["error"]

    def test_empty_task_id_returns_400(self, client):
        # whitespace-only must be rejected too
        resp = client.post("/api/pact/create", json={
            "task_id": "   ", "agent_name": "a", "amount": 10,
        })
        assert resp.status_code == 400

    def test_missing_agent_name_returns_400(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "amount": 10,
        })
        assert resp.status_code == 400
        assert "agent_name" in resp.get_json()["error"]

    def test_create_rejects_non_numeric_amount(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": "not-a-number",
        })
        assert resp.status_code == 400
        assert "amount" in resp.get_json()["error"]

    def test_create_rejects_negative_amount(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": -10,
        })
        assert resp.status_code == 400
        assert "amount" in resp.get_json()["error"]

    def test_create_rejects_zero_amount(self, client):
        # 0 dollars → 0 cents → all three split buckets are 0 → meaningless.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 0,
        })
        assert resp.status_code == 400

    def test_create_rejects_sub_cent_amount(self, client):
        # Regression: 0.001 passed `> 0` and `isfinite()` but settle's
        # Decimal('0.001') * 100 → Decimal('0.1') → int(round) = 0, so the
        # creator got billed zero. Reject sub-cent amounts at the door.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 0.001,
        })
        assert resp.status_code == 400
        assert "0.01" in resp.get_json()["error"]

    def test_create_rejects_amount_that_banker_rounds_to_zero(self, client):
        # 0.005 → Decimal('0.5') cents → int(round(0.5)) = 0 under banker's
        # rounding. Same zero-billing failure mode as 0.001 — must also reject.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 0.005,
        })
        assert resp.status_code == 400

    def test_create_accepts_one_cent_amount(self, client):
        # The boundary case: 0.01 → exactly 1 cent. Must pass.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 0.01,
        })
        assert resp.status_code == 201, resp.get_json()

    def test_create_rejects_boolean_amount(self, client):
        # True is technically `int(True) == 1`. Block it explicitly so a JSON
        # `true` can't sneak through as a 1-cent pact.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": True,
        })
        assert resp.status_code == 400

    def test_create_rejects_missing_amount(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a",
        })
        assert resp.status_code == 400

    def test_create_accepts_numeric_string_amount(self, client):
        # Numeric strings stay valid — settle's Decimal(str(...)) handles them.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": "60",
        })
        assert resp.status_code == 201

    def test_non_dict_array_body_400_not_500(self, client):
        # Regression: a JSON array body used to trip .get() with AttributeError → 500.
        resp = client.post(
            "/api/pact/create",
            data="[1]",
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "JSON object" in resp.get_json()["error"]

    def test_non_dict_string_body_400_not_500(self, client):
        # Regression: a JSON string body used to trip .get() with AttributeError → 500.
        resp = client.post(
            "/api/pact/create",
            data='"x"',
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "JSON object" in resp.get_json()["error"]

    def test_create_rejects_infinity_amount(self, client):
        # Regression: float("Infinity") passed the `<= 0` check and was stored,
        # then OverflowError'd at settle (Decimal(Infinity) is undefined).
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": "Infinity",
        })
        assert resp.status_code == 400
        assert "finite" in resp.get_json()["error"]

    def test_create_rejects_negative_infinity_amount(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": "-Infinity",
        })
        assert resp.status_code == 400

    def test_create_rejects_nan_amount(self, client):
        # Regression: NaN comparisons return False, so NaN <= 0 didn't trip the
        # positivity check. Must be rejected at the `isfinite` gate instead.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": "NaN",
        })
        assert resp.status_code == 400
        assert "finite" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
# asset_id binding (Bug 3): pact-level override of the billed asset
# ---------------------------------------------------------------------------

class TestPactAssetId:
    """A pact can be bound to any registered SkillAsset. Settle then bills
    that asset's creator instead of falling back to the Phase 1 Job Design
    creator — which is what makes the Cobo lifecycle reusable beyond the
    one bootstrapped asset."""

    def test_pact_create_persists_asset_id(self, client):
        # Use the bootstrapped Job Design asset id — guaranteed to exist.
        asset_id = client.application.config["JOB_DESIGN_ASSET_ID"]
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10,
            "asset_id": asset_id,
        })
        assert resp.status_code == 201, resp.get_json()
        assert resp.get_json()["asset_id"] == asset_id

    def test_pact_create_rejects_unknown_asset_id(self, client):
        # An asset_id that isn't in skill_assets must 400 at create — not at
        # settle, where record_agent_run would raise and we'd 500.
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10,
            "asset_id": "asset-does-not-exist",
        })
        assert resp.status_code == 400
        assert "asset_id" in resp.get_json()["error"]

    def test_pact_create_rejects_non_string_asset_id(self, client):
        resp = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "a", "amount": 10,
            "asset_id": 12345,
        })
        assert resp.status_code == 400

    def test_pact_without_asset_id_falls_back_to_job_design(self, client):
        # Backwards-compat: omitting asset_id must still bill the Phase 1
        # Job Design asset, so existing demo flows keep working.
        pact = _create(client, amount=60)
        assert pact.get("asset_id") is None
        _approve(client, pact["pact_id"])
        resp = _settle(client, pact["pact_id"])
        assert resp.status_code == 200
        # 60 USD → 6000 cents, 70/30 split → 4200/1800. JOB_DESIGN has no tax.
        s = resp.get_json()["royalty_splits"]
        assert s["creator"]["amount"] == 4200
        assert s["platform"]["amount"] == 1800

    def test_settle_with_bound_asset_id_routes_royalty_to_that_creator(self, client):
        # Register a fresh asset under a distinct creator. Settling a pact
        # bound to it must write the royalty row to *that* creator, not the
        # PHASE1 stub.
        from app.storage.skill_assets import insert_skill_asset
        from app.storage.royalty_ledger import list_royalties_by_creator
        db_path = client.application.config["DATABASE_PATH"]
        asset_id = insert_skill_asset(db_path, {
            "creator_id": "creator-alpha",
            "name": "Alpha Agent",
            "description": "test",
            "type": "agent",
            "endpoint_url": None,
            "io_schema": {"input": {}, "output": {}},
            "price_amount": 100,
            "price_currency": "USD",
            "price_chain": None,
            "split_rule": {"creator": 7000, "platform": 3000},
            "content_hash": "deadbeef" * 8,
        })
        resp_create = client.post("/api/pact/create", json={
            "task_id": "t", "agent_name": "Alpha Agent", "amount": 50,
            "asset_id": asset_id,
        })
        assert resp_create.status_code == 201, resp_create.get_json()
        pact_id = resp_create.get_json()["pact_id"]
        _approve(client, pact_id)
        resp_settle = _settle(client, pact_id)
        assert resp_settle.status_code == 200, resp_settle.get_json()
        run_id = resp_settle.get_json()["run_id"]

        # Royalty must land on creator-alpha, NOT on PHASE1_CREATOR_ID.
        alpha_rows = list_royalties_by_creator(db_path, "creator-alpha")
        assert any(r["run_id"] == run_id for r in alpha_rows)
        phase1_rows = list_royalties_by_creator(
            db_path, client.application.config["PHASE1_CREATOR_ID"]
        )
        assert not any(r["run_id"] == run_id for r in phase1_rows)


# ---------------------------------------------------------------------------
# concurrency (Bug 1): only one of N parallel settles may succeed
# ---------------------------------------------------------------------------

class TestPactSettleConcurrency:
    """Two threads racing to settle the same pact must end with exactly one
    royalty_ledger row, not two — otherwise the creator gets double-paid."""

    def test_concurrent_settle_records_exactly_one_run(self, client):
        from app.storage.royalty_ledger import list_royalties_by_creator
        import threading

        pact = _create(client, amount=60)
        _approve(client, pact["pact_id"])
        pact_id = pact["pact_id"]
        app = client.application
        db_path = app.config["DATABASE_PATH"]
        creator_id = app.config["PHASE1_CREATOR_ID"]

        # Each thread uses its own test_client because the werkzeug test
        # client isn't documented as thread-safe; the app object itself is.
        N = 5
        barrier = threading.Barrier(N)
        results: list[tuple[int, dict]] = []
        results_lock = threading.Lock()

        def do_settle():
            c = app.test_client()
            barrier.wait()  # release all threads simultaneously
            r = c.post(f"/api/pact/settle/{pact_id}")
            with results_lock:
                results.append((r.status_code, r.get_json()))

        threads = [threading.Thread(target=do_settle) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [body for code, body in results if code == 200]
        rejections = [body for code, body in results if code == 400]
        assert len(successes) == 1, f"expected exactly one 200, got {len(successes)} ({results})"
        assert len(rejections) == N - 1, (
            f"expected {N-1} 400s for already-settled pact, got {len(rejections)} ({results})"
        )

        # And the ledger backs that up: exactly one row for this run.
        run_id = successes[0]["run_id"]
        rows = list_royalties_by_creator(db_path, creator_id)
        assert sum(1 for r in rows if r["run_id"] == run_id) == 1
