from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import time
import unicodedata
import threading
from urllib.error import URLError

import pandas as pd
import requests
import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from config import APP_DIR, LOCAL_DATA_DIR, SPARETIME_DIR
from table_io import write_table_file


DEFAULT_SCOPES = {
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-follow-modify",
    "user-follow-read",
    "user-library-modify",
    "user-library-read",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-playback-state",
    "user-read-recently-played",
    "user-top-read",
}

TEST_TRACK_ID = "0c6xIDDpzE81m2q797ordA"
TEST_ARTIST_ID = "0TnOYISbd1XYRBk9myaseg"
KOD_CACHE_PATH = LOCAL_DATA_DIR / "spotify_kod_cache.json"

SPOTIFY_TYPE_MAP = {
    "playlist": "playlist",
    "playlists": "playlist",
    "album": "album",
    "albums": "album",
    "artist": "artist",
    "artists": "artist",
    "track": "track",
    "tracks": "track",
    "episode": "episode",
    "episodes": "episode",
    "show": "show",
    "shows": "show",
    "user": "user",
    "users": "user",
}


@dataclass(slots=True)
class SpotifySettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    playlist_ids: list[str]
    device_id: str = ""
    fallback_to_global: bool = True
    cache_path: Path = APP_DIR / ".spotify_cache"


@dataclass(slots=True)
class CapabilityResult:
    name: str
    ok: bool
    detail: str


def _seed_cache_from_original(cache_path: Path) -> None:
    if cache_path.exists():
        return
    original_cache = SPARETIME_DIR / ".cache"
    if original_cache.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(original_cache, cache_path)
        except OSError:
            pass


_AUTH_LOCK = threading.RLock()


class LockedCacheHandler(CacheFileHandler):
    """Prevent parallel clients from reading a partially written token cache."""

    def get_cached_token(self):
        with _AUTH_LOCK:
            return super().get_cached_token()

    def save_token_to_cache(self, token_info):
        with _AUTH_LOCK:
            return super().save_token_to_cache(token_info)


class ConcurrentSpotifyOAuth(SpotifyOAuth):
    def validate_token(self, token_info):
        with _AUTH_LOCK:
            # Another worker may already have refreshed the expired token.
            cached = self.cache_handler.get_cached_token()
            return super().validate_token(cached or token_info)


class CurrentSpotifyClient(spotipy.Spotify):
    """Adapt Spotipy's playlist reads to the current Spotify API."""

    def _get(self, url, args=None, payload=None, **kwargs):
        url = re.sub(r"(playlists/[^/]+)/tracks(?=\?|$)", r"\1/items", url)
        result = super()._get(url, args=args, payload=payload, **kwargs)
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            for entry in result["items"]:
                if isinstance(entry, dict) and "item" in entry and "track" not in entry:
                    entry["track"] = entry["item"]
        return result


def build_spotify_client(
    settings: SpotifySettings,
    extra_scopes: set[str] | None = None,
) -> spotipy.Spotify:
    if not settings.client_id or not settings.client_secret or not settings.redirect_uri:
        raise ValueError("Spotify client ID, client secret, and redirect URI are required.")

    _seed_cache_from_original(settings.cache_path)
    scopes = sorted(DEFAULT_SCOPES | (extra_scopes or set()))
    auth_manager = ConcurrentSpotifyOAuth(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.redirect_uri,
        scope=" ".join(scopes),
        cache_handler=LockedCacheHandler(cache_path=str(settings.cache_path)),
        requests_timeout=15,
    )
    return CurrentSpotifyClient(auth_manager=auth_manager, requests_timeout=20,
                                retries=0, status_retries=0)


def explain_spotify_error(exc: Exception) -> str:
    if isinstance(exc, URLError):
        exc = exc.reason if isinstance(exc.reason, Exception) else exc
    if isinstance(exc, (requests.exceptions.Timeout, TimeoutError)):
        return "Connection timed out. Check your internet connection and try again. Your saved lists and queue remain available offline."
    if isinstance(exc, (requests.exceptions.ConnectionError, URLError)):
        return "Could not connect to the online service. Check your internet connection, VPN or firewall and try again. Local lists and queues still work offline."
    if isinstance(exc, SpotifyException):
        status = getattr(exc, "http_status", "unknown")
        code = getattr(exc, "code", "")
        message = str(getattr(exc, "msg", exc))

        if status == 401:
            return f"Spotify authentication failed (401). Check the client ID, client secret, redirect URI, or refresh the login. {message}"
        if status == 403:
            return (
                "Spotify rejected the request (403). This often means a missing scope, a "
                "Spotify Development Mode restriction, a non-owned playlist, or a Premium/"
                f"active-device requirement. {message}"
            )
        if status == 404:
            if "device" in message.casefold() or "no active" in message.casefold() or "/me/player/" in message.casefold():
                return f"Spotify has no usable playback device (404). Open Spotify, start a song, then reload Devices and select the current device. {message}"
            return ("Spotify could not find or provide this item (404). Check the playlist or track reference. "
                    "Development Mode playlist contents require ownership or collaborator access; some older API features are unavailable. "
                    f"{message}")
        if status == 429:
            return f"Spotify rate limited the request (429). Try again shortly. {message}"
        return f"Spotify request failed ({status}{f'/{code}' if code else ''}). {message}"
    return str(exc)


def playback_device(sp, settings):
    """Use an available selected device, or Spotify's current active device."""
    devices = (sp.devices() or {}).get("devices", [])
    usable = [device for device in devices if not device.get("is_restricted")]
    selected = next((device for device in usable if device.get("id") == settings.device_id), None)
    active = next((device for device in usable if device.get("is_active")), None)
    device = selected or active or (usable[0] if len(usable) == 1 else None)
    if device is None:
        if usable:
            raise ValueError("Several Spotify devices are available. Select one using Devices > Use, then press Play.")
        raise ValueError("Spotify reports no available playback device. Open Spotify on this computer, then press Play here again. Your local queue is saved.")
    if not device.get("is_active"):
        sp.transfer_playback(device_id=device["id"], force_play=False)
        time.sleep(0.5)
    return str(device["id"])


def parse_playlist_entries(value: str) -> list[str]:
    parts = re.split(r"[\n,;]+", value)
    return [extract_spotify_id(part, expected_kind="playlist") for part in parts if part.strip()]


def parse_uri_list(value: str, expected_kind: str | None = None) -> list[str]:
    parts = re.split(r"[\n,;]+", value)
    return [normalize_spotify_uri(part, expected_kind=expected_kind) for part in parts if part.strip()]


def _coerce_spotify_kind(value: str | None) -> str | None:
    if value is None:
        return None
    return SPOTIFY_TYPE_MAP.get(value.strip().casefold())


