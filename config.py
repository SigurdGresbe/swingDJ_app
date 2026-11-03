from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re


APP_DIR = Path(__file__).resolve().parent
SPARETIME_DIR = Path(r"C:\VS_code\SpareTime")
LOCAL_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(APP_DIR))) / "SpareTimeStudio"
GENERATED_DIR = LOCAL_DATA_DIR / "generated"
SETTINGS_PATH = LOCAL_DATA_DIR / "settings.json"


def _load_original_spotify_defaults() -> dict[str, str]:
    spotify_core = SPARETIME_DIR / "spotify_core.py"
    if not spotify_core.exists():
        return {}
    try:
        text = spotify_core.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    defaults: dict[str, str] = {}
    patterns = {
        "spotify_client_id": r'^CLIENT_ID\s*=\s*["\'](.*?)["\']',
        "spotify_client_secret": r'^CLIENT_SECRET\s*=\s*["\'](.*?)["\']',
        "spotify_redirect_uri": r'^REDIRECT_URI\s*=\s*["\'](.*?)["\']',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            defaults[key] = match.group(1).strip()

    playlist_match = re.search(
        r"PLAYLIST_IDS\s*=\s*(\[[\s\S]*?\])",
        text,
        re.MULTILINE,
    )
    if playlist_match:
        try:
            playlist_ids = ast.literal_eval(playlist_match.group(1))
        except (SyntaxError, ValueError):
            playlist_ids = []
        if isinstance(playlist_ids, list):
            defaults["spotify_playlist_ids"] = ", ".join(
                str(item) for item in playlist_ids
            )
    return defaults


ORIGINAL_SPOTIFY_DEFAULTS = _load_original_spotify_defaults()

DEFAULT_SETTINGS: dict[str, object] = {
    "theme": "Paper",
    "accent": "Terracotta",
    "window_width": 1480,
    "window_height": 920,
    "viewer_file": str(SPARETIME_DIR / "Playlists" / "LargeList.xlsx"),
    "viewer_sheet": "",
    "viewer_row_limit": 2000,
    "viewer_style_column": "Style",
    "viewer_difficulty_column": "Challenge",
    "viewer_hidden_columns": [],
    "viewer_filter_column": "All columns",
    "viewer_filter_text": "",
    "viewer_sort_column": "",
    "viewer_sort_ascending": True,
    "viewer_color_styles": True,
    "viewer_color_difficulty": True,
    "viewer_highlight_blanks": False,
    "viewer_hidden_styles": [],
    "viewer_hidden_themes": [],
    "viewer_density": "Comfortable",
    "output_folder": str(GENERATED_DIR),
    "output_format": "Excel workbook (.xlsx)",
    "csv_delimiter": "Comma (,)",
    "text_encoding": "UTF-8 with BOM",
    "merge_source_file": str(
        SPARETIME_DIR / "Playlists_UPDATED" / "Blindern_Rockeswing.xlsx"
    ),
    "merge_master_file": str(SPARETIME_DIR / "Playlists" / "LargeList.xlsx"),
    "merge_output_file": str(GENERATED_DIR / "LargeList_merged.xlsx"),
    "merge_key_columns": "Track Name, Artist(s)",
    "merge_update_mode": "fill_blanks",
    "batch_source_dir": str(SPARETIME_DIR / "Playlists_UPDATED"),
    "batch_template_file": str(SPARETIME_DIR / "Playlists" / "LargeList.xlsx"),
    "batch_output_file": str(GENERATED_DIR / "LargeList_built.xlsx"),
    "spotify_client_id": ORIGINAL_SPOTIFY_DEFAULTS.get(
        "spotify_client_id",
        os.getenv("SPOTIPY_CLIENT_ID", ""),
    ),
    "spotify_client_secret": ORIGINAL_SPOTIFY_DEFAULTS.get(
        "spotify_client_secret",
        os.getenv("SPOTIPY_CLIENT_SECRET", ""),
    ),
    "spotify_redirect_uri": ORIGINAL_SPOTIFY_DEFAULTS.get(
        "spotify_redirect_uri",
        os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8080/callback/"),
    ),
    "spotify_playlist_ids": ORIGINAL_SPOTIFY_DEFAULTS.get(
        "spotify_playlist_ids",
        "",
    ),
    "spotify_device_id": "",
    "spotify_export_output": str(GENERATED_DIR / "spotify_playlist.xlsx"),
    "lastfm_api_key": "",
}


def load_settings() -> dict[str, object]:
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}
        if isinstance(loaded, dict):
            settings.update(loaded)
    return settings


def save_settings(settings: dict[str, object]) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    temporary.replace(SETTINGS_PATH)
