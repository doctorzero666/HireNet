def test_index(client):
    assert client.get('/').status_code == 200


def test_index_has_creator_earnings_link(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'<div id="root">' in resp.data or b'<!DOCTYPE html>' in resp.data


def test_employer(client):
    assert client.get('/employer').status_code == 200


def test_jobseeker(client):
    assert client.get('/jobseeker').status_code == 200


def test_agents(client):
    assert client.get('/agents').status_code == 200


def test_health(client):
    assert client.get('/api/health').status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# Suite hygiene: a test run must not read the operator's `.env`
#
# `create_app()` calls `load_dotenv()`, which happens AFTER a test's fixtures
# have arranged the environment — so without the `no_dotenv` fixture in
# conftest.py a machine-local secret silently overrides what the test set up.
# These two tests pin that fixture down; deleting it makes them fail.
# ──────────────────────────────────────────────────────────────────────────────

def test_the_suite_never_loads_a_dotenv_file(tmp_path):
    import os

    import dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("HIRENET_DOTENV_CANARY=leaked\n")
    dotenv.load_dotenv(str(env_file), override=True)
    assert os.getenv("HIRENET_DOTENV_CANARY") is None


def test_create_apps_own_load_dotenv_is_neutered(tmp_path):
    """The name `create_app` actually calls, bound at import time in app.app."""
    import os

    import app.app as app_module

    env_file = tmp_path / ".env"
    env_file.write_text("HIRENET_DOTENV_CANARY=leaked\n")
    app_module.load_dotenv(str(env_file), override=True)
    assert os.getenv("HIRENET_DOTENV_CANARY") is None
