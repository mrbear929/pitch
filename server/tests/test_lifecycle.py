def test_full_lifecycle(client, client_headers, worker_headers):
    # client submits
    r = client.post("/jobs", json={"url": "https://example.com/v"}, headers=client_headers)
    assert r.status_code == 200
    job_id = r.json()["id"]
    assert r.json()["status"] == "pending"

    # client checks
    r = client.get(f"/jobs/{job_id}", headers=client_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    # worker claims
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200
    assert r.json()["id"] == job_id
    assert r.json()["status"] == "claimed"

    # second worker call should not get the same job
    r = client.get("/jobs/next", headers=worker_headers)
    assert r.status_code == 200
    assert r.json() == {"job": None}

    # worker reports progress
    r = client.post(
        f"/jobs/{job_id}/progress",
        json={"status": "transcribing", "message": "halfway"},
        headers=worker_headers,
    )
    assert r.status_code == 200

    # client sees progress
    r = client.get(f"/jobs/{job_id}", headers=client_headers)
    assert r.json()["status"] == "transcribing"
    assert r.json()["progress_message"] == "halfway"

    # worker posts result
    r = client.post(
        f"/jobs/{job_id}/result",
        json={
            "status": "done",
            "markdown": "# hello\n",
            "title": "Hello video",
            "slug": "hello-video",
        },
        headers=worker_headers,
    )
    assert r.status_code == 200

    # client gets final
    r = client.get(f"/jobs/{job_id}", headers=client_headers)
    body = r.json()
    assert body["status"] == "done"
    assert body["result_markdown"] == "# hello\n"
    assert body["result_title"] == "Hello video"
    assert body["result_slug"] == "hello-video"


def test_404s(client, client_headers, worker_headers):
    r = client.get("/jobs/nonexistent", headers=client_headers)
    assert r.status_code == 404

    r = client.post(
        "/jobs/nonexistent/progress",
        json={"status": "transcribing"},
        headers=worker_headers,
    )
    assert r.status_code == 404


def test_url_required(client, client_headers):
    r = client.post("/jobs", json={}, headers=client_headers)
    assert r.status_code == 400
