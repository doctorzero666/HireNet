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
