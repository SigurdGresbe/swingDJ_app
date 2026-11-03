import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import requests
import spotipy
from spotipy.exceptions import SpotifyException
import error_reports
from spotify_tools import CurrentSpotifyClient, explain_spotify_error

client = CurrentSpotifyClient(auth="test")
with patch.object(spotipy.Spotify, "_get", return_value={"items": [{"item": {"uri": "spotify:track:abc"}}]}) as get:
    page = client.playlist_items("abc")
    assert get.call_args.args[0] == "playlists/abc/items"
    assert page["items"][0]["track"]["uri"] == "spotify:track:abc"
    client._get("https://api.spotify.com/v1/playlists/abc/tracks?offset=100")
    assert "/items?offset=100" in get.call_args.args[0]
assert "timed out" in explain_spotify_error(requests.exceptions.Timeout())
assert "Could not connect" in explain_spotify_error(requests.exceptions.ConnectionError())
assert "playback device" in explain_spotify_error(SpotifyException(404, -1, "No active device found"))
with TemporaryDirectory() as folder, patch.object(error_reports, "PATH", Path(folder)/"errors.jsonl"):
    error_reports.append("Refresh playlist", "404 access_token=private client_secret=secret Bearer hidden")
    error_reports.append("Search", "Connection timed out")
    reports = error_reports.read()
    assert len(reports) == 2 and reports[0]["action"] == "Refresh playlist"
    assert all(value not in reports[0]["message"] for value in ("private", "secret=secret", "hidden"))
    assert reports[0]["time"].endswith("+00:00")
print("ERRORS_OK current_endpoints response_normalization connection_messages persisted_redacted_reports")
