from fastapi.testclient import TestClient

from backend.main import app


def test_health_empty_search_and_frontend():
    client = TestClient(app)
    assert client.get("/api/health").json()["lyricsSearch"] is False
    assert client.post("/api/search", json={"query": "   "}).status_code == 422
    response = client.get("/")
    assert response.status_code == 200
    assert "CadenceIR" in response.text


def test_delete_history_removes_result_snapshot_and_feedback(tmp_path, monkeypatch):
    from backend import database

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "history.sqlite3")
    database.initialize()
    database.save_search("search-1", "amber", "hybrid", [{"song": {"id": "track-1"}}])
    database.put_feedback("search-1", "track-1", 1)

    client = TestClient(app)
    response = client.delete("/api/history/search-1")

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert database.history() == []
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    assert client.delete("/api/history/search-1").status_code == 404
