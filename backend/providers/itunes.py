"""Apple iTunes Search API adapter with bounded TTL caching and timeouts."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from urllib.parse import urlparse

import httpx

from .base import MusicProvider, PlaybackProvider


class ProviderUnavailable(Exception):
    pass


class ITunesProvider(MusicProvider, PlaybackProvider):
    BASE = "https://itunes.apple.com"

    def __init__(self, country="us"):
        self.country = country
        self.cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self.lock = asyncio.Lock()
        self.last_call = 0.0
        self.client = httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "CadenceIR/1.0 (university IR project)"})

    async def _json(self, path: str, params: dict, cache_key: str):
        now = time.monotonic()
        cached = self.cache.get(cache_key)
        if cached and cached[0] > now:
            self.cache.move_to_end(cache_key)
            return cached[1]
        async with self.lock:
            delay = 3.1 - (time.monotonic() - self.last_call)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_call = time.monotonic()
            for attempt in range(2):
                try:
                    response = await self.client.get(f"{self.BASE}/{path}", params=params)
                    if response.status_code == 429:
                        raise ProviderUnavailable("The music catalog is rate limited. Please wait a moment and retry.")
                    if response.status_code >= 500 and attempt == 0:
                        await asyncio.sleep(0.35)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                        raise ProviderUnavailable("The music catalog returned an unexpected response.")
                    break
                except ProviderUnavailable:
                    raise
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt == 0:
                        await asyncio.sleep(0.35)
                        continue
                    raise ProviderUnavailable("The music catalog could not be reached. Please try again shortly.") from exc
        self.cache[cache_key] = (time.monotonic() + 1800, data)
        self.cache.move_to_end(cache_key)
        while len(self.cache) > 512:
            self.cache.popitem(last=False)
        return data

    @staticmethod
    def _safe_url(value, domain_suffixes):
        if not isinstance(value, str):
            return None
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(host == suffix or host.endswith("." + suffix) for suffix in domain_suffixes):
            return None
        return value

    def _normalize_track(self, item: dict) -> dict:
        art = self._safe_url(item.get("artworkUrl100") or item.get("artworkUrl60"), {"mzstatic.com"})
        if art:
            art = art.replace("100x100", "600x600").replace("60x60", "600x600")
        preview = item.get("previewUrl")
        if preview and preview.startswith("http://"):
            preview = "https://" + preview[7:]
        preview = self._safe_url(preview, {"itunes.apple.com"})
        store_url = self._safe_url(item.get("trackViewUrl") or item.get("collectionViewUrl"), {"itunes.apple.com", "music.apple.com"})
        release_date = item.get("releaseDate") if isinstance(item.get("releaseDate"), str) else ""
        title = item.get("trackName") if isinstance(item.get("trackName"), str) else ""
        artist = item.get("artistName") if isinstance(item.get("artistName"), str) else ""
        album = item.get("collectionName") if isinstance(item.get("collectionName"), str) else ""
        genre = item.get("primaryGenreName") if isinstance(item.get("primaryGenreName"), str) else ""
        return {
            "id": str(item.get("trackId", "")), "title": title,
            "artist": artist, "album": album,
            "genre": genre, "releaseDate": release_date[:10],
            "artwork": art, "storeUrl": store_url,
            "previewUrl": preview, "durationMs": item.get("trackTimeMillis"),
            "artistId": str(item.get("artistId", "")), "albumId": str(item.get("collectionId", "")),
            "provider": "Apple iTunes",
        }

    async def search(self, query: str, limit: int = 40) -> list[dict]:
        data = await self._json("search", {"term": query, "media": "music", "entity": "song", "limit": min(100, max(1, limit)), "country": self.country}, f"search:{self.country}:{query.casefold()}")
        return [song for raw in data.get("results", []) if isinstance(raw, dict) and (song := self._normalize_track(raw)).get("id") and song.get("title")]

    async def artist(self, artist_id: str) -> dict:
        data = await self._json("lookup", {"id": artist_id, "entity": "album", "limit": 50, "country": self.country}, f"artist:{artist_id}")
        rows = data.get("results", [])
        head = next((r for r in rows if r.get("wrapperType") == "artist"), {})
        albums = [{"id": str(r.get("collectionId")), "title": r.get("collectionName"), "artwork": r.get("artworkUrl100"), "releaseDate": r.get("releaseDate", "")[:10], "storeUrl": r.get("collectionViewUrl")} for r in rows if r.get("wrapperType") == "collection"]
        return {"id": artist_id, "name": head.get("artistName", ""), "storeUrl": head.get("artistViewUrl"), "albums": albums, "provider": "Apple iTunes"}

    async def song(self, song_id: str) -> dict:
        data = await self._json("lookup", {"id": song_id, "country": self.country}, f"song:{song_id}")
        track = next((r for r in data.get("results", []) if r.get("wrapperType") == "track"), None)
        if not track:
            raise ProviderUnavailable("That track is no longer available from the catalog.")
        return self._normalize_track(track)

    async def album(self, album_id: str) -> dict:
        data = await self._json("lookup", {"id": album_id, "entity": "song", "country": self.country}, f"album:{album_id}")
        rows = data.get("results", [])
        collection = next((r for r in rows if r.get("wrapperType") == "collection"), {})
        return {"id": album_id, "title": collection.get("collectionName", ""), "artist": collection.get("artistName", ""), "artwork": collection.get("artworkUrl100"), "storeUrl": collection.get("collectionViewUrl"), "tracks": [self._normalize_track(r) for r in rows if r.get("wrapperType") == "track"], "provider": "Apple iTunes"}

    def preview(self, song: dict) -> str | None:
        return song.get("previewUrl")

    async def close(self):
        await self.client.aclose()
