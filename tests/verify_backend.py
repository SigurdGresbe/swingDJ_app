from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from config import GENERATED_DIR, SPARETIME_DIR
from excel_tools import MergeOptions, merge_excel_into_master
from spotify_tools import (
    SpotifySettings,
    build_tagged_playlist_table,
    list_playlist_tracks,
    play_reference,
    queue_named_track,
    search_catalog,
)
from table_io import read_table_file
from table_model import SongTableModel


def verify_table_workflows(temp_dir: Path) -> None:
    source = SPARETIME_DIR / "Playlists" / "LargeList.xlsx"
    model = SongTableModel()
    frame = read_table_file(source, max_rows=500)
    model.set_frame(frame, str(source), ["Sheet1"])
    assert model.rowCount() > 100
    assert model.columnCount() >= 8
    assert model.styleColumn in model.allColumns

    difficulty_source = SPARETIME_DIR / "Playlists" / "Swing_Party_W_BPM.xlsx"
    difficulty_model = SongTableModel()
    difficulty_model.set_frame(
        read_table_file(difficulty_source, max_rows=50),
        str(difficulty_source),
        ["Sheet1"],
    )
    assert difficulty_model.difficultyColumn == "Challenge"

    original_rows = model.rowCount()
    model.setFilter("All columns", "Sinatra", False)
    assert 0 < model.rowCount() < original_rows
    model.clearFilter()
    model.setSort("KOD", True)
    model.setColumnVisible(model.allColumns[-1], False)
    assert model.columnCount() == len(model.allColumns) - 1
    model.showAllColumns()
    assert model.rowRecord(0).get("Track Name")

    tagged_model = SongTableModel()
    tagged_model.set_frame(
        pd.DataFrame(
            [
                {"Track Name": "One", "Style": "Blues; Swing", "Theme": "Party"},
                {"Track Name": "Two", "Style": "Lindy Hop", "Theme": "Winter"},
                {"Track Name": "Three", "Style": "Swing", "Theme": "Party; Social"},
            ]
        )
    )
    assert tagged_model.tagFiltersAvailable
    assert [item["name"] for item in tagged_model.styleTagStates] == [
        "Blues",
        "Lindy Hop",
        "Swing",
    ]
    tagged_model.setTagVisible("Style", "Blues", False)
    assert tagged_model.updating
    assert tagged_model.rowCount() == 3
    assert not next(tag for tag in tagged_model.styleTagStates if tag["name"] == "Blues")["visible"]
    from PySide6.QtTest import QTest
    QTest.qWait(150)
    assert not tagged_model.updating
    assert tagged_model.rowCount() == 2
    tagged_model.setTagVisible("Theme", "Party", False)
    QTest.qWait(150)
    assert tagged_model.rowCount() == 1
    assert tagged_model.hiddenTagCount == 2
    tagged_model.showAllTags("")
    assert tagged_model.hiddenTagCount == 0
    QTest.qWait(150)
    assert tagged_model.rowCount() == 3

    tagged_model.setIsolateTags(True)
    tagged_model.setTagVisible("Style", "Blues", True)
    QTest.qWait(150)
    assert tagged_model.rowCount() == 1
    tagged_model.setTagVisible("Style", "Swing", True)
    QTest.qWait(150)
    assert tagged_model.rowCount() == 2
    tagged_model.showAllTags("")
    QTest.qWait(150)
    assert tagged_model.rowCount() == 3

    range_model = SongTableModel()
    range_model.set_frame(pd.DataFrame([
        {"Track Name": "Low", "KOD": 40},
        {"Track Name": "Boundary", "KOD": 60},
        {"Track Name": "From BPM", "BPM": 140},
        {"Track Name": "High", "KOD": 90},
        {"Track Name": "Unknown"},
    ]))
    range_model.setKodRange(True, 60, 70)
    QTest.qWait(150)
    assert range_model.rowCount() == 2
    assert range_model.rowRecord(0)["Track Name"] == "Boundary"
    range_model.setKodRange(False, 60, 70)
    QTest.qWait(150)
    assert range_model.rowCount() == 5

    tagged_model.setColumnVisible("Theme", False)
    assert "Theme" not in tagged_model.visibleColumns
    assert tagged_model.rowRecord(0).get("Theme")

    for suffix in (".xlsx", ".csv", ".tsv", ".json", ".jsonl"):
        output = temp_dir / f"view{suffix}"
        model.export_view(str(output), ",", "utf-8-sig")
        exported = read_table_file(output, max_rows=10)
        assert not exported.empty


