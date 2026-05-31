from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200

def test_store_vibe():
    response = client.get("/api/v1/store/vibe")
    assert response.status_code == 200

def test_metrics():
    response = client.get("/stores/STORE001/metrics")
    assert response.status_code == 200

def test_events():
    response = client.get("/stores/STORE001/events")
    assert response.status_code == 200