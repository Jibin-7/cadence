# Architecture

## Data flow

1. FastAPI validates query, mode, field and limit.
2. The query processor normalizes and tokenizes the expression, extracts quoted phrases and Boolean operators.
3. The provider adapter requests a live iTunes Search API response; successful responses are cached for 30 minutes and uncached calls are paced.
4. The index builder derives documents and field posting lists only from those provider records.
5. Boolean candidate selection and/or TF-IDF vector scoring run over this query-time corpus. Zone, phrase and exact-title signals feed the final score.
6. Ranked provider metadata and explanations are returned; the query/result set is persisted for history and feedback.
7. Feedback updates a query-specific judgment set and reconstructs the Rocchio query vector over that search's live corpus.

## Persistence model

SQLite stores `searches(id, query, mode, created_at, results_json)`, `feedback(search_id, song_id, label, updated_at)` and `favorites(song_id, song_json, created_at)`. Feedback has a composite uniqueness key per search and song. The result snapshot preserves the provider-derived candidate set needed to reproduce feedback ranking. No audio is stored.

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
