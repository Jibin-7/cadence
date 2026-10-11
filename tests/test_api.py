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


def test_relevant_feedback_adds_same_artist_tracks_and_reset_restores_baseline(tmp_path, monkeypatch):
    import asyncio

    from backend import database, main

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "feedback.sqlite3")
    database.initialize()
    first = {"id": "track-1", "title": "Needle Song", "artist": "Example Artist", "artistId": "42", "album": "First", "genre": "Pop"}
    database.save_search("feedback-search", "needle", "hybrid", [{"song": first, "score": 0.6, "explanation": {}}])

    async def artist_search(query, limit):
        assert query == "Example Artist"
        return [
            first,
            {"id": "track-2", "title": "Other Song", "artist": "Example Artist", "artistId": "42", "album": "Second", "genre": "Pop"},
            {"id": "track-3", "title": "Different Artist Song", "artist": "Another Artist", "artistId": "77", "album": "Third", "genre": "Rock"},
        ]

    monkeypatch.setattr(main.provider, "search", artist_search)
    refined = asyncio.run(main.feedback(main.FeedbackRequest(searchId="feedback-search", songId="track-1", label=1)))

    assert refined["expansion"] == {"added": 1, "artists": [{"name": "Example Artist", "count": 1}]}
    assert {row["song"]["id"] for row in refined["results"]} == {"track-1", "track-2"}

    reset = asyncio.run(main.feedback(main.FeedbackRequest(searchId="feedback-search", songId="track-1", label=0)))
    assert reset["judgmentCount"] == 0
    assert reset["expansion"]["added"] == 0
    assert {row["song"]["id"] for row in reset["results"]} == {"track-1"}
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
