# CadenceIR | Music Search & Information Retrieval

CadenceIR is a music discovery and information retrieval application built as a CSDC7023 mini-project. It retrieves current track metadata from Apple's iTunes Search API, builds an inverted index from that live result set, and ranks candidates with Boolean retrieval, field-weighted TF-IDF, cosine similarity, and relevance feedback.

## Run locally

Requires Python 3.10+ and network access to `itunes.apple.com`.

```powershell
cd outputs/cadence-ir
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000. On macOS/Linux, activate with `source .venv/bin/activate`.

SQLite is initialized at `data/cadenceir.sqlite3`. Set `CADENCEIR_DB` to choose a different location. No API key or credentials are required. `.env.example` is provided for local configuration; the app does not load `.env` automatically, so export `CADENCEIR_DB` in the process environment when changing the database path.

## Deploy on Render

The included `render.yaml` configures a single free Render web service. Place this project at the root of a GitHub repository, push it, then in Render choose **New → Blueprint** and connect that repository. Render reads the blueprint, installs `requirements.txt`, starts FastAPI on its assigned port, and checks `/api/health`.

The free service has an ephemeral filesystem. The app runs normally, but SQLite history, favorites, and relevance judgments may reset when the service restarts or deploys. Render persistent disks require a paid web service. Before choosing a paid plan, decide whether to attach persistent storage or move the database to a managed database. Check Render's current plan details before provisioning.

## Provider choice and boundaries

The live provider is Apple's public iTunes Search API. Its documented endpoints support music track search and ID-based artist/album lookup without a developer token. The response may include track title, artist, album, genre, release date, artwork, a store URL, and a 30-second preview URL. Apple documents an approximate limit of 20 requests per minute; CadenceIR caches each successful request for 30 minutes and spaces uncached calls at roughly 3.1 seconds. Metadata is fetched at query time, so no static music catalog is shipped.

Apple's promotional-content terms require preview audio to be streamed (not saved), used to promote that content, attributed as “provided courtesy of iTunes,” and accompanied by an approved Store link. The player only streams a provider-issued preview in the browser and keeps the Apple link beside the player. A preview may be unavailable for a track. The app does not provide full-track playback.

The API does not return lyrics. Lyrics search and lyric indexing are therefore explicitly unavailable; text typed as lyrics is treated as a metadata query and cannot be expected to find a track when those words do not occur in returned metadata. No lyric scraping or invented lyrics are used. The provider adapter interfaces leave a future compliant lyrics source as a separate extension point.

Search's local corpus is only the current provider response (up to 50 records by default). That makes each index real and reproducible from the live response, but it is not a persistent, whole-world music index. Broad concepts such as moods and decades are limited by what the provider returns for the submitted query and what metadata it supplies.

## Architecture

```text
Browser (HTML/CSS/JS)
  └── FastAPI /api
       ├── SearchService boundary and validation
       ├── ITunesProvider (metadata, artist/album, preview URL)
       ├── QueryProcessor (normalization, tokenization, phrases, Boolean operators)
       ├── InvertedIndex (from current live provider records)
       ├── TF-IDF / vector and field-zone ranking
       ├── Rocchio relevance-feedback reranker
       └── SQLite (search history, judgments, favorites, metrics)
