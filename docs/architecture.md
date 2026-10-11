# Architecture

## Data flow

1. FastAPI validates query, mode, field and limit.
2. The query processor normalizes and tokenizes the expression, extracts quoted phrases and Boolean operators.
3. The provider adapter requests a live iTunes Search API response; successful responses are cached for 30 minutes and uncached calls are paced.
4. The index builder derives documents and field posting lists only from those provider records.
5. Boolean candidate selection and/or TF-IDF vector scoring run over this query-time corpus. Zone, phrase and exact-title signals feed the final score.
6. Ranked provider metadata and explanations are returned; the query/result set is persisted for history and feedback.
7. Feedback updates a query-specific judgment set, adds a bounded set of live tracks by positively judged artists, and reconstructs the Rocchio query vector over the expanded corpus.

## Persistence model

SQLite stores `searches(id, query, mode, created_at, results_json, baseline_json)`, `feedback(search_id, song_id, label, updated_at)` and `favorites(song_id, song_json, created_at)`. Feedback has a composite uniqueness key per search and song. `baseline_json` preserves the original provider-derived candidate set while `results_json` stores the current feedback-expanded ranking, allowing Reset to restore the starting corpus. No audio is stored.

## Module boundaries

* `retrieval/text.py`: normalization, tokenization, phrase and Boolean query parsing.
* `retrieval/index.py`: inverted index, posting operations, TF-IDF, cosine scoring, zone weights, Rocchio.
* `providers/base.py`: metadata and playback contracts.
* `providers/itunes.py`: outbound HTTP, timeout, cache, response normalization, provider lookup.
* `database.py`: schema, searches, labels, favorites, evaluation.
* `main.py`: validation, consistent HTTP errors, route orchestration, structured logs.
* `frontend/`: accessible search UI, explanations, feedback, evaluation, preview player.

## Security and operations

The API has no client-side secrets. Provider response URLs remain server-originating and favorite records are URL-host validated. Requests use an 8-second timeout, a meaningful provider user agent, and response errors become concise 503 messages. The app serves the UI and JSON API from the same origin; there is no open CORS configuration. SQLite uses WAL mode and indexed timestamps/search IDs.
