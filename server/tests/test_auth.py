def test_healthz_no_auth_required(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_submit_requires_client_token(client):
    r = client.post("/jobs", json={"url": "https://x"})
    assert r.status_code == 401


def test_submit_with_wrong_token(client):
    r = client.post(
        "/jobs",
        json={"url": "https://x"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


def test_submit_with_worker_token_rejected_on_client_endpoint(client, worker_headers):
    r = client.post("/jobs", json={"url": "https://x"}, headers=worker_headers)
    assert r.status_code == 401


def test_next_with_client_token_rejected(client, client_headers):
    r = client.get("/jobs/next", headers=client_headers)
    assert r.status_code == 401
