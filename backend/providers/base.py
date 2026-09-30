"""Provider contracts shared by metadata and playback adapters."""
from __future__ import annotations
from abc import ABC, abstractmethod


class MusicProvider(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 40) -> list[dict]: ...

    @abstractmethod
    async def artist(self, artist_id: str) -> dict: ...

    @abstractmethod
    async def album(self, album_id: str) -> dict: ...

    @abstractmethod
    async def song(self, song_id: str) -> dict: ...


class PlaybackProvider(ABC):
    """Playback metadata only; clients stream provider-issued promotional previews."""

    @abstractmethod
    def preview(self, song: dict) -> str | None: ...
