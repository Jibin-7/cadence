"""SQLite persistence for search history, feedback judgments and favorites."""
from __future__ import annotations
import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("CADENCEIR_DB", Path(__file__).resolve().parent.parent / "data" / "cadenceir.sqlite3"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS searches(id TEXT PRIMARY KEY, query TEXT NOT NULL, mode TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, results_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback(search_id TEXT NOT NULL, song_id TEXT NOT NULL, label INTEGER NOT NULL CHECK(label IN (-1,1)), updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(search_id,song_id));
        CREATE TABLE IF NOT EXISTS favorites(song_id TEXT PRIMARY KEY, song_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_search_created ON searches(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_feedback_search ON feedback(search_id);
        """)


def save_search(search_id: str, query: str, mode: str, results: list[dict]):
    with connect() as db:
        db.execute("INSERT INTO searches(id,query,mode,results_json) VALUES(?,?,?,?)", (search_id, query, mode, json.dumps(results)))


def get_search(search_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM searches WHERE id=?", (search_id,)).fetchone()
        return dict(row) if row else None


def update_search_results(search_id: str, results: list[dict]):
    with connect() as db:
        db.execute("UPDATE searches SET results_json=? WHERE id=?", (json.dumps(results), search_id))


def put_feedback(search_id: str, song_id: str, label: int):
    with connect() as db:
        if label == 0:
            db.execute("DELETE FROM feedback WHERE search_id=? AND song_id=?", (search_id, song_id))
        else:
            db.execute("INSERT INTO feedback(search_id,song_id,label) VALUES(?,?,?) ON CONFLICT(search_id,song_id) DO UPDATE SET label=excluded.label,updated_at=CURRENT_TIMESTAMP", (search_id, song_id, label))
        return {r[0]: r[1] for r in db.execute("SELECT song_id,label FROM feedback WHERE search_id=?", (search_id,))}


def history(limit=30):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,query,mode,created_at FROM searches ORDER BY created_at DESC LIMIT ?", (limit,))]


def delete_search(search_id: str) -> bool:
    """Delete one saved search snapshot and its relevance judgments."""
    with connect() as db:
        db.execute("DELETE FROM feedback WHERE search_id=?", (search_id,))
        cursor = db.execute("DELETE FROM searches WHERE id=?", (search_id,))
        return cursor.rowcount > 0


def toggle_favorite(song: dict):
    with connect() as db:
        existing = db.execute("SELECT 1 FROM favorites WHERE song_id=?", (song["id"],)).fetchone()
        if existing:
            db.execute("DELETE FROM favorites WHERE song_id=?", (song["id"],))
            return False
        db.execute("INSERT INTO favorites(song_id,song_json) VALUES(?,?)", (song["id"], json.dumps(song)))
        return True


def favorites():
    with connect() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT song_json FROM favorites ORDER BY created_at DESC")]


def evaluation(k=5):
    with connect() as db:
        rows = db.execute("SELECT s.id,s.results_json,f.song_id,f.label FROM searches s LEFT JOIN feedback f ON f.search_id=s.id ORDER BY s.created_at DESC").fetchall()
    judged_searches = {}
    all_relevant = 0
    for row in rows:
        if row["label"] is not None:
            judged_searches.setdefault(row["id"], {"results": json.loads(row["results_json"]), "labels": {}})["labels"][row["song_id"]] = row["label"]
    if not judged_searches:
        return {"available": False, "message": "Not enough relevance judgments to calculate these metrics.", "judgments": 0, "queries": 0}
    precisions, recalls, reciprocal_ranks = [], [], []
    total_judgments = 0
    for item in judged_searches.values():
        labels = item["labels"]
        total_judgments += len(labels)
        relevant = sum(v == 1 for v in labels.values())
        all_relevant += relevant
        ranked = [str(r.get("song", {}).get("id")) for r in item["results"]]
        topk = ranked[:k]
        relevant_top = sum(labels.get(sid) == 1 for sid in topk)
        judged_top = sum(sid in labels for sid in topk)
        precisions.append(relevant_top / max(1, judged_top))
        recalls.append(relevant_top / relevant if relevant else 0.0)
        rr = next((1 / (rank + 1) for rank, sid in enumerate(ranked) if labels.get(sid) == 1), 0.0)
        reciprocal_ranks.append(rr)
    if total_judgments < 5 or len(judged_searches) < 2:
        return {"available": False, "message": "Collect at least 5 relevance judgments across 2 or more searches to calculate these metrics.", "judgments": total_judgments, "queries": len(judged_searches), "relevantJudgments": all_relevant}
    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"available": True, "queries": len(judged_searches), "judgments": total_judgments, "relevantJudgments": all_relevant, "precisionAtK": round(precision, 4), "recallAtK": round(recall, 4), "f1": round(f1, 4), "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4), "k": k}