def normalize_spotify_uri(value: str, expected_kind: str | None = None) -> str:
    cleaned = value.strip()
    expected = _coerce_spotify_kind(expected_kind)
    if not cleaned:
        raise ValueError("Spotify reference is empty.")

    if cleaned.startswith("spotify:"):
        parts = cleaned.split(":")
        if len(parts) < 3:
            raise ValueError(f"Invalid Spotify URI: {cleaned}")
        actual_kind = _coerce_spotify_kind(parts[-2])
        if expected and actual_kind and actual_kind != expected:
            raise ValueError(f"Expected a {expected} reference but got {actual_kind}.")
        return cleaned

    match = re.search(r"open\.spotify\.com/([a-zA-Z]+)/([A-Za-z0-9]+)", cleaned)
    if match:
        actual_kind = _coerce_spotify_kind(match.group(1))
        if not actual_kind:
            raise ValueError(f"Unsupported Spotify URL: {cleaned}")
        if expected and actual_kind != expected:
            raise ValueError(f"Expected a {expected} reference but got {actual_kind}.")
        return f"spotify:{actual_kind}:{match.group(2)}"

    spotify_id = cleaned.split("?")[0]
    if expected:
        return f"spotify:{expected}:{spotify_id}"
    raise ValueError(
        "A plain Spotify ID needs a known type. Use a Spotify URI/URL, or use a field that already knows whether the item is a track, artist, album, or playlist."
    )


def extract_spotify_id(value: str, expected_kind: str | None = None) -> str:
    normalized = normalize_spotify_uri(value, expected_kind=expected_kind)
    if normalized.startswith("spotify:"):
        return normalized.split(":")[-1]
    return normalized


def _format_artists(artists: list[dict[str, object]]) -> str:
    return ", ".join(str(artist.get("name", "")) for artist in artists)


def _flatten_track(track: dict[str, object]) -> dict[str, str]:
    album = track.get("album") or {}
    return {
        "type": "track",
        "name": str(track.get("name", "")),
        "subtitle": _format_artists(track.get("artists", [])),
        "uri": str(track.get("uri", "")),
        "id": str(track.get("id", "")),
        "extra": str(album.get("name", "")),
        "external_url": str(track.get("external_urls", {}).get("spotify", "")),
    }


def _flatten_artist(artist: dict[str, object]) -> dict[str, str]:
    return {
        "type": "artist",
        "name": str(artist.get("name", "")),
        "subtitle": ", ".join(str(item) for item in artist.get("genres", [])[:4]),
        "uri": str(artist.get("uri", "")),
        "id": str(artist.get("id", "")),
        "extra": "",
        "external_url": str(artist.get("external_urls", {}).get("spotify", "")),
    }


def _flatten_album(album: dict[str, object]) -> dict[str, str]:
    return {
        "type": "album",
        "name": str(album.get("name", "")),
        "subtitle": _format_artists(album.get("artists", [])),
        "uri": str(album.get("uri", "")),
        "id": str(album.get("id", "")),
        "extra": str(album.get("release_date", "")),
        "external_url": str(album.get("external_urls", {}).get("spotify", "")),
    }


def _flatten_playlist(playlist: dict[str, object]) -> dict[str, str]:
    owner = playlist.get("owner") or {}
    return {
        "type": "playlist",
        "name": str(playlist.get("name", "")),
        "subtitle": str(owner.get("display_name", owner.get("id", ""))),
        "uri": str(playlist.get("uri", "")),
        "id": str(playlist.get("id", "")),
        "extra": str((playlist.get("items") or playlist.get("tracks") or {}).get("total", "")),
        "external_url": str(playlist.get("external_urls", {}).get("spotify", "")),
    }


def _flatten_queue_item(item: dict[str, object], kind: str) -> dict[str, str]:
    artists = _format_artists(item.get("artists", []))
    return {
        "type": kind,
        "name": str(item.get("name", "")),
        "subtitle": artists,
        "uri": str(item.get("uri", "")),
        "id": str(item.get("id", "")),
        "extra": "",
        "external_url": str(item.get("external_urls", {}).get("spotify", "")),
    }


def _summarize_response(response: object) -> str:
    if response is None:
        return "No data returned."
    if isinstance(response, dict):
        if "items" in response and isinstance(response["items"], list):
            return f"Returned {len(response['items'])} item(s)."
        if "tracks" in response and isinstance(response["tracks"], list):
            return f"Returned {len(response['tracks'])} track(s)."
        if "devices" in response and isinstance(response["devices"], list):
            return f"Returned {len(response['devices'])} device(s)."
        if "queue" in response and isinstance(response["queue"], list):
            return f"Returned queue with {len(response['queue'])} upcoming item(s)."
        return "Request succeeded."
    if isinstance(response, list):
        return f"Returned {len(response)} item(s)."
    return "Request succeeded."


def authorize_user(settings: SpotifySettings) -> dict[str, str]:
    sp = build_spotify_client(settings)
    user = sp.current_user()
    return {
        "display_name": str(user.get("display_name") or user.get("id", "")),
        "user_id": str(user.get("id", "")),
    }


def run_capability_check(settings: SpotifySettings) -> tuple[dict[str, str], list[CapabilityResult]]:
    sp = build_spotify_client(settings)
    profile = sp.current_user()

    checks: list[tuple[str, callable]] = [
        ("Profile", lambda: profile),
        ("Search", lambda: sp.search(q="track:Believe artist:Cher", type="track", limit=1)),
        ("My Playlists", lambda: sp.current_user_playlists(limit=1)),
        ("Saved Tracks", lambda: sp.current_user_saved_tracks(limit=1)),
        ("Recently Played", lambda: sp.current_user_recently_played(limit=1)),
        ("Top Tracks", lambda: sp.current_user_top_tracks(limit=1)),
        ("Devices", sp.devices),
        ("Playback State", sp.current_playback),
        ("Queue", sp.queue),
        ("Recommendations (deprecated)", lambda: sp.recommendations(seed_tracks=[TEST_TRACK_ID], limit=1)),
        ("Audio Features", lambda: sp.audio_features([TEST_TRACK_ID])),
        ("Audio Analysis", lambda: sp.audio_analysis(TEST_TRACK_ID)),
    ]

    results: list[CapabilityResult] = []
    for name, callback in checks:
        try:
            response = callback()
            results.append(CapabilityResult(name=name, ok=True, detail=_summarize_response(response)))
        except Exception as exc:
            results.append(CapabilityResult(name=name, ok=False, detail=explain_spotify_error(exc)))

    return (
        {
            "display_name": str(profile.get("display_name") or profile.get("id", "")),
            "user_id": str(profile.get("id", "")),
        },
        results,
    )


