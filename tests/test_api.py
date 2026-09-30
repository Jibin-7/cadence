from fastapi.testclient import TestClient

from backend.main import app


def test_health_empty_search_and_frontend():
    client = TestClient(app)
    assert client.get("/api/health").json()["lyricsSearch"] is False
    assert client.post("/api/search", json={"query": "   "}).status_code == 422
    response = client.get("/")
    assert response.status_code == 200
    assert "CadenceIR" in response.text
