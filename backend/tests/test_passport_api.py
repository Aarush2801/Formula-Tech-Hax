import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    monkeypatch.setenv("APEX_DB", path)

    # api.py and passport_api.py both read APEX_DB at import time, so a fresh
    # temp DB per test requires fresh imports.
    import sys
    for mod in ("apex.api", "apex.passport_api"):
        sys.modules.pop(mod, None)
    from apex.api import app

    with TestClient(app) as c:
        yield c

    if os.path.exists(path):
        os.remove(path)


def test_existing_health_route_still_works(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_car_presets_lists_all_classes(client):
    r = client.get("/api/car-presets")
    assert r.status_code == 200
    body = r.json()
    assert set(body["classes"]) == {"F1_2026", "F2", "F3", "F4", "FORMULA_E", "FORMULA_STUDENT"}


def test_create_and_get_car(client):
    r = client.post("/api/cars", json=dict(name="API Test Car", car_class="F3"))
    assert r.status_code == 200
    car = r.json()
    assert car["name"] == "API Test Car"
    assert car["car_profile"]["class_name"] == "F3"

    r = client.get("/api/cars")
    assert any(c["id"] == car["id"] for c in r.json()["cars"])


def test_create_car_unknown_class_without_profile_fails(client):
    r = client.post("/api/cars", json=dict(name="Bad Car", car_class="NOT_A_CLASS"))
    assert r.status_code == 400


def test_passport_route_returns_full_view(client):
    car = client.post("/api/cars", json=dict(name="Passport Car", car_class="F4")).json()
    r = client.get(f"/api/cars/{car['id']}/passport")
    assert r.status_code == 200
    body = r.json()
    assert len(body["parts"]) == 8
    assert body["chain_verification"]["valid"] is True
    assert len(body["policy_conditions"]) == 3


def test_passport_route_404_for_unknown_car(client):
    r = client.get("/api/cars/does-not-exist/passport")
    assert r.status_code == 404


def test_replace_part_via_api(client):
    car = client.post("/api/cars", json=dict(name="Wear Car", car_class="F3")).json()
    r = client.post(f"/api/cars/{car['id']}/parts/brakes/replace")
    assert r.status_code == 200
    parts = {p["name"]: p for p in r.json()["parts"]}
    assert parts["brakes"]["life_used_pct"] == 0.0


def test_replace_unknown_part_404s(client):
    car = client.post("/api/cars", json=dict(name="Wear Car 2", car_class="F3")).json()
    r = client.post(f"/api/cars/{car['id']}/parts/not_a_part/replace")
    assert r.status_code == 404


def test_incident_and_claim_pack_flow(client):
    car = client.post("/api/cars", json=dict(name="Incident Car", car_class="F2")).json()
    r = client.post(f"/api/cars/{car['id']}/incidents",
                    json=dict(description="Spin at turn 6"))
    assert r.status_code == 200
    incident_id = r.json()["incident_id"]

    r = client.get(f"/api/cars/{car['id']}/incidents")
    assert len(r.json()["incidents"]) == 1

    r = client.get(f"/api/cars/{car['id']}/claim-pack/{incident_id}")
    assert r.status_code == 200
    pack = r.json()
    assert pack["incident"]["description"] == "Spin at turn 6"
    assert pack["chain_verification"]["valid"] is True


def test_verify_route(client):
    car = client.post("/api/cars", json=dict(name="Verify Car", car_class="F4")).json()
    r = client.get(f"/api/cars/{car['id']}/verify")
    assert r.status_code == 200 and r.json()["valid"] is True


def test_insurer_summary_route(client):
    car = client.post("/api/cars", json=dict(name="Summary Car", car_class="F3")).json()
    r = client.get(f"/api/cars/{car['id']}/insurer-summary")
    assert r.status_code == 200
    assert "disclaimer" in r.json()


def test_evidence_pack_json_and_html(client):
    car = client.post("/api/cars", json=dict(name="Evidence Car", car_class="F4")).json()
    r = client.get(f"/api/cars/{car['id']}/evidence-pack")
    assert r.status_code == 200 and r.json()["car"]["id"] == car["id"]

    r = client.get(f"/api/cars/{car['id']}/evidence-pack?format=html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Evidence Car" in r.text


def test_stress_test_job_lifecycle(client):
    car = client.post("/api/cars", json=dict(name="Stress API Car", car_class="F3")).json()
    r = client.post(f"/api/cars/{car['id']}/stress-test",
                    json=dict(track_id="vale_park", weather="DRY", n_races=10))
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    import time
    result = None
    for _ in range(60):
        r = client.get(f"/api/stress-test/{job_id}")
        body = r.json()
        if body["status"] == "complete":
            result = body["result"]
            break
        if body["status"] == "error":
            pytest.fail(f"stress test job failed: {body['error']}")
        time.sleep(0.5)
    assert result is not None, "stress test job did not complete in time"
    assert result["car_id"] == car["id"]
    assert len(result["parts"]) == 8


def test_stress_test_unknown_car_404s(client):
    r = client.post("/api/cars/no-such-car/stress-test", json=dict(n_races=10))
    assert r.status_code == 404


def test_unknown_job_id_404s(client):
    r = client.get("/api/stress-test/not-a-real-job")
    assert r.status_code == 404