```

`backend/retrieval/` contains focused retrieval modules; `backend/providers/` contains provider contracts and the Apple adapter; `backend/database.py` owns persistence; `backend/main.py` is the validated HTTP layer. The frontend is served from the same origin, so API keys are not exposed in client code and no permissive CORS policy is needed.

## IR model

* **Tokenization and normalization:** Unicode compatibility normalization, case folding, apostrophe and punctuation handling, and token boundaries. Common stop words are defined for extension; they are not blindly removed from proper names.
* **Inverted index:** term → set of IDs for the actual current provider records, with per-zone posting lists and prefix matching for terms of at least three characters.
* **Boolean retrieval:** explicit `AND`, `OR`, and `NOT` combine postings with intersection, union, and difference. Plain Boolean mode uses conjunction by default.
* **TF-IDF / vector-space ranking:** logarithmic term frequency, smoothed inverse document frequency, query/document vectors, and cosine normalization contribute to the ranking score. Vector mode scores the full live response set; Hybrid mode first narrows candidates through postings, then applies vector scoring plus exact-title and phrase boosts.
* **Zone weighting:** title 3.0, artist 2.4, album 1.5, genre 1.0. This explicit descending policy favors the fields most directly identifying a known song while still allowing genre discovery. The ranking explanation reports matched fields, TF-IDF contribution, exact-title and phrase boosts.
* **Relevance feedback:** per-search labels are stored in SQLite. The reranker uses Rocchio's `Q′ = αQ + β centroid(relevant) − γ centroid(non-relevant)` with α=1, β=0.75, γ=0.15, then scores the indexed result vectors against the refined query vector. Positive judgments also trigger a bounded live catalog search for up to three selected artists; up to 25 additional tracks per artist are included only when the provider confirms the same artist ID. Reset removes judgments and restores the original result corpus.
* **Evaluation:** Precision@K, Recall@K, F1 and MRR are computed over searches with judgments. Precision@K counts only results that have been judged within the top K; Recall@K uses relevant labels gathered for that search. The page waits for at least five labels across two searches before reporting metrics.

## API

* `POST /api/search` — live provider search and retrieval; accepts `query`, `mode` (`hybrid`, `vector`, `boolean`), `field`, and `limit`.
* `POST /api/search/feedback` — stores/withdraws a relevance label and returns the updated ranking.
* `GET /api/songs/{id}`, `GET /api/artists/{id}`, `GET /api/albums/{id}` — provider-backed details.
* `GET /api/history`, `GET|POST /api/favorites`, `GET /api/evaluation`, `GET /api/providers`, `GET /api/health`.

The endpoint for song details serves provider metadata recently retrieved by search, or resolves the provider ID if the track was returned from an album lookup. Artist/album detail calls use the ID lookup API. Favorites must match a recent live search record and validate provider URL hosts before persistence.

## Syllabus mapping

| CSDC7023 topic | CadenceIR implementation |
|---|---|
| Introduction and retrieval process | Query → normalization → provider candidates → local postings → ranking → results |
| Query structures | Free text, quoted phrase boosts, explicit Boolean operators |
| Pattern matching | Prefix term lookup for partial tokens of three or more characters |
| Inverted files | In-memory term/zone postings built from live records per search |
| Boolean model | Posting-set intersection, union and difference |
| Term weighting | Log TF and smoothed IDF |
| Vector space model | Weighted term vectors and cosine similarity |
| Field / zone weighting | Configured title, artist, album and genre weights |
| Relevance feedback | Rocchio query-vector reformulation, labels persisted per search |
| Evaluation | Precision@K, Recall@K, F1 and MRR over recorded labels |
| Multimedia IR | Music metadata discovery and provider-issued preview playback |
| Distributed IR / providers | Provider abstraction, external live catalog API, timeout/cache boundary |

## Demonstration flow

1. Search a real title such as `Blinding Lights` and open “Why this result?” to inspect measured title/artist field signals.
2. Try `artist AND album-term`, `term OR term`, or `term NOT remix`; the explicit operators act on actual result postings.
3. Switch between Hybrid, Vector and Boolean ranking.
4. Mark tracks relevant and non-relevant; observe their order change and the feedback indicator.
5. Visit Evaluation to see metrics after labels are recorded.
6. Play only a returned preview when available and use its adjacent Apple store link.
7. Search an artist or album and follow the returned artist/album metadata.

## Limitations

Lyrics, full-track playback, auth-based user accounts, and global recommendations are intentionally not simulated. The app persists history, favorites and judgments locally in SQLite, without login. Genre and mood recall depends on provider metadata and candidate search behavior. Results and scores are scoped to a bounded response set. The iTunes API rate limit and result geography may affect availability. The UI includes an attribution and provider documentation link; review the provider's current terms before distributing a hosted production service.

## Development checks

```powershell
python -m pytest
python -m compileall backend
```
