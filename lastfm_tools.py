from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import urlencode
from urllib.request import urlopen


API_ROOT = "https://ws.audioscrobbler.com/2.0/"


@dataclass(slots=True)
class LastFmTrack:
    name: str
    artist: str
    url: str
    match: str


@dataclass(slots=True)
class LastFmArtist:
    name: str
    url: str
    match: str


def _request(params: dict[str, object]) -> dict[str, object]:
    query = urlencode({**params, "format": "json"})
    with urlopen(f"{API_ROOT}?{query}", timeout=15) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Last.fm returned an invalid response. Try again shortly.")
    if "error" in data:
        raise ValueError(data.get("message", "Last.fm request failed."))
    return data


def fetch_similar_tracks(
    api_key: str,
    artist: str,
    track: str,
    limit: int = 10,
    autocorrect: bool = True,
) -> list[LastFmTrack]:
    if not api_key.strip():
        raise ValueError("A Last.fm API key is required.")
    if not artist.strip() or not track.strip():
        raise ValueError("Both artist and track are required for Last.fm similar tracks.")

    data = _request(
        {
            "method": "track.getsimilar",
            "api_key": api_key.strip(),
            "artist": artist.strip(),
            "track": track.strip(),
            "limit": max(1, min(int(limit), 50)),
            "autocorrect": 1 if autocorrect else 0,
        }
    )
    items = data.get("similartracks", {}).get("track", [])
    results: list[LastFmTrack] = []
    for item in items:
        results.append(
            LastFmTrack(
                name=str(item.get("name", "")),
                artist=str(item.get("artist", {}).get("name", "")),
                url=str(item.get("url", "")),
                match=str(item.get("match", "")),
            )
        )
    return results


def fetch_similar_artists(
    api_key: str,
    artist: str,
    limit: int = 10,
    autocorrect: bool = True,
) -> list[LastFmArtist]:
    if not api_key.strip():
        raise ValueError("A Last.fm API key is required.")
    if not artist.strip():
        raise ValueError("An artist name is required for Last.fm similar artists.")

    data = _request(
        {
            "method": "artist.getsimilar",
            "api_key": api_key.strip(),
            "artist": artist.strip(),
            "limit": max(1, min(int(limit), 50)),
            "autocorrect": 1 if autocorrect else 0,
        }
    )
    items = data.get("similarartists", {}).get("artist", [])
    results: list[LastFmArtist] = []
    for item in items:
        results.append(
            LastFmArtist(
                name=str(item.get("name", "")),
                url=str(item.get("url", "")),
                match=str(item.get("match", "")),
            )
        )
    return results

