"""SQLite persistence for search history, feedback judgments and favorites."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


DB_PATH = Path(
    os.environ.get(
        "CADENCEIR_DB",
        Path(__file__).resolve().parent.parent / "data" / "cadenceir.sqlite3",
    )
)


def connect() -> sqlite3.Connection:
    """Create and return a database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    return db


def initialize() -> None:
    """Create the required database tables and indexes."""
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS searches (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                results_json TEXT NOT NULL,
                baseline_json TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback (
                search_id TEXT NOT NULL,
                song_id TEXT NOT NULL,
                label INTEGER NOT NULL CHECK(label IN (-1, 1)),
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (search_id, song_id)
            );

            CREATE TABLE IF NOT EXISTS favorites (
                song_id TEXT PRIMARY KEY,
                song_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_search_created
                ON searches(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_feedback_search
                ON feedback(search_id);
            """
        )

        # Migrate databases created by older versions.
        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(searches)")
        }

        if "baseline_json" not in columns:
            db.execute(
                "ALTER TABLE searches ADD COLUMN baseline_json TEXT"
            )

        db.execute(
            """
            UPDATE searches
            SET baseline_json = results_json
            WHERE baseline_json IS NULL
            """
        )


def save_search(
    search_id: str,
    query: str,
    mode: str,
    results: list[dict],
) -> None:
    """Save a search and its initial result snapshot."""
    results_json = json.dumps(results)

    with connect() as db:
        db.execute(
            """
            INSERT INTO searches
                (id, query, mode, results_json, baseline_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                search_id,
                query,
                mode,
                results_json,
                results_json,
            ),
        )


def get_search(search_id: str) -> dict | None:
    """Retrieve one saved search."""
    with connect() as db:
        row = db.execute(
            "SELECT * FROM searches WHERE id = ?",
            (search_id,),
        ).fetchone()

        return dict(row) if row else None


def update_search_results(
    search_id: str,
    results: list[dict],
) -> None:
    """Update the current ranked results without changing the baseline."""
    with connect() as db:
        db.execute(
            "UPDATE searches SET results_json = ? WHERE id = ?",
            (json.dumps(results), search_id),
        )


def put_feedback(
    search_id: str,
    song_id: str,
    label: int,
) -> dict[str, int]:
    """
    Save a relevance judgment.

    label =  1: relevant
    label = -1: not relevant
    label =  0: remove the existing judgment
    """
    if label not in (-1, 0, 1):
        raise ValueError("label must be -1, 0, or 1")

    with connect() as db:
        if label == 0:
            db.execute(
                """
                DELETE FROM feedback
                WHERE search_id = ? AND song_id = ?
                """,
                (search_id, song_id),
            )
        else:
            db.execute(
                """
                INSERT INTO feedback (search_id, song_id, label)
                VALUES (?, ?, ?)
                ON CONFLICT(search_id, song_id)
                DO UPDATE SET
                    label = excluded.label,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (search_id, song_id, label),
            )

        rows = db.execute(
            """
            SELECT song_id, label
            FROM feedback
            WHERE search_id = ?
            """,
            (search_id,),
        ).fetchall()

        return {row["song_id"]: row["label"] for row in rows}


def history(limit: int = 30) -> list[dict]:
    """Return recent search history."""
    limit = max(0, int(limit))

    with connect() as db:
        rows = db.execute(
            """
            SELECT id, query, mode, created_at
            FROM searches
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]


def delete_search(search_id: str) -> bool:
    """Delete a saved search and its associated relevance judgments."""
    with connect() as db:
        db.execute(
            "DELETE FROM feedback WHERE search_id = ?",
            (search_id,),
        )

        cursor = db.execute(
            "DELETE FROM searches WHERE id = ?",
            (search_id,),
        )

        return cursor.rowcount > 0


def toggle_favorite(song: dict) -> bool:
    """
    Toggle a favorite.

    Returns True if added, False if removed.
    """
    song_id = song.get("id")

    if song_id is None:
        raise ValueError("Song must contain an 'id' field")

    song_id = str(song_id)

    with connect() as db:
        existing = db.execute(
            "SELECT 1 FROM favorites WHERE song_id = ?",
            (song_id,),
        ).fetchone()

        if existing:
            db.execute(
                "DELETE FROM favorites WHERE song_id = ?",
                (song_id,),
            )
            return False

        db.execute(
            """
            INSERT INTO favorites (song_id, song_json)
            VALUES (?, ?)
            """,
            (song_id, json.dumps(song)),
        )

        return True


def favorites() -> list[dict]:
    """Return saved favorites."""
    with connect() as db:
        rows = db.execute(
            """
            SELECT song_json
            FROM favorites
            ORDER BY created_at DESC
            """
        ).fetchall()

        return [json.loads(row["song_json"]) for row in rows]


def _extract_song_id(result: dict) -> str | None:
    """Extract a normalized song ID from a search result."""
    song = result.get("song", {})

    if not isinstance(song, dict):
        return None

    song_id = song.get("id")

    if song_id is None:
        return None

    return str(song_id)


def evaluation(k: int = 5) -> dict[str, Any]:
    """
    Evaluate search results using Precision@K, Recall@K, F1, and MRR.

    Important:
    - Only explicitly judged documents are used as relevance evidence.
    - Unjudged retrieved documents count as not confirmed relevant for
      Precision@K.
    - Recall is based on the relevant documents judged for each query.
      It is a true recall estimate only when relevance judgments are
      sufficiently complete.
    - Metrics are macro-averaged across searches with feedback.
    - MRR uses the rank of the first judged-relevant result.
    """
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")

    with connect() as db:
        rows = db.execute(
            """
            SELECT
                s.id,
                s.results_json,
                f.song_id,
                f.label
            FROM searches AS s
            LEFT JOIN feedback AS f
                ON f.search_id = s.id
            ORDER BY s.created_at DESC
            """
        ).fetchall()

    judged_searches: dict[str, dict[str, Any]] = {}

    for row in rows:
        search_id = row["id"]

        if search_id not in judged_searches:
            try:
                results = json.loads(row["results_json"])
            except (json.JSONDecodeError, TypeError):
                results = []

            if not isinstance(results, list):
                results = []

            judged_searches[search_id] = {
                "results": results,
                "labels": {},
            }

        if row["label"] is not None:
            judged_searches[search_id]["labels"][
                str(row["song_id"])
            ] = int(row["label"])

    # Only searches with at least one explicit judgment are evaluated.
    judged_searches = {
        search_id: item
        for search_id, item in judged_searches.items()
        if item["labels"]
    }

    if not judged_searches:
        return {
            "available": False,
            "message": (
                "Add relevance judgments to at least one search "
                "before calculating evaluation metrics."
            ),
            "judgments": 0,
            "queries": 0,
        }

    precisions: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []

    total_judgments = 0
    total_relevant_judgments = 0
    evaluated_queries = 0
    judged_topk_count = 0

    for item in judged_searches.values():
        labels: dict[str, int] = item["labels"]
        results: list[dict] = item["results"]

        total_judgments += len(labels)

        relevant_ids = {
            song_id
            for song_id, label in labels.items()
            if label == 1
        }

        total_relevant_judgments += len(relevant_ids)

        # Preserve retrieval order and avoid counting duplicate IDs twice.
        ranked: list[str] = []
        seen: set[str] = set()

        for result in results:
            if not isinstance(result, dict):
                continue

            song_id = _extract_song_id(result)

            if song_id is not None and song_id not in seen:
                ranked.append(song_id)
                seen.add(song_id)

        topk = ranked[:k]

        # Precision@K: relevant retrieved results divided by K,
        # or by the number retrieved when fewer than K exist.
        precision_denominator = min(k, len(topk))

        relevant_topk = sum(
            labels.get(song_id) == 1
            for song_id in topk
        )

        precision_at_k = (
            relevant_topk / precision_denominator
            if precision_denominator > 0
            else 0.0
        )

        # Recall@K is relative to the known relevant judgments.
        recall_at_k = (
            len(relevant_ids.intersection(topk)) / len(relevant_ids)
            if relevant_ids
            else 0.0
        )

        # MRR: reciprocal rank of the first judged-relevant result.
        reciprocal_rank = next(
            (
                1.0 / (rank + 1)
                for rank, song_id in enumerate(ranked)
                if labels.get(song_id) == 1
            ),
            0.0,
        )

        precisions.append(precision_at_k)
        recalls.append(recall_at_k)
        reciprocal_ranks.append(reciprocal_rank)

        judged_topk_count += sum(
            song_id in labels for song_id in topk
        )

        evaluated_queries += 1

    if total_judgments < 5 or evaluated_queries < 2:
        return {
            "available": False,
            "message": (
                "Collect at least 5 relevance judgments across "
                "2 or more searches to calculate these metrics."
            ),
            "judgments": total_judgments,
            "queries": evaluated_queries,
            "relevantJudgments": total_relevant_judgments,
        }

    # Macro averages: each evaluated search has equal weight.
    precision = sum(precisions) / evaluated_queries
    recall = sum(recalls) / evaluated_queries

    # F1 of the macro-averaged precision and recall.
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )

    mrr = sum(reciprocal_ranks) / evaluated_queries

    return {
        "available": True,
        "queries": evaluated_queries,
        "judgments": total_judgments,
        "relevantJudgments": total_relevant_judgments,
        "judgedResultsAtK": judged_topk_count,
        "precisionAtK": round(precision, 4),
        "recallAtK": round(recall, 4),
        "f1": round(f1, 4),
        "mrr": round(mrr, 4),
        "k": k,
        "averaging": "macro",
        "recallNote": (
            "Recall is calculated against known relevant judgments. "
            "It represents true recall only if the relevance judgments "
            "cover the relevant collection for each query."
        ),
    }
```