def verify_merge(temp_dir: Path) -> None:
    source = SPARETIME_DIR / "Playlists_UPDATED" / "Blindern_Rockeswing.xlsx"
    master = SPARETIME_DIR / "Playlists" / "LargeList.xlsx"
    output = temp_dir / "merged.xlsx"
    options = MergeOptions(
        key_columns=["Track Name", "Artist(s)"],
        update_mode="fill_blanks",
        preview_limit=10,
    )
    preview = merge_excel_into_master(source, master, output, options, preview_only=True)
    assert preview.rows_read_source > 0
    assert not output.exists()
    result = merge_excel_into_master(source, master, output, options, preview_only=False)
    assert output.exists()
    assert result.output_path == str(output)
    assert len(pd.read_excel(output)) >= result.rows_read_master


def verify_spotify_helpers() -> None:
    settings = SpotifySettings(
        "client",
        "secret",
        "http://localhost/callback",
        ["playlist-1"],
    )
    client = type("Client", (), {})()
    calls: list[dict[str, object]] = []

    def start_playback(**kwargs: object) -> None:
        calls.append(kwargs)

    client.start_playback = start_playback
    client.devices = lambda: {"devices": [{"id": "active", "is_active": True}]}
    queued: list[dict[str, object]] = []
    client.add_to_queue = lambda uri, **kwargs: queued.append({"uri": uri, **kwargs})
    client.playlist_items = lambda *args, **kwargs: {
        "items": [
            {
                "track": {
                    "name": "Playlist Match",
                    "id": "playlist-track",
                    "uri": "spotify:track:playlist-track",
                    "artists": [{"name": "Test Artist"}],
                    "external_urls": {"spotify": "https://open.spotify.com/track/playlist-track"},
                }
            }
        ],
        "next": None,
    }
    client.current_user_playlists = lambda *args, **kwargs: {
        "items": [
            {"name": "Stil: Blues", "id": "style-playlist"},
            {"name": "Tema: Party", "id": "theme-playlist"},
            {"name": " event: Wedding", "id": "event-playlist"},
        ],
        "next": None,
    }
    client.search = lambda **kwargs: {
        "tracks": {
            "items": [
                {
                    "name": "Test Song",
                    "id": "1",
                    "uri": "spotify:track:1",
                    "artists": [{"name": "Test Artist"}],
                    "album": {"name": "Test Album"},
                    "external_urls": {"spotify": "https://open.spotify.com/track/1"},
                }
            ]
        }
    }
    client.audio_features = lambda track_ids: [None for _ in track_ids]
    with (
        patch("spotify_tools.build_spotify_client", return_value=client),
        patch("spotify_tools._load_kod_cache", return_value={}),
        patch("spotify_tools._reccobeats_tempos", return_value={}),
        patch("spotify_tools._reccobeats_search_tempos", return_value={}),
    ):
        play_reference(settings, "")
        rows = search_catalog(settings, "test", ["track"], 5)
        playlist_rows = list_playlist_tracks(settings, "spotify:playlist:playlist-1")
        queued_result = queue_named_track(settings, "Playlist Match", "Test Artist")
        progress_events = []
        tagged, tagged_summary = build_tagged_playlist_table(settings, progress=lambda *event: progress_events.append(event))
        assert any(event[0] == "Reading tagged playlists" and event[1:3] == (3, 3) for event in progress_events)
    assert calls == [{"device_id": "active"}]
    assert rows[0]["name"] == "Test Song"
    assert playlist_rows[0]["name"] == "Playlist Match"
    assert queued_result["source"] == "Spotify playlist"
    assert queued[0]["uri"] == "spotify:track:playlist-track"
    assert tagged.iloc[0]["Style"] == "Blues"
    assert tagged.iloc[0]["Theme"] == "Party"
    assert tagged.iloc[0]["Event"] == "Wedding"
    assert "KOD" in tagged.columns
    assert "Spotify URL" not in tagged.columns
    assert tagged_summary == {
        "playlists": 3,
        "style_playlists": 1,
        "theme_playlists": 1,
        "event_playlists": 1,
        "tracks": 1,
        "kod_tracks": 0,
        "kod_existing": 0,
        "kod_api": 0,
    }


def main() -> int:
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=GENERATED_DIR) as temp:
        temp_dir = Path(temp)
        verify_table_workflows(temp_dir)
        verify_merge(temp_dir)
        verify_spotify_helpers()
    print("BACKEND_OK table_exports=5 merge=preview+write spotify=mocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
