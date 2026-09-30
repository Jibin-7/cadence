from backend.database import evaluation, initialize, put_feedback, save_search


def test_evaluation_requires_judgments_and_uses_only_saved_labels(tmp_path, monkeypatch):
    from backend import database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "evaluation.sqlite3")
    initialize()
    assert evaluation()["available"] is False
    rows = [
        {"song": {"id": "s1"}, "score": .8},
        {"song": {"id": "s2"}, "score": .5},
    ]
    save_search("q1", "amber", "hybrid", rows)
    put_feedback("q1", "s1", 1)
    put_feedback("q1", "s2", -1)
    assert evaluation()["available"] is False
    save_search("q2", "quiet river", "hybrid", rows)
    put_feedback("q2", "s1", 1)
    put_feedback("q2", "s2", -1)
    put_feedback("q2", "s3", 1)
    result = evaluation(k=2)
    assert result["available"] is True
    assert result["precisionAtK"] == .5
    assert result["recallAtK"] == .75
    assert result["mrr"] == 1