def search_catalog(
    settings: SpotifySettings,
    query: str,
    search_types: list[str],
    limit: int = 10,
) -> list[dict[str, str]]:
    if not query.strip():
        raise ValueError("Search query is required.")
    if not search_types:
        raise ValueError("Select at least one Spotify search type.")

    valid_types = []
    for item in search_types:
        normalized = _coerce_spotify_kind(item)
        if normalized and normalized in {"track", "artist", "album", "playlist"}:
            valid_types.append(normalized)
    if not valid_types:
        raise ValueError("Only track, artist, album, and playlist search types are supported in the GUI.")

    sp = build_spotify_client(settings)
    response = sp.search(q=query.strip(), type=",".join(valid_types), limit=max(1, min(limit, 10)))

    rows: list[dict[str, str]] = []
    for track in response.get("tracks", {}).get("items", []):
        rows.append(_flatten_track(track))
    for artist in response.get("artists", {}).get("items", []):
        rows.append(_flatten_artist(artist))
    for album in response.get("albums", {}).get("items", []):
        rows.append(_flatten_album(album))
    for playlist in response.get("playlists", {}).get("items", []):
        rows.append(_flatten_playlist(playlist))
    return rows


def get_currently_playing(settings: SpotifySettings) -> dict[str, str]:
    sp = build_spotify_client(settings)
    current = sp.current_user_playing_track()
    if not current or not current.get("item"):
        return {}

    item = current.get("item") or {}
    device = current.get("device") or {}
    album = item.get("album") or {}
    return {
        "track_name": str(item.get("name", "")),
        "artists": _format_artists(item.get("artists", [])),
        "album": str(album.get("name", "")),
        "device": str(device.get("name", "")),
        "progress_ms": str(current.get("progress_ms", "")),
        "duration_ms": str(item.get("duration_ms", "")),
        "is_playing": str(current.get("is_playing", "")),
        "uri": str(item.get("uri", "")),
    }


def get_playback_state(settings: SpotifySettings) -> dict[str, str]:
    sp = build_spotify_client(settings)
    state = sp.current_playback()
    if not state:
        return {}

    device = state.get("device") or {}
    item = state.get("item") or {}
    return {
        "is_playing": str(state.get("is_playing", "")),
        "shuffle_state": str(state.get("shuffle_state", "")),
        "repeat_state": str(state.get("repeat_state", "")),
        "device_name": str(device.get("name", "")),
        "device_id": str(device.get("id", "")),
        "device_volume": str(device.get("volume_percent", "")),
        "track_name": str(item.get("name", "")),
        "track_uri": str(item.get("uri", "")),
        "artists": _format_artists(item.get("artists", [])),
        "album": str((item.get("album") or {}).get("name", "")),
        "progress_ms": str(state.get("progress_ms", "")),
        "duration_ms": str(item.get("duration_ms", "")),
    }


def list_devices(settings: SpotifySettings) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    response = sp.devices()
    rows: list[dict[str, str]] = []
    for device in response.get("devices", []):
        rows.append(
            {
                "name": str(device.get("name", "")),
                "id": str(device.get("id", "")),
                "type": "device",
                "device_type": str(device.get("type", "")),
                "subtitle": "Active" if device.get("is_active") else "Available",
                "extra": f"{device.get('type', '')} / {device.get('volume_percent', '')}%",
                "restricted": "Yes" if device.get("is_restricted") else "No",
            }
        )
    return rows


def list_queue(settings: SpotifySettings) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    sp = build_spotify_client(settings)
    response = sp.queue() or {}
    current_item = response.get("currently_playing")
    current_row = _flatten_queue_item(current_item, "current") if current_item else None
    queue_rows = [_flatten_queue_item(item, "queue") for item in (response.get("queue") or []) if isinstance(item, dict)]
    return current_row, queue_rows


def find_in_playlists(
    sp: spotipy.Spotify,
    track_name: str,
    playlist_ids: list[str],
    artist_name: str = "",
) -> tuple[str | None, str | None]:
    query = track_name.casefold()
    artist_query = artist_name.casefold().strip()
    fallback: tuple[str | None, str | None] = (None, None)
    for playlist_id in playlist_ids:
        results = sp.playlist_items(playlist_id, additional_types=["track"], limit=100)
        while True:
            for item in results.get("items", []):
                track = item.get("track")
                if not track:
                    continue
                name = str(track.get("name", ""))
                if query in name.casefold():
                    artists = _format_artists(track.get("artists", [])).casefold()
                    candidate = (str(track["uri"]), name)
                    if artist_query and artist_query in artists:
                        return candidate
                    if fallback == (None, None):
                        fallback = candidate
            if results.get("next"):
                results = sp.next(results)
            else:
                break
    return fallback


def list_playlist_tracks(
    settings: SpotifySettings,
    playlist_reference: str,
    limit: int = 500,
) -> list[dict[str, str]]:
    playlist_id = extract_spotify_id(playlist_reference, expected_kind="playlist")
    sp = build_spotify_client(settings)
    rows: list[dict[str, str]] = []
    offset = 0
    page_size = min(100, max(1, limit))

    while len(rows) < limit:
        page = sp.playlist_items(
            playlist_id,
            additional_types=["track", "episode"],
            limit=page_size,
            offset=offset,
        )
        items = page.get("items", [])
        for item in items:
            media = item.get("track") or item.get("episode")
            if not media:
                continue
            rows.append(_flatten_queue_item(media, "track"))
            if len(rows) >= limit:
                break
        if not page.get("next") or not items:
            break
        offset += len(items)
    return rows


def find_playlist_ids_by_name(
    sp: spotipy.Spotify,
    playlist_name: str,
    limit: int = 10,
) -> list[str]:
    hint = re.sub(r"[^a-z0-9]", "", playlist_name.casefold())
    if not hint:
        return []

    matches: list[str] = []
    page = sp.current_user_playlists(limit=50)
    while page and len(matches) < limit:
        for playlist in page.get("items", []):
            name = re.sub(r"[^a-z0-9]", "", str(playlist.get("name", "")).casefold())
            if hint in name or name in hint:
                playlist_id = str(playlist.get("id", ""))
                if playlist_id:
                    matches.append(playlist_id)
                    if len(matches) >= limit:
                        break
        page = sp.next(page) if page.get("next") and len(matches) < limit else None
    return matches


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _spotify_id_from_href(value: object) -> str:
    match = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]+)", str(value or ""))
    return match.group(1) if match else ""


def _kod_from_tempo(value: object) -> int | float | str:
    try:
        from tempo_store import kod_from_bpm
        half_tempo = kod_from_bpm(value)
    except (TypeError, ValueError):
        return ""
    import math
    if not math.isfinite(half_tempo) or half_tempo <= 0:
        return ""
    rounded = round(half_tempo, 1)
    return int(rounded) if rounded.is_integer() else rounded


