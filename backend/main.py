"""FastAPI application and HTTP boundary for CadenceIR."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database
from .providers.itunes import ITunesProvider, ProviderUnavailable
from .retrieval.index import InvertedIndex, rank_documents
from .retrieval.text import process_query, tokenize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("cadenceir")
provider = ITunesProvider()
database.initialize()
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
INDEX_CACHE: OrderedDict[tuple, InvertedIndex] = OrderedDict()


@asynccontextmanager
async def lifespan(_app):
    yield
    await provider.close()


app = FastAPI(title="CadenceIR", version="1.0.0", description="Music discovery powered by information retrieval", lifespan=lifespan)


def get_index(songs: list[dict]) -> InvertedIndex:
    key = tuple((s.get("id"), s.get("title"), s.get("artist"), s.get("album"), s.get("genre")) for s in songs)
    cached = INDEX_CACHE.get(key)
    if cached is not None:
        INDEX_CACHE.move_to_end(key)
        return cached
    index = InvertedIndex(songs, tokenize)
    INDEX_CACHE[key] = index
    while len(INDEX_CACHE) > 16:
        INDEX_CACHE.popitem(last=False)
    logger.info("index_built documents=%d terms=%d cached_corpora=%d", len(index.docs), len(index.postings), len(INDEX_CACHE))
    return index


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=160)
    mode: str = Field(default="hybrid", pattern="^(hybrid|vector|boolean)$")
    field: str | None = Field(default=None, pattern="^(all|title|artist|album|genre)$")
    limit: int = Field(default=40, ge=1, le=100)
    year_from: int | None = Field(default=None, ge=1900, le=2099)
    year_to: int | None = Field(default=None, ge=1900, le=2099)


class FeedbackRequest(BaseModel):
    searchId: str = Field(min_length=1, max_length=80)
    songId: str = Field(min_length=1, max_length=40)
    label: int = Field(ge=-1, le=1)


class FavoriteRequest(BaseModel):
    song: dict


def provider_query(query: str) -> str:
    query = re.sub(r'"([^\"]+)"', r"\1", query)
    return re.sub(r"\b(?:AND|OR|NOT)\b", " ", query, flags=re.I).strip()


@app.get("/api/health")
async def health():
    return {"ok": True, "provider": "Apple iTunes Search API", "lyricsSearch": False}


@app.post("/api/search")
async def search(payload: SearchRequest):
    started = time.perf_counter()
    query = payload.query.strip()
    if not query or not tokenize(query):
        raise HTTPException(status_code=422, detail="Enter one or more search terms.")
    external_query = provider_query(query)
    if not external_query:
        raise HTTPException(status_code=422, detail="Add a music search term alongside Boolean operators.")
    if payload.year_from and payload.year_to and payload.year_from > payload.year_to:
        raise HTTPException(status_code=422, detail="The start year must be before the end year.")
    try:
        songs = await provider.search(external_query, payload.limit)
    except ProviderUnavailable as exc:
        logger.warning("provider_unavailable query_length=%s error=%s", len(query), str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Query-field restriction is applied to provider-supplied live metadata before local indexing.
    parsed = process_query(query)
    if payload.field and payload.field != "all":
        songs = [s for s in songs if parsed.terms and any(t in tokenize(s.get(payload.field, "")) or any(w.startswith(t) for w in tokenize(s.get(payload.field, "")) if len(t) >= 3) for t in parsed.terms)]
    if payload.year_from or payload.year_to:
        songs = [s for s in songs if (year_text := (s.get("releaseDate") or "")[:4]).isdigit() and (year := int(year_text)) and (not payload.year_from or year >= payload.year_from) and (not payload.year_to or year <= payload.year_to)]
    index = get_index(songs)
    ranked = rank_documents(index, parsed, payload.mode)
    sid = uuid.uuid4().hex
    database.save_search(sid, query, payload.mode, ranked)
    logger.info("search query_length=%s mode=%s provider_count=%d result_count=%d latency_ms=%d", len(query), payload.mode, len(songs), len(ranked), int((time.perf_counter()-started)*1000))
    return {"searchId": sid, "query": query, "mode": "boolean" if parsed.boolean_mode else payload.mode, "resultCount": len(ranked), "providerCount": len(songs), "results": ranked, "lyricsAvailable": False, "retrieval": {"indexTerms": len(index.postings), "indexedDocuments": len(index.docs), "candidateCount": len(ranked), "pipeline": ["normalize", "tokenize", "inverted-index", "tf-idf cosine", "zone-weight", "exact/phrase boost"]}}


async def expand_relevant_artists(songs: list[dict], labels: dict[str, int], judged_songs: dict[str, dict] | None = None) -> tuple[list[dict], dict]:
    """Add live catalog tracks by positively judged artists to the Rocchio corpus."""
    song_by_id = {str(song.get("id")): song for song in songs}
    artists: list[dict] = []
    seen_artists: set[str] = set()
    for song_id, label in labels.items():
        selected = (judged_songs or {}).get(str(song_id)) or song_by_id.get(str(song_id))
        if label != 1 or not selected:
            continue
        artist_name = str(selected.get("artist") or "").strip()
        artist_id = str(selected.get("artistId") or "").strip()
        key = artist_id or artist_name.casefold()
        if artist_name and key not in seen_artists:
            seen_artists.add(key)
            artists.append({"id": artist_id, "name": artist_name})
        if len(artists) >= 3:
            break

    expanded = list(songs)
    known_ids = set(song_by_id)
    for song_id, song in (judged_songs or {}).items():
        if song_id not in known_ids:
            expanded.append(song)
            known_ids.add(song_id)
    artist_details = []
    for artist in artists:
        try:
            candidates = await provider.search(artist["name"], 50)
        except ProviderUnavailable as exc:
            logger.info("feedback_artist_expansion_unavailable artist=%s error=%s", artist["id"] or artist["name"], str(exc))
            continue
        if artist["id"]:
            matches = [song for song in candidates if str(song.get("artistId") or "") == artist["id"]]
        else:
            matches = [song for song in candidates if str(song.get("artist") or "").casefold() == artist["name"].casefold()]
        new_tracks = [song for song in matches if str(song.get("id")) not in known_ids][:25]
        for song in new_tracks:
            known_ids.add(str(song.get("id")))
            expanded.append(song)
        artist_details.append({"name": artist["name"], "count": len(new_tracks)})

    return expanded, {"added": len(expanded) - len(songs), "artists": artist_details}


@app.post("/api/search/feedback")
async def feedback(payload: FeedbackRequest):
    record = database.get_search(payload.searchId)
    if not record:
        raise HTTPException(status_code=404, detail="This search has expired or is unavailable.")
    current_results = json.loads(record["results_json"])
    song_ids = {str(r.get("song", {}).get("id")) for r in current_results}
    if payload.songId not in song_ids:
        raise HTTPException(status_code=404, detail="That track does not belong to this result set.")
    if payload.label == 0:
        labels = database.put_feedback(payload.searchId, payload.songId, 0)
    else:
        labels = database.put_feedback(payload.searchId, payload.songId, payload.label)
    terms = process_query(record["query"])
    baseline_results = json.loads(record.get("baseline_json") or record["results_json"])
    songs = [r["song"] for r in baseline_results]
    current_songs = {str(r.get("song", {}).get("id")): r["song"] for r in current_results if r.get("song")}
    judged_songs = {song_id: current_songs[song_id] for song_id in labels if song_id in current_songs}
    songs, expansion = await expand_relevant_artists(songs, labels, judged_songs)
    index = get_index(songs)
    reranked = rank_documents(index, terms, record["mode"], labels)
    database.update_search_results(payload.searchId, reranked)
    logger.info("feedback search_id=%s label=%d judgments=%d", payload.searchId, payload.label, len(labels))
    return {"searchId": payload.searchId, "results": reranked, "judgmentCount": len(labels), "refined": bool(labels), "expansion": expansion}


@app.get("/api/songs/{song_id}")
async def song_detail(song_id: str):
    # The result endpoint deliberately only serves metadata previously returned by the live provider.
    with database.connect() as db:
        for row in db.execute("SELECT results_json FROM searches ORDER BY created_at DESC LIMIT 50"):
            for result in json.loads(row[0]):
                song = result.get("song", {})
                if song.get("id") == song_id:
                    return song
    if not song_id.isdigit():
        raise HTTPException(status_code=422, detail="Invalid track identifier.")
    try:
        return await provider.song(song_id)
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/artists/{artist_id}")
async def artist_detail(artist_id: str):
    if not artist_id.isdigit():
        raise HTTPException(status_code=422, detail="Invalid artist identifier.")
    try:
        return await provider.artist(artist_id)
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/albums/{album_id}")
async def album_detail(album_id: str):
    if not album_id.isdigit():
        raise HTTPException(status_code=422, detail="Invalid album identifier.")
    try:
        return await provider.album(album_id)
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/history")
async def get_history():
    return {"items": database.history()}


@app.delete("/api/history/{search_id}")
async def delete_history(search_id: str):
    if not database.delete_search(search_id):
        raise HTTPException(status_code=404, detail="That saved search no longer exists.")
    logger.info("history_deleted search_id=%s", search_id)
    return {"deleted": True}


@app.get("/api/favorites")
async def get_favorites():
    return {"items": database.favorites()}


@app.post("/api/favorites")
async def set_favorite(payload: FavoriteRequest):
    song = payload.song
    if not song.get("id") or song.get("provider") != "Apple iTunes":
        raise HTTPException(status_code=422, detail="Only provider-retrieved tracks can be saved.")
    canonical = None
    with database.connect() as db:
        for row in db.execute("SELECT results_json FROM searches ORDER BY created_at DESC LIMIT 50"):
            canonical = next((r.get("song") for r in json.loads(row[0]) if str(r.get("song", {}).get("id")) == str(song["id"])), None)
            if canonical:
                break
    if not canonical:
        try:
            canonical = await provider.song(str(song["id"]))
        except ProviderUnavailable as exc:
            raise HTTPException(status_code=404, detail="That track could not be verified in the live catalog.") from exc
    song = canonical
    allowed = {"storeUrl": {"itunes.apple.com", "music.apple.com"}, "previewUrl": {"itunes.apple.com"}, "artwork": {"mzstatic.com"}}
    for key, hosts in allowed.items():
        value = song.get(key)
        if value:
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not any(host == suffix or host.endswith("." + suffix) for suffix in hosts):
                raise HTTPException(status_code=422, detail=f"Invalid provider URL in {key}.")
    return {"saved": database.toggle_favorite(song)}


@app.get("/api/evaluation")
async def get_evaluation(k: int = Query(default=5, ge=1, le=20)):
    return database.evaluation(k)


@app.get("/api/providers")
async def get_providers():
    return {"metadata": {"name": "Apple iTunes Search API", "available": True, "authentication": "None", "lyrics": False}, "playback": {"name": "Apple-provided previews", "type": "30-second preview stream when supplied", "fullTracks": False}, "capabilities": ["song and album search", "artist lookup", "album track lookup", "artwork", "store links", "optional 30-second previews"], "unavailable": ["lyrics search", "full-track playback", "provider genre filters independent of track metadata"]}


app.mount("/assets", StaticFiles(directory=FRONTEND), name="assets")


@app.get("/{path:path}")
async def frontend(path: str):
    return FileResponse(FRONTEND / "index.html")
