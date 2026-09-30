# Setup and operation

## Requirements

* Python 3.10 or newer
* Internet access to `itunes.apple.com` for live search

## Windows PowerShell

```powershell
cd outputs/cadence-ir
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open http://127.0.0.1:8000.

For macOS/Linux, use `source .venv/bin/activate` to activate the virtual environment. Set `CADENCEIR_DB` in the process environment to change SQLite's path. `.env.example` lists the optional setting; the app does not read `.env` automatically. No API credentials are needed.

## Verify

```powershell
python -m pytest -q
python -m compileall -q backend
node --check frontend\app.js
```

## Local persistence

SQLite is created on first import at `data/cadenceir.sqlite3`. It stores search history, search-result snapshots, relevance labels, and favorites. It does not store audio or credentials. `data/*.sqlite3` is ignored by Git.

## Useful routes

* `GET /api/health` — app and capability status.
* `GET /api/providers` — provider limits and unavailable features.
* `POST /api/search` — query/mode/field/year filter/limit.
* `POST /api/search/feedback` — set or withdraw a per-search label.
* `GET /api/songs/{id}`, `/api/artists/{id}`, `/api/albums/{id}` — provider metadata.
* `GET /api/history`, `GET|POST /api/favorites`, `GET /api/evaluation` — local persisted features.

## Operational notes

The provider adapter caches successful responses in memory for 30 minutes, caps its cache, and spaces uncached calls to stay under Apple's documented approximate request rate. Search and detail requests use an eight-second timeout and one retry for transient transport or server errors. HTTP 429 responses return a friendly rate-limit message. Metadata unavailable in the response is omitted; lyrics remain unavailable.