def _normalized_song_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = text.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _existing_kod_lookup() -> tuple[dict[tuple[str, str], object], dict[str, object]]:
    source = SPARETIME_DIR / "Playlists" / "LargeList.xlsx"
    if not source.exists():
        return {}, {}
    try:
        frame = pd.read_excel(source, engine="openpyxl")
    except (OSError, ValueError):
        return {}, {}
    if not {"Track Name", "Artist(s)", "KOD"}.issubset(frame.columns):
        return {}, {}

    exact: dict[tuple[str, str], object] = {}
    title_values: dict[str, set[object]] = {}
    for _, row in frame.iterrows():
        kod = pd.to_numeric(pd.Series([row.get("KOD")]), errors="coerce").iloc[0]
        if pd.isna(kod):
            continue
        value: object = int(kod) if float(kod).is_integer() else round(float(kod), 1)
        title = _normalized_song_text(row.get("Track Name"))
        artist = _normalized_song_text(row.get("Artist(s)"))
        if not title:
            continue
        exact.setdefault((title, artist), value)
        title_values.setdefault(title, set()).add(value)
    unique_titles = {
        title: next(iter(values))
        for title, values in title_values.items()
        if len(values) == 1
    }
    return exact, unique_titles


def _spotify_tempos(sp: spotipy.Spotify, track_ids: list[str], progress=None) -> dict[str, object]:
    tempos: dict[str, object] = {}
    for index, batch in enumerate(_chunks(track_ids, 100)):
        if progress:
            progress("Spotify tempo batches", index, (len(track_ids) + 99) // 100, f"{len(track_ids)} songs to check")
        try:
            features = sp.audio_features(batch)
        except SpotifyException as exc:
            if getattr(exc, "http_status", None) in {403, 404}:
                break
            continue
        for track_id, feature in zip(batch, features or []):
            if feature and feature.get("tempo") is not None:
                tempos[track_id] = feature["tempo"]
    return tempos


def _reccobeats_tempos(track_ids: list[str], progress=None) -> dict[str, object]:
    tempos: dict[str, object] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": "SpareTimeStudio/1.0"})
    for index, batch in enumerate(_chunks(track_ids, 40)):
        if progress:
            progress("ReccoBeats tempo batches", index, (len(track_ids) + 39) // 40, f"{len(track_ids)} songs to check")
        response = None
        for attempt in range(2):
            try:
                response = session.get(
                    "https://api.reccobeats.com/v1/audio-features",
                    params=[("ids", track_id) for track_id in batch],
                    timeout=20,
                )
            except requests.RequestException:
                response = None
                break
            if response.status_code != 429 or attempt:
                break
            delay = min(float(response.headers.get("Retry-After", "1") or 1), 5.0)
            time.sleep(max(delay, 0.2))
        if response is None or not response.ok:
            continue
        try:
            content = response.json().get("content", [])
        except (AttributeError, ValueError):
            continue
        for feature in content:
            track_id = _spotify_id_from_href(feature.get("href"))
            if track_id and feature.get("tempo") is not None:
                tempos[track_id] = feature["tempo"]
    return tempos


def _reccobeats_search_tempos(
    tracks: dict[str, tuple[str, str]],
    progress=None,
) -> dict[str, object]:
    if not tracks:
        return {}
    session = requests.Session()
    session.headers.update({"User-Agent": "SpareTimeStudio/1.0"})
    spotify_by_recco: dict[str, str] = {}

    for index, (spotify_id, (title, artists)) in enumerate(tracks.items()):
        if progress:
            progress("Searching missing tempos", index, len(tracks), str(title))
        primary_artist = str(artists).split(",", 1)[0].strip()
        params: dict[str, object] = {
            "searchText": title,
            "size": 5,
        }
        if len(primary_artist) >= 3:
            params["artist"] = primary_artist
        response = None
        for attempt in range(2):
            try:
                response = session.get(
                    "https://api.reccobeats.com/v1/track/search",
                    params=params,
                    timeout=15,
                )
            except requests.RequestException:
                response = None
                break
            if response.status_code != 429 or attempt:
                break
            delay = min(float(response.headers.get("Retry-After", "1") or 1), 10.0)
            time.sleep(max(delay, 0.2))
        if response is None or not response.ok:
            continue
        try:
            candidates = response.json().get("content", [])
        except (AttributeError, ValueError):
            continue
        normalized_title = _normalized_song_text(title)
        normalized_artist = _normalized_song_text(primary_artist)
        for candidate in candidates:
            if _normalized_song_text(candidate.get("trackTitle")) != normalized_title:
                continue
            candidate_artists = {
                _normalized_song_text(artist.get("name"))
                for artist in candidate.get("artists", [])
            }
            if normalized_artist and normalized_artist not in candidate_artists:
                continue
            recco_id = str(candidate.get("id", ""))
            if recco_id:
                spotify_by_recco[recco_id] = spotify_id
                break

    tempos: dict[str, object] = {}
    recco_ids = list(spotify_by_recco)
    for index, batch in enumerate(_chunks(recco_ids, 40)):
        if progress:
            progress("Loading matched tempos", index, (len(recco_ids) + 39) // 40, f"{len(recco_ids)} matches")
        try:
            response = session.get(
                "https://api.reccobeats.com/v1/audio-features",
                params=[("ids", track_id) for track_id in batch],
                timeout=20,
            )
        except requests.RequestException:
            continue
        if not response.ok:
            continue
        try:
            content = response.json().get("content", [])
        except (AttributeError, ValueError):
            continue
        for feature in content:
            spotify_id = spotify_by_recco.get(str(feature.get("id", "")))
            if spotify_id and feature.get("tempo") is not None:
                tempos[spotify_id] = feature["tempo"]
    return tempos


def _load_kod_cache() -> dict[str, object]:
    try:
        loaded = json.loads(KOD_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save_kod_cache(cache: dict[str, object]) -> None:
    try:
        KOD_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        KOD_CACHE_PATH.write_text(
            json.dumps(cache, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        pass


def build_tagged_playlist_table(
    settings: SpotifySettings,
    style_prefix: str = "Stil:",
    theme_prefix: str = "Tema:",
    event_prefix: str = "Event:",
    progress=None,
    apply_corrections=True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    report = progress or (lambda *args: None)
    report("Finding playlists", 0, 0, "")
    sp = build_spotify_client(settings)
    playlists: list[dict[str, object]] = []
    page = sp.current_user_playlists(limit=50)
    while page:
        playlists.extend(page.get("items", []))
        report("Finding playlists", len(playlists), int(page.get("total") or 0), f"{len(playlists)} playlists found")
        page = sp.next(page) if page.get("next") else None

    style_key = style_prefix.casefold()
    theme_key = theme_prefix.casefold()
    event_key = event_prefix.casefold()
    tagged_playlists = [
        playlist
        for playlist in playlists
        if str(playlist.get("name", "")).strip().casefold().startswith((style_key, theme_key, event_key))
    ]
    records: dict[str, dict[str, object]] = {}

    for playlist_index, playlist in enumerate(tagged_playlists):
        playlist_name = str(playlist.get("name", "")).strip()
        report("Reading tagged playlists", playlist_index, len(tagged_playlists), playlist_name)
        playlist_id = str(playlist.get("id", "")).strip()
        if not playlist_id:
            continue
        tag_column = next(
            column for prefix, column in ((style_key, "Style"), (theme_key, "Theme"), (event_key, "Event"))
            if playlist_name.casefold().startswith(prefix)
        )
        tag = playlist_name.split(":", 1)[1].strip() if ":" in playlist_name else playlist_name
        offset = 0

        while True:
            response = sp.playlist_items(
                playlist_id,
                additional_types=["track"],
                limit=100,
                offset=offset,
            )
            items = response.get("items", [])
            for item in items:
                track = item.get("track")
                if not track or str(track.get("type", "track")) != "track":
                    continue
                name = str(track.get("name", "")).strip()
                artists = _format_artists(track.get("artists", []))
                uri = str(track.get("uri", "")).strip()
                key = uri or f"{name.casefold()}|{artists.casefold()}"
                if not key:
                    continue
                album = track.get("album") or {}
                record = records.setdefault(
                    key,
                    {
                        "Playlist": set(),
                        "Track Name": name,
                        "Artist(s)": artists,
                        "Album": str(album.get("name", "")),
                        "KOD": "",
                        "API BPM": "",
                        "Tempo source": "",
                        "Style": set(),
                        "Theme": set(),
                        "Event": set(),
                        "Spotify URI": uri,
                    },
                )
                record["Playlist"].add(playlist_name)
                record[tag_column].add(tag or playlist_name)
            report("Reading tagged playlists", playlist_index, len(tagged_playlists),
                   f"{playlist_name}: {offset + len(items)} tracks read; {len(records)} unique songs")
            if not response.get("next") or not items:
                break
            offset += len(items)
        report("Reading tagged playlists", playlist_index + 1, len(tagged_playlists), f"{len(records)} unique songs")

    rows: list[dict[str, object]] = []
    for record in records.values():
        rows.append(
            {
                **record,
                "Playlist": "; ".join(sorted(record["Playlist"], key=str.casefold)),
                "Style": "; ".join(sorted(record["Style"], key=str.casefold)),
                "Theme": "; ".join(sorted(record["Theme"], key=str.casefold)),
                "Event": "; ".join(sorted(record["Event"], key=str.casefold)),
            }
        )

    report("Matching local tempos", 0, 0, f"{len(rows)} songs")
    exact_kod, title_kod = _existing_kod_lookup()
    existing_kod_count = 0
    for row in rows:
        title = _normalized_song_text(row.get("Track Name"))
        artist = _normalized_song_text(row.get("Artist(s)"))
        kod = exact_kod.get((title, artist), title_kod.get(title, ""))
        if kod != "":
            row["KOD"] = kod
            row["Tempo source"] = "Local list"
            existing_kod_count += 1

    id_to_row = {
        extract_spotify_id(str(row["Spotify URI"]), expected_kind="track"): row
        for row in rows
        if row.get("Spotify URI")
    }
    kod_cache = _load_kod_cache()
    cached_kod_count = 0
    for track_id, row in id_to_row.items():
        if row["KOD"] == "" and track_id in kod_cache:
            row["KOD"] = kod_cache[track_id]
            row["Tempo source"] = "Tempo cache (raw BPM unavailable)"
            cached_kod_count += 1

    missing_ids = [track_id for track_id, row in id_to_row.items() if row["KOD"] == ""]
    spotify_tempos = _spotify_tempos(sp, missing_ids, progress=report)
    remaining_ids = [track_id for track_id in missing_ids if track_id not in spotify_tempos]
    reccobeats_tempos = _reccobeats_tempos(remaining_ids, progress=report)
    search_ids = [
        track_id
        for track_id in remaining_ids
        if track_id not in reccobeats_tempos
    ]
    searched_tempos = _reccobeats_search_tempos(
        {
            track_id: (
                str(id_to_row[track_id]["Track Name"]),
                str(id_to_row[track_id]["Artist(s)"]),
            )
            for track_id in search_ids
        }, progress=report
    )
    api_kod_count = 0
    for track_id, tempo in {
        **searched_tempos,
        **reccobeats_tempos,
        **spotify_tempos,
    }.items():
        kod = _kod_from_tempo(tempo)
        if kod != "" and track_id in id_to_row:
            id_to_row[track_id]["KOD"] = kod
            id_to_row[track_id]["API BPM"] = tempo
            id_to_row[track_id]["Tempo source"] = "Spotify" if track_id in spotify_tempos else "ReccoBeats"
            kod_cache[track_id] = kod
            api_kod_count += 1
    if api_kod_count:
        _save_kod_cache(kod_cache)

    frame = pd.DataFrame(
        rows,
        columns=[
            "Playlist",
            "Track Name",
            "Artist(s)",
            "Album",
            "KOD",
            "API BPM",
            "Tempo source",
            "Style",
            "Theme",
            "Event",
            "Spotify URI",
        ],
    )
    import tempo_store
    if apply_corrections:
        frame = tempo_store.apply(frame)
    if not frame.empty:
        frame = frame.sort_values(
            ["Track Name", "Artist(s)"],
            kind="stable",
            key=lambda values: values.astype(str).str.casefold(),
        ).reset_index(drop=True)
    summary = {
        "playlists": len(tagged_playlists),
        "style_playlists": sum(
            str(item.get("name", "")).strip().casefold().startswith(style_key)
            for item in tagged_playlists
        ),
        "theme_playlists": sum(
            str(item.get("name", "")).strip().casefold().startswith(theme_key)
            for item in tagged_playlists
        ),
        "event_playlists": sum(
            str(item.get("name", "")).strip().casefold().startswith(event_key)
            for item in tagged_playlists
        ),
        "tracks": len(frame),
        "kod_tracks": existing_kod_count + cached_kod_count + api_kod_count,
        "kod_existing": existing_kod_count,
        "kod_api": cached_kod_count + api_kod_count,
    }
    return frame, summary


def queue_named_track(
    settings: SpotifySettings,
    track_name: str,
    artist_name: str = "",
    explicit_reference: str = "",
    playlist_hint: str = "",
) -> dict[str, str]:
    if not track_name.strip() and not explicit_reference.strip():
        raise ValueError("The selected row does not contain a track name or Spotify URI.")

    sp = build_spotify_client(settings)
    matched_uri = ""
    matched_name = track_name.strip()
    source = "explicit URI"

    if explicit_reference.strip():
        matched_uri = normalize_spotify_uri(explicit_reference, expected_kind="track")
    else:
        hinted_ids = find_playlist_ids_by_name(sp, playlist_hint) if playlist_hint else []
        playlist_ids = list(dict.fromkeys([*hinted_ids, *settings.playlist_ids]))
    if not matched_uri and playlist_ids:
        uri, name = find_in_playlists(
            sp,
            track_name,
            playlist_ids,
            artist_name,
        )
        matched_uri = uri or ""
        matched_name = name or matched_name
        source = "Spotify playlist"

    if not matched_uri:
        query = f'track:"{track_name.strip()}"'
        if artist_name.strip():
            query += f' artist:"{artist_name.strip()}"'
        response = sp.search(q=query, type="track", limit=5)
        items = response.get("tracks", {}).get("items", [])
        if not items:
            raise ValueError(f"No Spotify match was found for '{track_name}'.")
        matched_uri = str(items[0].get("uri", ""))
        matched_name = str(items[0].get("name", track_name))
        source = "Spotify catalog"

    sp.add_to_queue(matched_uri, device_id=playback_device(sp, settings))
    return {
        "track_name": matched_name,
        "track_uri": matched_uri,
        "artist": artist_name,
        "source": source,
    }


def play_track_from_playlists(settings: SpotifySettings, track_name: str) -> dict[str, str]:
    if not track_name.strip():
        raise ValueError("Enter a track name before starting playback.")

    sp = build_spotify_client(settings)
    matched_uri = None
    matched_name = None

    if settings.playlist_ids:
        matched_uri, matched_name = find_in_playlists(sp, track_name, settings.playlist_ids)

    if not matched_uri:
        if not settings.fallback_to_global:
            raise ValueError("No matching track was found in the configured playlists.")
        search = sp.search(q=f"track:{track_name}", type="track", limit=1)
        items = search.get("tracks", {}).get("items", [])
        if not items:
            raise ValueError(f"No track found for '{track_name}'.")
        matched_uri = str(items[0]["uri"])
        matched_name = str(items[0]["name"])

    sp.start_playback(device_id=playback_device(sp, settings), uris=[matched_uri])
    return {
        "track_name": matched_name or track_name,
        "track_uri": matched_uri,
    }


def play_reference(settings: SpotifySettings, reference: str, fallback_uri: str = "") -> dict[str, str]:
    sp = build_spotify_client(settings)

    if not reference.strip():
        device_id = playback_device(sp, settings)
        try:
            sp.start_playback(device_id=device_id)
            return {"uri": ""}
        except SpotifyException as exc:
            if exc.http_status != 404:
                raise
        # A discovered device may have no resumable playback session.
        # Prefer Spotify's actual upcoming song, then the locally saved plan.
        try:
            queued = (sp.queue() or {}).get("queue", [])
            first = next((item.get("uri", "") for item in queued if item.get("uri")), "")
        except SpotifyException as exc:
            if exc.http_status != 404:
                raise
            first = ""
        first = first or fallback_uri
        sp.transfer_playback(device_id=device_id, force_play=False)
        time.sleep(0.5)
        if first:
            first = normalize_spotify_uri(first)
            sp.start_playback(device_id=device_id, uris=[first])
        else:
            sp.start_playback(device_id=device_id)
        return {"uri": first}

    uri = normalize_spotify_uri(reference)

    if uri.startswith("spotify:track:") or uri.startswith("spotify:episode:"):
        sp.start_playback(device_id=playback_device(sp, settings), uris=[uri])
    else:
        sp.start_playback(device_id=playback_device(sp, settings), context_uri=uri)
    return {"uri": uri}


def add_to_queue(settings: SpotifySettings, reference: str) -> dict[str, str]:
    uri = normalize_spotify_uri(reference)
    sp = build_spotify_client(settings)
    sp.add_to_queue(uri, device_id=playback_device(sp, settings))
    return {"uri": uri}


def pause_playback(settings: SpotifySettings) -> None:
    sp = build_spotify_client(settings)
    sp.pause_playback(device_id=playback_device(sp, settings))


def next_track(settings: SpotifySettings) -> None:
    sp = build_spotify_client(settings)
    sp.next_track(device_id=playback_device(sp, settings))


def fade_skip(settings: SpotifySettings, duration: float = 5.0) -> None:
    """Fade the active device, skip once, and restore its original volume."""
    _fade_playback(settings, "skip", duration)


def fade_pause(settings: SpotifySettings, duration: float = 5.0) -> None:
    """Fade the active device, pause, and restore volume for later resuming."""
    _fade_playback(settings, "pause", duration)


def _fade_playback(settings: SpotifySettings, action: str, duration: float) -> None:
    sp = build_spotify_client(settings)
    state = sp.current_playback() or {}
    device = state.get("device") or {}
    if not state.get("is_playing") or not device.get("id"):
        raise ValueError("Start a song in Spotify before using the fade controls.")
    original = device.get("volume_percent")
    if original is None or device.get("supports_volume") is False or device.get("is_restricted"):
        raise ValueError("This Spotify device does not support volume control. Select another device.")
    device_id = str(device["id"])
    original = int(original)
    started = time.monotonic()
    failure = None
    try:
        for step in range(1, 11):
            deadline = started + duration * step / 10
            time.sleep(max(0, deadline - time.monotonic()))
            sp.volume(round(original * (1 - step / 10)), device_id=device_id)
        if action == "pause":
            sp.pause_playback(device_id=device_id)
        else:
            sp.next_track(device_id=device_id)
    except Exception as exc:
        failure = exc
    finally:
        try:
            sp.volume(original, device_id=device_id)
        except Exception as restore_error:
            detail = f"Could not restore Spotify volume to {original}%. Adjust it in Spotify. {explain_spotify_error(restore_error)}"
            if failure is not None:
                detail = f"{explain_spotify_error(failure)} {detail}"
            raise RuntimeError(detail) from restore_error
    if failure is not None:
        raise failure


def previous_track(settings: SpotifySettings) -> None:
    sp = build_spotify_client(settings)
    sp.previous_track(device_id=playback_device(sp, settings))


def seek_playback(settings: SpotifySettings, position_ms: int) -> None:
    sp = build_spotify_client(settings)
    sp.seek_track(position_ms=position_ms, device_id=playback_device(sp, settings))


def set_volume(settings: SpotifySettings, volume_percent: int) -> None:
    sp = build_spotify_client(settings)
    sp.volume(max(0, min(volume_percent, 100)), device_id=playback_device(sp, settings))


def set_shuffle(settings: SpotifySettings, enabled: bool) -> None:
    sp = build_spotify_client(settings)
    sp.shuffle(enabled, device_id=playback_device(sp, settings))


def set_repeat(settings: SpotifySettings, mode: str) -> None:
    sp = build_spotify_client(settings)
    sp.repeat(mode, device_id=playback_device(sp, settings))


def transfer_playback(settings: SpotifySettings, device_id: str, force_play: bool = True) -> None:
    if not device_id.strip():
        raise ValueError("A device ID is required to transfer playback.")
    build_spotify_client(settings).transfer_playback(device_id=device_id.strip(), force_play=force_play)


def list_current_user_playlists(settings: SpotifySettings, limit: int = 50) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    rows: list[dict[str, str]] = []
    offset = 0
    page_size = max(1, min(limit, 50))
    while True:
        response = sp.current_user_playlists(limit=page_size, offset=offset)
        items = response.get("items", [])
        for playlist in items:
            rows.append(_flatten_playlist(playlist))
        if not response.get("next"):
            break
        offset += page_size
    return rows


def create_playlist(
    settings: SpotifySettings,
    name: str,
    description: str = "",
    public: bool = False,
) -> dict[str, str]:
    if not name.strip():
        raise ValueError("Playlist name is required.")
    sp = build_spotify_client(settings)
    playlist = sp._post("me/playlists", payload={
        "name": name.strip(), "public": public,
        "description": description.strip(),
    })
    return {
        "name": str(playlist.get("name", "")),
        "id": str(playlist.get("id", "")),
        "uri": str(playlist.get("uri", "")),
    }


def add_items_to_playlist(
    settings: SpotifySettings,
    playlist_reference: str,
    item_references: list[str],
) -> dict[str, str]:
    if not item_references:
        raise ValueError("At least one Spotify URI is required.")
    playlist_id = extract_spotify_id(playlist_reference, expected_kind="playlist")
    uris = [normalize_spotify_uri(item) for item in item_references]
    sp = build_spotify_client(settings)
    snapshot_id = None
    for offset in range(0, len(uris), 100):
        snapshot_id = sp._post(f"playlists/{playlist_id}/items", payload={"uris": uris[offset:offset+100]})
    return {"playlist_id": playlist_id, "snapshot_id": str(snapshot_id)}


def list_saved_tracks(settings: SpotifySettings, limit: int = 50) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    response = sp.current_user_saved_tracks(limit=max(1, min(limit, 50)))
    return [_flatten_track(item.get("track") or {}) for item in response.get("items", [])]


def list_recent_tracks(settings: SpotifySettings, limit: int = 50) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    response = sp.current_user_recently_played(limit=max(1, min(limit, 50)))
    return [{**_flatten_track(item.get("track") or {}), "played_at": str(item.get("played_at", ""))}
            for item in response.get("items", [])]


def list_top_tracks(
    settings: SpotifySettings,
    limit: int = 20,
    time_range: str = "medium_term",
) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    response = sp.current_user_top_tracks(limit=max(1, min(limit, 50)), time_range=time_range)
    return [_flatten_track(item) for item in response.get("items", [])]


def list_top_artists(
    settings: SpotifySettings,
    limit: int = 20,
    time_range: str = "medium_term",
) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    response = sp.current_user_top_artists(limit=max(1, min(limit, 50)), time_range=time_range)
    return [_flatten_artist(item) for item in response.get("items", [])]


def save_items_to_library(settings: SpotifySettings, references: list[str]) -> dict[str, str]:
    if not references:
        raise ValueError("At least one Spotify URI is required.")
    uris = [normalize_spotify_uri(reference) for reference in references]
    sp = build_spotify_client(settings)
    sp._put("me/library", args={"uris": ",".join(uris)})
    return {"count": str(len(uris))}


def remove_items_from_library(settings: SpotifySettings, references: list[str]) -> dict[str, str]:
    if not references:
        raise ValueError("At least one Spotify URI is required.")
    uris = [normalize_spotify_uri(reference) for reference in references]
    sp = build_spotify_client(settings)
    sp._delete("me/library", args={"uris": ",".join(uris)})
    return {"count": str(len(uris))}


def check_items_in_library(settings: SpotifySettings, references: list[str]) -> list[dict[str, str]]:
    if not references:
        raise ValueError("At least one Spotify URI is required.")
    uris = [normalize_spotify_uri(reference) for reference in references]
    sp = build_spotify_client(settings)
    states = sp._get("me/library/contains", args={"uris": ",".join(uris)})
    rows: list[dict[str, str]] = []
    for uri, saved in zip(uris, states):
        rows.append(
            {
                "type": "library",
                "name": uri,
                "subtitle": "Saved" if saved else "Not saved",
                "uri": uri,
                "id": uri.split(":")[-1],
                "extra": "",
                "external_url": "",
            }
        )
    return rows


def get_audio_features(settings: SpotifySettings, reference: str) -> dict[str, object]:
    track_id = extract_spotify_id(reference, expected_kind="track")
    sp = build_spotify_client(settings)
    response = sp.audio_features([track_id])
    if not response or not response[0]:
        raise ValueError("No audio features were returned for this track.")
    return response[0]


def get_audio_analysis(settings: SpotifySettings, reference: str) -> dict[str, object]:
    track_id = extract_spotify_id(reference, expected_kind="track")
    return build_spotify_client(settings).audio_analysis(track_id)


def get_recommendations(
    settings: SpotifySettings,
    seed_tracks: list[str] | None = None,
    seed_artists: list[str] | None = None,
    seed_genres: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, str]]:
    sp = build_spotify_client(settings)
    response = sp.recommendations(
        seed_tracks=[extract_spotify_id(item, expected_kind="track") for item in (seed_tracks or [])] or None,
        seed_artists=[extract_spotify_id(item, expected_kind="artist") for item in (seed_artists or [])] or None,
        seed_genres=[item.strip() for item in (seed_genres or []) if item.strip()] or None,
        limit=max(1, min(limit, 50)),
    )
    return [_flatten_track(track) for track in response.get("tracks", [])]


def get_related_artists(settings: SpotifySettings, reference: str) -> list[dict[str, str]]:
    artist_id = extract_spotify_id(reference, expected_kind="artist")
    response = build_spotify_client(settings).artist_related_artists(artist_id)
    return [_flatten_artist(artist) for artist in response.get("artists", [])]


def get_artist_top_tracks(settings: SpotifySettings, reference: str) -> list[dict[str, str]]:
    artist_id = extract_spotify_id(reference, expected_kind="artist")
    response = build_spotify_client(settings).artist_top_tracks(artist_id)
    return [_flatten_track(track) for track in response.get("tracks", [])]


def ms_to_min_sec(milliseconds: int | None) -> str:
    if milliseconds is None:
        return ""
    seconds = milliseconds // 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


def export_playlist_to_file(
    settings: SpotifySettings,
    playlist_reference: str,
    output_path: str | Path,
    *,
    csv_delimiter: str = ",",
    text_encoding: str = "utf-8-sig",
) -> dict[str, str]:
    if not playlist_reference.strip():
        raise ValueError("Enter a Spotify playlist URL, URI, or ID first.")

    playlist_id = extract_spotify_id(playlist_reference, expected_kind="playlist")
    sp = build_spotify_client(settings)
    metadata = sp.playlist(playlist_id, fields="name,owner(display_name)")
    playlist_name = str(metadata.get("name", "Spotify Playlist"))

    all_items: list[dict[str, object]] = []
    limit = 100
    offset = 0
    while True:
        page = sp.playlist_items(playlist_id, additional_types=["track"], limit=limit, offset=offset)
        all_items.extend(page.get("items", []))
        if page.get("next"):
            offset += limit
        else:
            break

    rows = []
    for item in all_items:
        track = item.get("track") or {}
        album = track.get("album") or {}
        rows.append(
            {
                "Track Name": track.get("name", ""),
                "Artist(s)": _format_artists(track.get("artists", [])),
                "KOD": "",
                "Style": "",
                "Challenge": "",
                "Sure?": "",
                "Played?": "",
                "Duration": ms_to_min_sec(track.get("duration_ms")),
                "Album": album.get("name", ""),
                "Release": album.get("release_date", ""),
                "Count": "1",
            }
        )

    df = pd.DataFrame(rows)
    output_file = Path(output_path)
    write_table_file(
        df,
        output_file,
        csv_delimiter=csv_delimiter,
        text_encoding=text_encoding,
        sheet_name="Tracks",
    )

    return {
        "playlist_name": playlist_name,
        "owner": str((metadata.get("owner") or {}).get("display_name", "")),
        "track_count": str(len(df)),
        "output_path": str(output_file),
        "format": output_file.suffix.casefold().removeprefix(".").upper(),
    }


def export_playlist_to_excel(
    settings: SpotifySettings,
    playlist_reference: str,
    output_path: str | Path,
) -> dict[str, str]:
    return export_playlist_to_file(settings, playlist_reference, output_path)


def export_listening_playlist(settings, name, uris):
    if not name.strip():
        raise ValueError("Enter a playlist name.")
    if not uris or any(not uri.startswith("spotify:track:") for uri in uris):
        raise ValueError("Every song needs a Spotify track URI. Import a Spotify list first.")
    sp = build_spotify_client(settings)
    playlist = sp._post("me/playlists", payload={"name": name.strip(), "public": False,
                        "description": "Listening history or queue from SpareTime Studio"})
    playlist_id = playlist["id"]
    try:
        for offset in range(0, len(uris), 100):
            sp._post(f"playlists/{playlist_id}/items", payload={"uris": uris[offset:offset+100]})
    except Exception as exc:
        raise RuntimeError(f"Playlist {name} ({playlist_id}) was created, but adding songs failed; it may be incomplete. {exc}") from exc
    return playlist


def _playlist_track_uris(sp, playlist_id):
    uris = set()
    offset = 0
    while True:
        response = sp.playlist_items(playlist_id, additional_types=["track"], limit=100, offset=offset) or {}
        items = response.get("items") or []
        for item in items:
            track = (item or {}).get("track") or (item or {}).get("item") or {}
            if track.get("uri"):
                uris.add(track["uri"])
        if not response.get("next"):
            return uris
        if not items:
            raise ValueError("Spotify returned an empty playlist page with more pages pending. Preview again before adding songs.")
        offset += len(items)


def preview_tag_playlist_additions(settings, changes):
    """Plan additions to existing exact Stil:/Tema: playlists; never modify them."""
    sp = build_spotify_client(settings)
    user_id = (sp.current_user() or {}).get("id")
    playlists = []
    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset) or {}
        items = page.get("items") or []
        playlists.extend(item for item in items if isinstance(item, dict))
        if not page.get("next"):
            break
        if not items:
            raise ValueError("Spotify returned incomplete playlist discovery. Preview again.")
        offset += len(items)
    matches = {}
    for playlist in playlists:
        name = str(playlist.get("name", "")).strip()
        for column, prefix in (("Style", "stil:"), ("Theme", "tema:")):
            if name.casefold().startswith(prefix):
                tag = name.split(":", 1)[1].strip().casefold()
                matches.setdefault((column, tag), []).append(playlist)
    requested = {}
    issues = []
    for change in changes:
        key = (change["column"], change["tag"].casefold())
        requested.setdefault(key, {"tag": change["tag"], "uris": set(), "names": {}})
        requested[key]["uris"].add(change["uri"])
        requested[key]["names"][change["uri"]] = change["name"]
    plans = []
    already_present = 0
    for (column, tag), request in sorted(requested.items()):
        candidates = matches.get((column, tag), [])
        prefix = "Stil:" if column == "Style" else "Tema:"
        label = f"{prefix} {request['tag']}"
        if len(candidates) != 1:
            issues.append(f"{label}: {'no matching playlist' if not candidates else 'multiple playlists have this name'}")
            continue
        playlist = candidates[0]
        playlist_id = playlist.get("id")
        owner = (playlist.get("owner") or {}).get("id")
        if not playlist_id or not (owner == user_id and user_id or playlist.get("collaborative")):
            issues.append(f"{label}: this account does not own the playlist and it is not collaborative")
            continue
        try:
            existing = _playlist_track_uris(sp, playlist_id)
        except Exception as exc:
            issues.append(f"{label}: {explain_spotify_error(exc)}")
            continue
        missing = sorted(request["uris"] - existing)
        already_present += len(request["uris"] & existing)
        if missing:
            plans.append({"id": playlist_id, "name": playlist.get("name", label), "uris": missing,
                          "count": len(missing), "songs": [request["names"][uri] for uri in missing]})
    return {"playlists": plans, "count": sum(plan["count"] for plan in plans),
            "already_present": already_present, "issues": issues}


def add_previewed_tag_songs(settings, preview):
    """Recheck membership before writes, allowing safe retries after partial success."""
    sp = build_spotify_client(settings)
    added, skipped = 0, 0
    failures = []
    for plan in preview.get("playlists", []):
        try:
            existing = _playlist_track_uris(sp, plan["id"])
            missing = list(dict.fromkeys(uri for uri in plan["uris"] if uri not in existing))
            skipped += len(plan["uris"]) - len(missing)
            for batch in _chunks(missing, 100):
                sp._post(f"playlists/{plan['id']}/items", payload={"uris": batch})
                added += len(batch)
        except Exception as exc:
            failures.append(f"{plan['name']}: {explain_spotify_error(exc)} Some additions may have succeeded; preview again before retrying.")
    return {"added": added, "skipped": skipped, "failures": failures}
