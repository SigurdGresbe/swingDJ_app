from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import tempo_store
import field_store
import error_reports
from PySide6.QtCore import (
    QObject,
    Property,
    QRunnable,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from config import DEFAULT_SETTINGS, GENERATED_DIR, SPARETIME_DIR, load_settings, save_settings
from excel_tools import MergeOptions, MergeSummary, build_master_from_folder, merge_excel_into_master
from lastfm_tools import fetch_similar_artists, fetch_similar_tracks
from spotify_tools import (
    SpotifySettings,
    preview_tag_playlist_additions,
    add_previewed_tag_songs,
    export_listening_playlist,
    fade_skip,
    fade_pause,
    explain_spotify_error,
    add_to_queue,
    authorize_user,
    build_tagged_playlist_table,
    check_items_in_library,
    export_playlist_to_file,
    get_currently_playing,
    get_playback_state,
    list_current_user_playlists,
    list_devices,
    list_playlist_tracks,
    list_queue,
    list_recent_tracks,
    list_saved_tracks,
    list_top_artists,
    list_top_tracks,
    next_track,
    parse_playlist_entries,
    pause_playback,
    play_reference,
    previous_track,
    queue_named_track,
    remove_items_from_library,
    run_capability_check,
    save_items_to_library,
    search_catalog,
    set_shuffle,
    set_volume,
    transfer_playback,
)
from table_io import (
    DELIMITER_VALUES,
    ENCODING_VALUES,
    FORMAT_SUFFIXES,
    TABLE_FILE_TYPES,
    delimiter_from_label,
    encoding_from_label,
    ensure_output_suffix,
    list_sheet_names,
    read_table_file,
    write_table_file,
)
from table_model import SongTableModel


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int, int, str)


class Worker(QRunnable):
    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.failed.emit(explain_spotify_error(exc))
        else:
            self.signals.succeeded.emit(result)


class AppController(QObject):
    statusChanged = Signal()
    busyChanged = Signal()
    updateProgressChanged = Signal()
    themeChanged = Signal()
    accentChanged = Signal()
    settingsChanged = Signal()
    mergeChanged = Signal()
    spotifyChanged = Signal()
    playbackChanged = Signal()
    activityChanged = Signal()
    listeningChanged = Signal()
    liveQueueChanged = Signal()
    bulkTempoChanged = Signal()
    tagSyncChanged = Signal()
    errorReportsChanged = Signal()
    toastRequested = Signal(str, str)
    navigateRequested = Signal(int)

    def __init__(self, table_model: SongTableModel) -> None:
        super().__init__()
        self.table_model = table_model
        self.settings = load_settings()
        self.table_model.restore_settings(self.settings)
        self.table_model.setDarkTheme(self.darkMode)
        self.table_model.updatingChanged.connect(self.busyChanged.emit)
        self.table_model.updatingChanged.connect(self.statusChanged.emit)
        self.thread_pool = QThreadPool.globalInstance()
        self.import_pool = QThreadPool(self)
        self.import_pool.setMaxThreadCount(1)
        self._workers: set[Worker] = set()
        self._status = "Ready"
        self._busy_count = 0
        self._tagged_update_running = False
        self._update_progress = {"stage": "", "completed": 0, "total": 0, "detail": ""}
        self._table_revision = 0
        self._bulk_tempo = {}
        self._bulk_undo = None
        self._tag_sync_preview = {}
        self._tag_sync_changes = []
        self.table_model.modelReset.connect(self._table_changed)
        self.table_model.dataChanged.connect(self._table_changed)
        self._merge_result: dict[str, object] = {}
        self._spotify_results: list[dict[str, object]] = []
        self._spotify_state: dict[str, object] = {}
        self._playback = {}
        self._playback_pending = False
        self._playback_generation = 0
        self._last_playback_error = ""
        self._spotify_view: dict[str, object] = {
            "mode": "results",
            "title": "Spotify results",
            "reference": "",
        }
        self._error_reports = error_reports.read()
        self._listening = tempo_store.load()
        self._listening_mode = "plan"
        self._live_queue_rows = []
        self._live_queue_state = {"current": {}, "stale": True, "error": "", "updated": "", "refreshing": False}
        self._live_queue_active = False
        self._live_queue_pending = False
        self._live_queue_generation = 0
        self._live_queue_timer = QTimer(self)
        self._live_queue_timer.setInterval(5000)
        self._live_queue_timer.timeout.connect(self.refreshLiveQueue)
        self._activity: list[dict[str, str]] = []
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        self._view_save_timer = QTimer(self)
        self._view_save_timer.setSingleShot(True)
        self._view_save_timer.setInterval(250)
        self._view_save_timer.timeout.connect(self._save_view_preferences)
        self.table_model.filterChanged.connect(self._view_save_timer.start)
        self.table_model.sortChanged.connect(self._view_save_timer.start)
        self.table_model.columnsChanged.connect(self._view_save_timer.start)
        QTimer.singleShot(150, self.loadConfiguredTable)
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(5000)
        self._playback_timer.timeout.connect(self._poll_playback)
        self._playback_timer.start()

    @Property(str, notify=statusChanged)
    def statusMessage(self) -> str:
        return ("Updating list" if self.table_model.updating else
                "Updating Spotify tagged list" if self._tagged_update_running and not self._busy_count else self._status)

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy_count > 0 or self.table_model.updating

    @Property("QVariantMap", notify=updateProgressChanged)
    def updateProgress(self):
        return self._update_progress

    @Slot(str, int, int, str)
    def _update_progress_received(self, stage, completed, total, detail):
        self._update_progress = {"stage": stage, "completed": completed, "total": total, "detail": detail}
        self.updateProgressChanged.emit()

    def _table_changed(self, *args):
        self._table_revision += 1

    @Property(bool, notify=busyChanged)
    def taggedUpdateRunning(self):
        return self._tagged_update_running

    @Property(bool, notify=busyChanged)
    def working(self):
        return self.busy or self._tagged_update_running

    @Property(str, notify=themeChanged)
    def themeName(self) -> str:
        return str(self.settings.get("theme", "Paper"))

    @Property(bool, notify=themeChanged)
    def darkMode(self) -> bool:
        return self.themeName == "Night"

    @Property(str, notify=accentChanged)
    def accentName(self) -> str:
        return str(self.settings.get("accent", "Terracotta"))

    @Property("QVariantMap", notify=settingsChanged)
    def settingsMap(self) -> dict[str, object]:
        return dict(self.settings)

    @Property("QVariantMap", notify=mergeChanged)
    def mergeResult(self) -> dict[str, object]:
        return self._merge_result

    @Property("QVariantList", notify=spotifyChanged)
    def spotifyResults(self) -> list[dict[str, object]]:
        return self._spotify_results

    @Property("QVariantMap", notify=spotifyChanged)
    def spotifyState(self) -> dict[str, object]:
        return self._spotify_state

    @Property("QVariantMap", notify=spotifyChanged)
    def spotifyView(self) -> dict[str, object]:
        return self._spotify_view

    @Property("QVariantList", notify=activityChanged)
    def activityItems(self) -> list[dict[str, str]]:
        return self._activity[-30:][::-1]

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        self.settings["theme"] = theme if theme in {"Paper", "Night"} else "Paper"
        self.table_model.setDarkTheme(self.darkMode)
        self.themeChanged.emit()
        self._save()

    @Slot(str)
    def setAccent(self, accent: str) -> None:
        if accent not in {"Terracotta", "Ocean", "Golden", "Berry"}:
            return
        self.settings["accent"] = accent
        self.accentChanged.emit()
        self._save()

    @Slot(str, object)
    def setSetting(self, key: str, value: object) -> None:
        if key not in self.settings:
            return
        self.settings[key] = value
        self.settingsChanged.emit()
        self._save()

    @Slot(str, str, str)
    def choosePath(self, key: str, mode: str, title: str) -> None:
        current = Path(str(self.settings.get(key, GENERATED_DIR))).expanduser()
        if mode == "folder":
            selected = QFileDialog.getExistingDirectory(
                None,
                title,
                str(current if current.exists() else current.parent),
            )
        elif mode == "save":
            selected, _ = QFileDialog.getSaveFileName(
                None,
                title,
                str(current),
                self._qt_file_filter(save=True),
            )
        else:
            selected, _ = QFileDialog.getOpenFileName(
                None,
                title,
                str(current if current.exists() else current.parent),
                self._qt_file_filter(save=False),
            )
        if selected:
            self.settings[key] = selected
            self.settingsChanged.emit()
            self._save()

    @staticmethod
    def _qt_file_filter(save: bool) -> str:
        if save:
            return (
                "Excel workbook (*.xlsx);;CSV (*.csv);;TSV (*.tsv);;"
                "JSON records (*.json);;JSON Lines (*.jsonl)"
            )
        return (
            "Table files (*.xlsx *.xlsm *.xls *.csv *.tsv *.txt *.json *.jsonl *.ndjson);;"
            "Excel workbooks (*.xlsx *.xlsm *.xls);;CSV (*.csv);;TSV (*.tsv *.txt);;"
            "JSON (*.json *.jsonl *.ndjson)"
        )

    @Slot()
    def openTableDialog(self) -> None:
        current = Path(str(self.settings.get("viewer_file", SPARETIME_DIR)))
        selected, _ = QFileDialog.getOpenFileName(
            None,
            "Open a music list",
            str(current if current.exists() else current.parent),
            self._qt_file_filter(save=False),
        )
        if selected:
            self.loadTable(selected, "", int(self.settings.get("viewer_row_limit", 2000)))

    @Slot()
    def loadConfiguredTable(self) -> None:
        path = str(self.settings.get("viewer_file", ""))
        if not path:
            tagged = GENERATED_DIR / "Spotify_Style_Theme_Tags.xlsx"
            path = str(tagged) if self.settings.get("viewer_sheet") == "Spotify Tags" and tagged.exists() else str(DEFAULT_SETTINGS["viewer_file"])
            self.settings["viewer_file"] = path
        if path and Path(path).exists():
            self.loadTable(
                path,
                str(self.settings.get("viewer_sheet", "")),
                int(self.settings.get("viewer_row_limit", 2000)),
            )
        elif path:
            self._error(f"Saved list not found: {path}. Use Open list to select it.", "Load saved list")

    @Slot(str, str, int)
    def loadTable(self, path: str, sheet: str = "", row_limit: int = 2000) -> None:
        source = Path(path)
        if not source.exists():
            self._error(f"Table file not found: {source}")
            return
        sheet_value: str | int = int(sheet) if sheet.isdigit() else sheet or 0

        def operation() -> tuple[pd.DataFrame, list[str]]:
            return (
                read_table_file(source, sheet_name=sheet_value, max_rows=row_limit),
                list_sheet_names(source),
            )

        def completed(payload: object) -> None:
            frame, sheets = payload
            self.table_model.set_frame(frame, str(source), sheets)
            self.settings["viewer_file"] = str(source)
            self.settings["viewer_sheet"] = sheet
            self.settings["viewer_row_limit"] = row_limit
            self._save()
            self._log("List loaded", f"{source.name} / {len(frame):,} rows")
            self.toastRequested.emit("List ready", source.name)

        self._run_task("Loading music list", operation, completed)

    @Slot()
    def exportCurrentView(self) -> None:
        current_format = str(self.settings.get("output_format", "Excel workbook (.xlsx)"))
        suffix = FORMAT_SUFFIXES.get(current_format, ".xlsx")
        initial = Path(str(self.settings.get("output_folder", GENERATED_DIR))) / f"filtered_songs{suffix}"
        selected, _ = QFileDialog.getSaveFileName(
            None,
            "Export the current view",
            str(initial),
            self._qt_file_filter(save=True),
        )
        if not selected:
            return
        output = Path(selected)
        detected = next(
            (label for label, value in FORMAT_SUFFIXES.items() if value == output.suffix.casefold()),
            current_format,
        )
        output = ensure_output_suffix(output, detected)
        if not self._safe_output_or_notify(output):
            return
        delimiter = delimiter_from_label(str(self.settings.get("csv_delimiter", "Comma (,)")))
        encoding = encoding_from_label(str(self.settings.get("text_encoding", "UTF-8 with BOM")))

        frame = self.table_model._view.copy(deep=True)

        def operation() -> Path:
            return write_table_file(frame, output, csv_delimiter=delimiter, text_encoding=encoding)

        def completed(result: object) -> None:
            path = Path(str(result))
            self._log("View exported", path.name)
            self.toastRequested.emit("Export complete", path.name)

        self._run_task("Exporting current view", operation, completed)

    def _merge_options(self) -> MergeOptions:
        keys = [
            item.strip()
            for item in str(self.settings.get("merge_key_columns", "Track Name, Artist(s)")).split(",")
            if item.strip()
        ]
        return MergeOptions(
            key_columns=keys,
            update_mode=str(self.settings.get("merge_update_mode", "fill_blanks")),
            include_new_columns=True,
            inject_playlist_from_filename=True,
            preview_limit=100,
            csv_delimiter=delimiter_from_label(
                str(self.settings.get("csv_delimiter", "Comma (,)"))
            ),
            text_encoding=encoding_from_label(
                str(self.settings.get("text_encoding", "UTF-8 with BOM"))
            ),
        )

    @Slot(bool)
    def runMerge(self, preview_only: bool = True) -> None:
        source = Path(str(self.settings.get("merge_source_file", "")))
        master = Path(str(self.settings.get("merge_master_file", "")))
        output = Path(str(self.settings.get("merge_output_file", "")))
        if not source.exists() or not master.exists():
            self._error("Choose an existing source and master table first.")
            return
        if not preview_only:
            if not self._safe_output_or_notify(output):
                return

        def operation() -> MergeSummary:
            return merge_excel_into_master(
                source,
                master,
                output,
                self._merge_options(),
                preview_only=preview_only,
            )

        self._run_task(
            "Previewing merge" if preview_only else "Creating merged list",
            operation,
            lambda result: self._merge_completed(result, preview_only),
        )

    @Slot(bool)
    def runBatchBuild(self, preview_only: bool = True) -> None:
        folder = Path(str(self.settings.get("batch_source_dir", "")))
        template = Path(str(self.settings.get("batch_template_file", "")))
        output = Path(str(self.settings.get("batch_output_file", "")))
        if not folder.exists() or not template.exists():
            self._error("Choose an existing source folder and template first.")
            return
        if not preview_only:
            if not self._safe_output_or_notify(output):
                return

        def operation() -> MergeSummary:
            return build_master_from_folder(
                folder,
                output,
                self._merge_options(),
                template_path=template,
                skip_filenames=[template.name],
                preview_only=preview_only,
            )

        self._run_task(
            "Previewing master build" if preview_only else "Building master list",
            operation,
            lambda result: self._merge_completed(result, preview_only),
        )

    def _merge_completed(self, result: MergeSummary, preview_only: bool) -> None:
        self._merge_result = {
            **asdict(result),
            "title": "Preview ready" if preview_only else "Output created",
            "summary": (
                f"{result.rows_added:,} added  /  {result.rows_updated:,} updated  /  "
                f"{result.rows_skipped:,} unchanged"
            ),
        }
        self.mergeChanged.emit()
        label = "Merge preview" if preview_only else "Merged list"
        self._log(label, str(self._merge_result["summary"]))
        self.toastRequested.emit(label, str(self._merge_result["summary"]))

    def _spotify_settings(self) -> SpotifySettings:
        return SpotifySettings(
            client_id=str(self.settings.get("spotify_client_id", "")),
            client_secret=str(self.settings.get("spotify_client_secret", "")),
            redirect_uri=str(self.settings.get("spotify_redirect_uri", "")),
            playlist_ids=parse_playlist_entries(
                str(self.settings.get("spotify_playlist_ids", ""))
            ),
            device_id=str(self.settings.get("spotify_device_id", "")),
            cache_path=GENERATED_DIR.parent / ".spotify_cache",
        )

    @Slot()
    def spotifyAuthorize(self) -> None:
        self._run_task(
            "Connecting Spotify",
            lambda: authorize_user(self._spotify_settings()),
            lambda result: self._spotify_completed("Spotify connected", result),
        )

    @Slot()
    def spotifyCapabilityCheck(self) -> None:
        def completed(payload: object) -> None:
            profile, checks = payload
            self._spotify_state = dict(profile)
            self._spotify_view = {
                "mode": "capabilities",
                "title": "Capability check",
                "reference": "",
            }
            self._spotify_results = [
                {"type": "capability", "name": item.name, "subtitle": item.detail, "extra": "Available" if item.ok else "Restricted"}
                for item in checks
            ]
            self.spotifyChanged.emit()
            self._log("Spotify capability check", f"{sum(item.ok for item in checks)}/{len(checks)} available")

        self._run_task(
            "Checking Spotify capabilities",
            lambda: run_capability_check(self._spotify_settings()),
            completed,
        )

    @Slot(str, str)
    def spotifySearch(self, query: str, search_types: str = "track,artist,album,playlist") -> None:
        if not query.strip():
            self._error("Enter something to search for.")
            return

        def completed(result: object) -> None:
            self._spotify_results = list(result)
            self._spotify_view = {
                "mode": "search",
                "title": f"Search results for {query}",
                "reference": "",
            }
            self.spotifyChanged.emit()
            self._log("Spotify search", f"{len(self._spotify_results)} results for {query}")

        self._run_task(
            "Searching Spotify",
            lambda: search_catalog(
                self._spotify_settings(),
                query,
                [item.strip() for item in search_types.split(",") if item.strip()],
                20,
            ),
            completed,
        )

    @Property("QVariantMap", notify=playbackChanged)
    def playbackState(self):
        return self._playback

    def _set_playback(self, result):
        self._playback = dict(result)
        self._playback["stale"] = False
        self.playbackChanged.emit()

    def _poll_playback(self):
        if self.busy or self._playback_pending or not self._spotify_settings().cache_path.exists():
            return
        self._fetch_playback()

    def _fetch_playback(self):
        if self._playback_pending:
            QTimer.singleShot(1000, self._poll_playback)
            return
        self._playback_pending = True
        generation = self._playback_generation
        settings = self._spotify_settings()
        worker = Worker(lambda: get_playback_state(settings))
        def succeeded(result):
            self._playback_pending = False
            if generation == self._playback_generation:
                self._set_playback(result)
                self._last_playback_error = ""
                self._playback_timer.setInterval(5000)
        def failed(message):
            self._playback_pending = False
            if generation != self._playback_generation:
                return
            self._playback_timer.setInterval(min(60000, self._playback_timer.interval() * 2))
            self._playback = {"stale": True, "error": message}
            self.playbackChanged.emit()
            if message != self._last_playback_error:
                self._error(message, "Refresh playback")
                self._last_playback_error = message
        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.succeeded.connect(lambda result, item=worker: self._workers.discard(item))
        worker.signals.failed.connect(lambda message, item=worker: self._workers.discard(item))
        self._workers.add(worker)
        self.thread_pool.start(worker)

    @Slot()
    def spotifyNowPlaying(self):
        self._fetch_playback()
        if self._live_queue_active:
            self.refreshLiveQueue()

    @Slot()
    def spotifyTogglePlayback(self):
        action = "pause" if str(self._playback.get("is_playing", "")).lower() == "true" else "play"
        self.spotifyPlayback(action, "")

    @Slot(str, str)
    def spotifyPlayback(self, action: str, reference: str = "") -> None:
        self._playback_generation += 1
        settings = self._spotify_settings()
        fallback_uri = next((str(row.get("uri", "")) for row in self._listening["plan"]
                             if str(row.get("uri", "")).startswith("spotify:track:")), "")
        actions: dict[str, Callable[[], object]] = {
            "play": lambda: play_reference(settings, reference, fallback_uri),
            "pause": lambda: pause_playback(settings),
            "next": lambda: next_track(settings),
            "previous": lambda: previous_track(settings),
            "shuffle_on": lambda: set_shuffle(settings, True),
            "shuffle_off": lambda: set_shuffle(settings, False),
        }
        operation = actions.get(action)
        if operation is None:
            self._error(f"Unknown playback action: {action}")
            return
        self._run_task(
            f"Spotify: {action.replace('_', ' ')}",
            operation,
            lambda _result: QTimer.singleShot(750, self.spotifyNowPlaying),
        )

    @Slot()
    def spotifyFadeSkip(self):
        if self.busy:
            return
        self._playback_generation += 1
        settings = self._spotify_settings()
        self._run_task("Fading volume for 5 seconds, then skipping", lambda: fade_skip(settings),
                       lambda result: QTimer.singleShot(750, self.spotifyNowPlaying))

    @Slot()
    def spotifyFadePause(self):
        if self.busy:
            return
        self._playback_generation += 1
        settings = self._spotify_settings()
        self._run_task("Fading volume for 5 seconds, then pausing", lambda: fade_pause(settings),
                       lambda result: QTimer.singleShot(750, self.spotifyNowPlaying))

    @Slot(str)
    def spotifySetVolume(self, value: str) -> None:
        try:
            volume = max(0, min(100, int(value)))
        except ValueError:
            self._error("Volume must be between 0 and 100.")
            return
        self._run_task(
            "Changing Spotify volume",
            lambda: set_volume(self._spotify_settings(), volume),
            lambda _result: self.toastRequested.emit("Spotify", f"Volume set to {volume}%"),
        )

    @Slot(str)
    def spotifyExportPlaylist(self, reference: str) -> None:
        if not reference.strip():
            self._error("Enter a playlist URL, URI, or ID first.")
            return
        initial = Path(str(self.settings.get("spotify_export_output", GENERATED_DIR / "spotify_playlist.xlsx")))
        selected, _ = QFileDialog.getSaveFileName(
            None,
            "Export Spotify playlist",
            str(initial),
            self._qt_file_filter(save=True),
        )
        if not selected:
            return
        output = Path(selected)
        if not self._safe_output_or_notify(output):
            return
        delimiter = delimiter_from_label(str(self.settings.get("csv_delimiter", "Comma (,)")))
        encoding = encoding_from_label(str(self.settings.get("text_encoding", "UTF-8 with BOM")))

        def operation() -> dict[str, str]:
            return export_playlist_to_file(
                self._spotify_settings(),
                reference,
                output,
                csv_delimiter=delimiter,
                text_encoding=encoding,
            )

        def completed(result: object) -> None:
            self.settings["spotify_export_output"] = str(output)
            self._save()
            self._spotify_completed("Playlist exported", result)

        self._run_task("Exporting Spotify playlist", operation, completed)

    @Slot()
    def spotifyLoadPlaylists(self) -> None:
        def completed(result: object) -> None:
            self._spotify_results = list(result)
            self._spotify_view = {
                "mode": "playlists",
                "title": "Your playlists",
                "reference": "",
            }
            self.spotifyChanged.emit()
            self._log("Spotify playlists", f"{len(self._spotify_results)} loaded")

        self._run_task(
            "Loading Spotify playlists",
            lambda: list_current_user_playlists(self._spotify_settings(), 50),
            completed,
        )

    @Slot()
    def spotifyLoadDevices(self) -> None:
        def completed(result: object) -> None:
            self._spotify_results = list(result)
            self._spotify_view = {
                "mode": "devices",
                "title": "Playback devices",
                "reference": "",
            }
            self.spotifyChanged.emit()
            self._log("Spotify devices", f"{len(self._spotify_results)} found")

        self._run_task(
            "Loading Spotify devices",
            lambda: list_devices(self._spotify_settings()),
            completed,
        )

    @Slot(str)
    def spotifyBrowse(self, category: str) -> None:
        settings = self._spotify_settings()
        operations: dict[str, Callable[[], object]] = {
            "saved": lambda: list_saved_tracks(settings, 50),
            "recent": lambda: list_recent_tracks(settings, 50),
            "top_tracks": lambda: list_top_tracks(settings, 30),
            "top_artists": lambda: list_top_artists(settings, 30),
            "queue": lambda: list_queue(settings),
        }
        operation = operations.get(category)
        if operation is None:
            self._error(f"Unknown Spotify collection: {category}")
            return

        def completed(result: object) -> None:
            if category == "queue":
                current, queued = result
                rows = ([current] if current else []) + list(queued)
            else:
                rows = list(result)
            self._spotify_results = rows
            titles = {
                "saved": "Saved tracks",
                "recent": "Recently played",
                "top_tracks": "Top tracks",
                "top_artists": "Top artists",
                "queue": "Current queue",
            }
            self._spotify_view = {
                "mode": category,
                "title": titles.get(category, "Spotify results"),
                "reference": "",
            }
            self.spotifyChanged.emit()
            self._log("Spotify collection", f"{len(rows)} {category.replace('_', ' ')} loaded")

        self._run_task(
            f"Loading Spotify {category.replace('_', ' ')}",
            operation,
            completed,
        )

    @Slot(str, str)
    def spotifyItemAction(self, action: str, reference: str) -> None:
        if not reference.strip():
            self._error("This Spotify action needs an item URI or device ID.")
            return
        settings = self._spotify_settings()
        actions: dict[str, Callable[[], object]] = {
            "queue": lambda: add_to_queue(settings, reference),
            "save": lambda: save_items_to_library(settings, [reference]),
            "remove": lambda: remove_items_from_library(settings, [reference]),
            "check": lambda: check_items_in_library(settings, [reference]),
            "device": lambda: transfer_playback(settings, reference, True),
        }
        operation = actions.get(action)
        if operation is None:
            self._error(f"Unknown Spotify item action: {action}")
            return

        def completed(result: object) -> None:
            if action == "device":
                self.settings["spotify_device_id"] = reference
                self._save()
                QTimer.singleShot(750, self.spotifyNowPlaying)
            if isinstance(result, list):
                self._spotify_results = list(result)
                self.spotifyChanged.emit()
            if action == "queue":
                match = next((item for item in self._spotify_results if item.get("uri") == reference), {"uri": reference, "name": "Spotify track"})
                self._append_queue_plan({**tempo_store.song(match), "queue_status": "Queued in Spotify"})
            self._spotify_completed(f"Spotify {action}", result)

        self._run_task(f"Spotify: {action}", operation, completed)

    @Slot(str, str)
    def spotifyOpenPlaylist(self, reference: str, name: str) -> None:
        if not reference.strip():
            self._error("This playlist does not contain a usable Spotify reference.")
            return

        def completed(result: object) -> None:
            self._spotify_results = list(result)
            self._spotify_view = {
                "mode": "playlist",
                "title": name.strip() or "Playlist",
                "reference": reference,
            }
            self.spotifyChanged.emit()
            self._log("Playlist opened", f"{self._spotify_view['title']} / {len(self._spotify_results)} tracks")

        self._run_task(
            f"Opening playlist: {name}",
            lambda: list_playlist_tracks(self._spotify_settings(), reference, 500),
            completed,
        )

    @Slot(int)
    def spotifyQueueTableRow(self, row: int) -> None:
        record = self.table_model.rowRecord(row)
        if not record:
            self._error("The selected table row is no longer available.")
            return

        folded = {str(key).casefold(): str(value) for key, value in record.items()}

        def first_value(candidates: tuple[str, ...]) -> str:
            for candidate in candidates:
                if folded.get(candidate):
                    return folded[candidate]
            for key, value in folded.items():
                if any(candidate in key for candidate in candidates) and value:
                    return value
            return ""

        track = first_value(("track name", "track", "song", "title"))
        artist = first_value(("artist(s)", "artists", "artist"))
        playlist = first_value(("playlist", "playlist name"))
        reference = first_value(("spotify uri", "track uri", "spotify url"))
        if not track and not reference:
            self._error("This row needs a Track Name or Spotify URI before it can be queued.")
            return

        import uuid
        plan_id = str(uuid.uuid4())
        planned = tempo_store.song(record)
        planned["plan_id"] = plan_id
        planned["queue_status"] = "Local queue"
        self._append_queue_plan(planned)
        if not self._spotify_settings().cache_path.exists():
            self.toastRequested.emit("Added to queue", "Saved locally. Connect Spotify to send songs to its queue.")
            return

        def completed(result: object) -> None:
            details = dict(result)
            data = tempo_store.load()
            for song in data["plan"]:
                if song.get("plan_id") == plan_id:
                    song["uri"] = str(details.get("track_uri", reference))
                    song["queue_status"] = "Queued in Spotify"
            tempo_store.save(data)
            self._listening = data
            self.listeningChanged.emit()
            source = str(details.get("source", "Spotify"))
            name = str(details.get("track_name", track))
            self._log("LargeList queued", f"{name} / {source}")
            self.toastRequested.emit("Added to Spotify queue", f"{name} / from {source}")

        self._run_task(
            f"Finding {track or 'Spotify track'}",
            lambda: queue_named_track(
                self._spotify_settings(),
                track,
                artist,
                reference,
                playlist,
            ),
            completed,
        )

    @Slot()
    def spotifyBuildTaggedList(self) -> None:
        if self._tagged_update_running or self.busy:
            self.toastRequested.emit("Update already busy", "Wait for the current task before starting another update.")
            return
        output = GENERATED_DIR / "Spotify_Style_Theme_Tags.xlsx"
        settings = self._spotify_settings()
        revision = self._table_revision

        def operation() -> tuple[pd.DataFrame, dict[str, int], Path]:
            frame, summary = build_tagged_playlist_table(settings, progress=self._import_progress_signal, apply_corrections=False)
            if frame.empty:
                raise ValueError("No songs were found in playlists beginning with Stil:, Event:, or Tema:.")
            self._import_progress_signal("Saving workbook", 0, 1, f"{len(frame):,} songs")
            field_store.remember(frame, str(output), refresh=True)
            frame = field_store.apply(tempo_store.apply(frame), str(output))
            written = write_table_file(frame, output, sheet_name="Spotify Tags")
            self._import_progress_signal("Saved workbook", 1, 1, f"{len(frame):,} songs")
            return frame, summary, written

        def completed(result: object) -> None:
            frame, summary, written = result
            if revision != self._table_revision:
                self._log("Spotify list updated", str(written))
                self.toastRequested.emit("Spotify list saved", "Your current list was kept because it changed during the update. Open the generated Spotify tagged list to view the update.")
                return
            self.table_model.set_frame(frame, str(written), ["Spotify Tags"])
            self.table_model.setSemanticColumns("Style", "")
            self.table_model.setColumnVisible("Spotify URI", False)
            self.settings["viewer_file"] = str(written)
            self.settings["viewer_sheet"] = "Spotify Tags"
            self._save()
            detail = (
                f"{summary['tracks']:,} songs from {summary['style_playlists']} style "
                f", {summary['event_playlists']} event and {summary['theme_playlists']} theme playlists; "
                f"KOD found for {summary['kod_tracks']:,}"
            )
            self._log("Spotify list updated", detail)
            self.toastRequested.emit("Spotify list updated", detail)
            self.navigateRequested.emit(0)

        self._run_task("Updating all Spotify style, event and theme songs", operation, completed, background=True)

    @Slot(str, str, bool)
    def lastFmSimilar(self, artist: str, track: str, artists_only: bool = False) -> None:
        api_key = str(self.settings.get("lastfm_api_key", ""))

        def operation() -> list[dict[str, str]]:
            if artists_only:
                return [
                    {
                        "type": "lastfm artist",
                        "name": item.name,
                        "subtitle": f"Match {item.match}",
                        "extra": "Last.fm",
                        "external_url": item.url,
                    }
                    for item in fetch_similar_artists(api_key, artist, 20)
                ]
            return [
                {
                    "type": "lastfm track",
                    "name": item.name,
                    "subtitle": item.artist,
                    "extra": f"Match {item.match}",
                    "external_url": item.url,
                }
                for item in fetch_similar_tracks(api_key, artist, track, 20)
            ]

        def completed(result: object) -> None:
            self._spotify_results = list(result)
            self._spotify_view = {
                "mode": "lastfm",
                "title": "Last.fm suggestions",
                "reference": "",
            }
            self.spotifyChanged.emit()
            self._log("Last.fm discovery", f"{len(self._spotify_results)} suggestions loaded")

        self._run_task("Finding Last.fm suggestions", operation, completed)

    def _spotify_completed(self, title: str, result: object) -> None:
        self._spotify_state = dict(result) if isinstance(result, dict) else {"message": str(result or title)}
        self.spotifyChanged.emit()
        self._log(title, str(self._spotify_state.get("name") or self._spotify_state.get("message") or "Complete"))
        self.toastRequested.emit(title, "Complete")

    @Slot(str)
    def openPath(self, path: str) -> None:
        if path.startswith(("https://", "http://")):
            QDesktopServices.openUrl(QUrl(path))
            return
        target = Path(path)
        if target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @Slot(int, int)
    def shutdown(self, width: int, height: int) -> None:
        self._view_save_timer.stop()
        self._playback_timer.stop()
        self.setLiveQueueActive(False)
        self.settings["window_width"] = width
        self.settings["window_height"] = height
        self._save_view_preferences()

    def _run_task(
        self,
        label: str,
        operation: Callable[[], object],
        completed: Callable[[object], None],
        *,
        background: bool = False,
    ) -> None:
        # The long import reads Spotify and owns only its generated output.
        # Foreground operations remain serialized, including playback mutations.
        if (background and self._tagged_update_running) or (not background and self.busy):
            self.toastRequested.emit("Task in progress", "Wait for the current action to finish before repeating it.")
            return
        if background:
            self._tagged_update_running = True
        else:
            self._busy_count += 1
        self._status = label
        self.busyChanged.emit()
        self.statusChanged.emit()
        worker = Worker(operation)
        if background:
            worker.signals.progress.connect(self._update_progress_received)
            self._import_progress_signal = worker.signals.progress.emit
            self._update_progress_received("Connecting Spotify", 0, 0, "")

        def succeeded(result: object) -> None:
            try:
                completed(result)
            except Exception as exc:
                self._finish_task(background)
                self._error(explain_spotify_error(exc), label)
            else:
                self._finish_task(background)

        def failed(message: str) -> None:
            if label == "Sending local queue to Spotify queue":
                self._listening = tempo_store.load()
                self.listeningChanged.emit()
            self._finish_task(background)
            self._error(message, label)

        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.succeeded.connect(lambda _result, item=worker: self._workers.discard(item))
        worker.signals.failed.connect(lambda _message, item=worker: self._workers.discard(item))
        self._workers.add(worker)
        (self.import_pool if background else self.thread_pool).start(worker)

    def _finish_task(self, background=False) -> None:
        if background:
            self._tagged_update_running = False
        else:
            self._busy_count = max(0, self._busy_count - 1)
        self._status = "Ready" if not self._busy_count else self._status
        self.busyChanged.emit()
        self.statusChanged.emit()

    def _error(self, message: str, action: str = "Action needed") -> None:
        secret = str(self.settings.get("spotify_client_secret", ""))
        message = error_reports.redact(message.replace(secret, "[redacted]") if secret else message)
        try:
            report = error_reports.append(action, message)
            self._error_reports.append(report)
            self.errorReportsChanged.emit()
        except OSError as exc:
            message += f" (Could not save error report: {exc})"
        self._status = message
        self.statusChanged.emit()
        self._log("Action needed", message)
        self.toastRequested.emit("Action needed", message)

    def _log(self, title: str, detail: str) -> None:
        self._activity.append({"title": title, "detail": detail})
        self._activity = self._activity[-200:]
        self.activityChanged.emit()

    def _ensure_safe_output(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        if self._tagged_update_running and resolved == (GENERATED_DIR / "Spotify_Style_Theme_Tags.xlsx").resolve():
            raise ValueError("The Spotify update is writing this file. Choose another output file or wait for the update to finish.")
        try:
            resolved.relative_to(SPARETIME_DIR.resolve())
        except ValueError:
            return
        raise ValueError(
            "Outputs cannot be written inside the original SpareTime folder. "
            "Choose the Qt app's generated folder or another location."
        )

    def _safe_output_or_notify(self, path: Path) -> bool:
        try:
            self._ensure_safe_output(path)
        except ValueError as exc:
            self._error(str(exc))
            return False
        return True

    def _save(self) -> None:
        snapshot = self.table_model.settings_snapshot()
        # Preferences may change before asynchronous startup loading completes.
        # Keep the last file until an actual list has been loaded.
        if not snapshot.get("viewer_file"):
            snapshot.pop("viewer_file", None)
        self.settings.update(snapshot)
        save_settings(self.settings)

    def _save_view_preferences(self) -> None:
        try:
            self._save()
        except OSError as exc:
            self._error(str(exc), "Save list view preferences")

    @Property("QVariantMap", notify=liveQueueChanged)
    def liveQueueState(self):
        return self._live_queue_state

    @Slot(bool)
    def setLiveQueueActive(self, active):
        self._live_queue_active = active
        if active:
            self._live_queue_timer.start()
            self.refreshLiveQueue()
        else:
            self._live_queue_timer.stop()
            self._live_queue_generation += 1

    @Slot()
    def refreshLiveQueue(self):
        if not self._live_queue_active or self._live_queue_pending:
            return
        try:
            settings = self._spotify_settings()
            if not settings.cache_path.exists():
                raise ValueError("Connect Spotify to read its live queue.")
        except ValueError as exc:
            self._live_queue_state.update(stale=True, error=str(exc), refreshing=False)
            self.liveQueueChanged.emit()
            return
        self._live_queue_pending = True
        self._live_queue_state["refreshing"] = True
        self.liveQueueChanged.emit()
        generation = self._live_queue_generation
        worker = Worker(lambda: list_queue(settings))

        def succeeded(result):
            self._live_queue_pending = False
            self._live_queue_state["refreshing"] = False
            if generation != self._live_queue_generation:
                self.liveQueueChanged.emit()
                return
            from datetime import datetime
            current, upcoming = result
            known = {tempo_store.key(song): song for song in self._listening["plan"] + self._listening["history"]}
            for record in self.table_model._source.to_dict("records"):
                song = tempo_store.song(record)
                known[tempo_store.key(song)] = song
            rows = []
            for item in upcoming:
                song = tempo_store.song(item)
                match = known.get(tempo_store.key(song), {})
                song.update({field: match.get(field, "") for field in ("bpm", "kod")})
                song["queue_status"] = "Spotify queue"
                rows.append(song)
            self._live_queue_rows = rows
            self._live_queue_state = {"current": current or {}, "stale": False, "error": "",
                                      "updated": datetime.now().astimezone().strftime("%H:%M:%S"), "refreshing": False}
            self._live_queue_timer.setInterval(5000)
            self.liveQueueChanged.emit()
            self.listeningChanged.emit()

        def failed(message):
            self._live_queue_pending = False
            self._live_queue_state["refreshing"] = False
            if generation == self._live_queue_generation:
                self._live_queue_state.update(stale=True, error=message)
                self._live_queue_timer.setInterval(min(60000, self._live_queue_timer.interval() * 2))
            self.liveQueueChanged.emit()

        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.succeeded.connect(lambda result, item=worker: self._workers.discard(item))
        worker.signals.failed.connect(lambda message, item=worker: self._workers.discard(item))
        self._workers.add(worker)
        self.thread_pool.start(worker)

    @Property("QVariantList", notify=listeningChanged)
    def listeningRows(self):
        rows = self._live_queue_rows if self._listening_mode == "live" else self._listening[self._listening_mode]
        corrections = tempo_store.load()["corrections"]
        return [tempo_store.normalize({**row, **corrections.get(tempo_store.key(row), {}),
                                       "queue_status": str(row.get("queue_status", "")).replace("Local plan", "Local queue")}) for row in rows]

    @Slot(str)
    def listeningMode(self, mode):
        if mode == "queue":
            mode = "plan"
        if mode in ("history", "plan", "live"):
            self._listening_mode = mode
            self.listeningChanged.emit()

    @Slot()
    def refreshListeningHistory(self):
        known = {tempo_store.key(tempo_store.song(record)): tempo_store.song(record)
                 for record in self.table_model._source.to_dict("records")}
        def completed(result):
            data = tempo_store.load()
            existing = {(r.get("played_at"), r.get("uri")) for r in data["history"]}
            deleted = {tuple(identity) for identity in data.get("deleted_history", [])}
            for record in result:
                row = tempo_store.song(record)
                row["played_at"] = record.get("played_at", "")
                match = known.get(tempo_store.key(row), {})
                row.update({field: match.get(field, "") for field in ("bpm", "kod")})
                if row["uri"] and (row["played_at"], row["uri"]) not in existing | deleted:
                    data["history"].append(row)
                    existing.add((row["played_at"], row["uri"]))
            data["history"].sort(key=lambda r: r.get("played_at", ""))
            tempo_store.save(data)
            self._listening = data
            self.listeningChanged.emit()
        self._run_task("Refreshing played songs", lambda: list_recent_tracks(self._spotify_settings(), 50), completed)

    @Slot(int)
    def addPlanSong(self, row):
        record = tempo_store.song(self.table_model.rowRecord(row))
        if not record["name"]:
            return
        data = tempo_store.load()
        data["plan"].append(record)
        tempo_store.save(data)
        self._listening = data
        self.listeningChanged.emit()
        self.toastRequested.emit("Added to queue", record["name"])

    @Slot(int, int)
    def movePlanSong(self, index, direction):
        data = tempo_store.load()
        target = index + direction
        if 0 <= index < len(data["plan"]) and 0 <= target < len(data["plan"]):
            data["plan"][index], data["plan"][target] = data["plan"][target], data["plan"][index]
            tempo_store.save(data)
            self._listening = data
            self.listeningChanged.emit()

    @Slot(int)
    def removePlanSong(self, index):
        data = tempo_store.load()
        if 0 <= index < len(data["plan"]):
            removed = data["plan"].pop(index)
            tempo_store.save(data)
            self._listening = data
            self.listeningChanged.emit()
            if removed.get("queue_status") == "Queued in Spotify":
                self.toastRequested.emit("Removed locally", "Spotify does not support queue removal through its API. Remove this song in Spotify too.")

    @Slot(int)
    def removeHistorySong(self, index):
        data = tempo_store.load()
        if 0 <= index < len(data["history"]):
            removed = data["history"].pop(index)
            # Keep deletions from being undone by the next Spotify refresh.
            identity = [removed.get("played_at", ""), removed.get("uri", "")]
            deleted = data.setdefault("deleted_history", [])
            if identity not in deleted:
                deleted.append(identity)
            tempo_store.save(data)
            self._listening = data
            self.listeningChanged.emit()

    @Slot()
    def clearListeningHistory(self):
        data = tempo_store.load()
        deleted = data.setdefault("deleted_history", [])
        for row in data["history"]:
            identity = [row.get("played_at", ""), row.get("uri", "")]
            if identity not in deleted:
                deleted.append(identity)
        data["history"] = []
        tempo_store.save(data)
        self._listening = data
        self.listeningChanged.emit()
        self.toastRequested.emit("Played history emptied", "Saved history cleared. Tempo corrections are kept.")

    @Property("QVariantMap", notify=tagSyncChanged)
    def tagSyncPreview(self):
        return self._tag_sync_preview

    def _changed_tag_additions(self):
        data = field_store.load()
        changes = []
        for uri, fields in data["edits"].items():
            if not uri.startswith("spotify:track:"):
                continue
            original = data["originals"].get(uri, {})
            for column in ("Style", "Theme"):
                if column not in fields:
                    continue
                before = {tag.casefold() for tag in self.table_model._split_tags(original.get(column, ""))}
                for tag in self.table_model._split_tags(fields[column]):
                    if tag.casefold() not in before:
                        changes.append({"uri": uri, "column": column, "tag": tag,
                                        "name": fields.get("Track Name", original.get("Track Name", uri))})
        return changes

    @Slot()
    def previewChangedTagsToSpotify(self):
        if self._tagged_update_running or self.busy:
            self.toastRequested.emit("Task in progress", "Finish the current task before previewing playlist additions.")
            return
        try:
            changes = self._changed_tag_additions()
            settings = self._spotify_settings()
        except (ValueError, OSError) as exc:
            self._error(str(exc), "Preview edited tags")
            return
        self._tag_sync_preview = {}
        self.tagSyncChanged.emit()
        if not changes:
            self.toastRequested.emit("No new tags", "No saved Style or Theme edits add a new tag to a Spotify song.")
            return
        def completed(result):
            self._tag_sync_changes = changes
            self._tag_sync_preview = result
            self.tagSyncChanged.emit()
        self._run_task("Previewing edited tags in Spotify playlists", lambda: preview_tag_playlist_additions(settings, changes), completed)

    @Slot()
    def addChangedTagsToSpotify(self):
        if self._tagged_update_running or self.busy or not self._tag_sync_preview.get("count"):
            return
        try:
            if self._changed_tag_additions() != self._tag_sync_changes:
                raise ValueError("Style or Theme edits changed. Preview the playlist additions again.")
            settings = self._spotify_settings()
        except (ValueError, OSError) as exc:
            self._error(str(exc), "Add edited tags to Spotify")
            return
        preview = self._tag_sync_preview
        def completed(result):
            self._tag_sync_preview = {"count": 0, "playlists": [], "issues": result["failures"],
                                      "result": f"{result['added']} playlist additions confirmed; {result['skipped']} songs already present."}
            self.tagSyncChanged.emit()
            if result["failures"]:
                self._error("\n".join(result["failures"]), "Add edited tags to Spotify")
            else:
                self.toastRequested.emit("Spotify lists updated", self._tag_sync_preview["result"])
        self._run_task("Adding edited songs to Spotify lists", lambda: add_previewed_tag_songs(settings, preview), completed)

    @Property("QVariantMap", notify=bulkTempoChanged)
    def bulkTempoPreview(self):
        return self._bulk_tempo

    @Property(bool, notify=bulkTempoChanged)
    def canUndoBulkTempo(self):
        return self._bulk_undo is not None

    @Slot(str, str, bool, str)
    def previewBulkTempo(self, unit, factor, below_sixty, row_selection):
        try:
            import re
            multiplier = tempo_store.parse_tempo_input(factor)
            indices = list(self.table_model._view.index)
            if row_selection.strip():
                chosen = set()
                for token in row_selection.split(","):
                    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", token)
                    if not match:
                        raise ValueError("Use row numbers such as 1-10, 15, 20-25.")
                    first, last = int(match[1]), int(match[2] or match[1])
                    if not 1 <= first <= last <= len(indices):
                        raise ValueError("Row numbers must be within the current filtered list.")
                    chosen.update(range(first - 1, last))
                indices = [indices[i] for i in sorted(chosen)]
            frame = self.table_model._source
            corrections = {}
            skipped = 0
            for index in indices:
                row = tempo_store.song(frame.loc[index].to_dict())
                try:
                    old = float(row[unit.lower()])
                    import math
                    if not math.isfinite(old) or old <= 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    skipped += 1
                    continue
                if below_sixty and old >= 60:
                    continue
                number = tempo_store.validated_tempo(str(old * multiplier), unit)
                bpm = number if unit == "BPM" else number * 2
                change = {"bpm": bpm, "kod": number if unit == "KOD" else tempo_store.kod_from_bpm(bpm)}
                identity = tempo_store.key(row)
                if identity in corrections and corrections[identity] != change:
                    raise ValueError("Repeated copies of a song have different tempos. Filter or select those rows separately.")
                corrections[identity] = change
            preview = []
            for index, record in frame.iterrows():
                row = tempo_store.song(record.to_dict())
                change = corrections.get(tempo_store.key(row))
                if change:
                    preview.append({"name": row["name"], "artists": row["artists"],
                                    "before": row[unit.lower()], "after": change[unit.lower()], "unit": unit})
            self._bulk_tempo = {"rows": preview, "count": len(preview), "songs": len(corrections),
                                "skipped": skipped, "revision": self._table_revision, "corrections": corrections,
                                "unit": unit, "factor": factor, "below": below_sixty, "selection": row_selection}
            self.bulkTempoChanged.emit()
        except (ValueError, KeyError) as exc:
            self._bulk_tempo = {}
            self.bulkTempoChanged.emit()
            self._error(str(exc), "Preview tempo multiplication")

    @Slot()
    def applyBulkTempo(self):
        preview = self._bulk_tempo
        if not preview.get("count"):
            return
        if preview["revision"] != self._table_revision:
            self._error("The list changed. Preview the tempo multiplication again before applying it.", "Apply tempo multiplication")
            return
        try:
            data = tempo_store.load()
            changes = preview["corrections"]
            previous = {key: data["corrections"].get(key) for key in changes}
            data["corrections"].update(changes)
            tempo_store.save(data)
            self._bulk_undo = {"previous": previous, "applied": changes, "frame": self.table_model._source.copy(deep=True), "file": self.table_model.currentFile}
            self._listening = data
            self.table_model.set_frame(self.table_model._source, self.table_model.currentFile, self.table_model.sheetNames, remember_originals=False)
            self._bulk_tempo = {}
            self.bulkTempoChanged.emit()
            self.listeningChanged.emit()
            self.toastRequested.emit("Tempos multiplied", f"Updated {preview['count']} rows. Export the list to save a new file.")
        except (ValueError, OSError) as exc:
            self._error(str(exc), "Apply tempo multiplication")

    @Slot()
    def undoBulkTempo(self):
        undo = self._bulk_undo
        if undo is None:
            return
        try:
            data = tempo_store.load()
            if any(data["corrections"].get(key) != value for key, value in undo["applied"].items()):
                raise ValueError("Some affected tempos were edited again. Undo cannot overwrite those newer corrections.")
            for key, value in undo["previous"].items():
                if value is None:
                    data["corrections"].pop(key, None)
                else:
                    data["corrections"][key] = value
            tempo_store.save(data)
            frame = self.table_model._source.copy(deep=True)
            if undo["file"] == self.table_model.currentFile:
                # Restore original tempo cells only; preserve other edits made since apply.
                original = {tempo_store.key(tempo_store.song(record.to_dict())): record for _, record in undo["frame"].iterrows()}
                for index, record in frame.iterrows():
                    key = tempo_store.key(tempo_store.song(record.to_dict()))
                    if key in undo["applied"] and key in original:
                        for column in ("BPM", "KOD"):
                            if column in frame:
                                frame[column] = frame[column].astype(object)
                                frame.at[index, column] = original[key].get(column, "")
            self._listening = data
            self.table_model.set_frame(frame, self.table_model.currentFile, self.table_model.sheetNames, remember_originals=False)
            self._bulk_undo = None
            self._bulk_tempo = {}
            self.bulkTempoChanged.emit()
            self.listeningChanged.emit()
        except (ValueError, OSError) as exc:
            self._error(str(exc), "Undo tempo multiplication")

    @Slot(str, str, result=str)
    def tempoInputPreview(self, value, unit):
        if not value.strip():
            return "Enter a tempo or multiply, for example 30*2."
        try:
            number = tempo_store.validated_tempo(value, unit)
            return f"= {number:g} {unit}"
        except ValueError as exc:
            return str(exc)

    @Slot("QVariantMap")
    def lookupSongTempo(self, record):
        from urllib.parse import urlencode
        song = tempo_store.song(record)
        if song["name"]:
            QDesktopServices.openUrl(QUrl("https://www.google.com/search?" + urlencode({"q": f'{song["name"]} {song["artists"]} BPM tempo'})))

    @Slot("QVariantMap", str, str, result=bool)
    def correctSongTempo(self, record, value, unit):
        try:
            tempo_store.correct(tempo_store.song(record), value, unit)
            self.table_model.set_frame(self.table_model._source, self.table_model.currentFile, self.table_model.sheetNames, remember_originals=False)
            self._listening = tempo_store.load()
            self.listeningChanged.emit()
            self.toastRequested.emit("Tempo saved", "The correction is kept for future Spotify updates.")
            return True
        except (ValueError, OSError) as exc:
            self._error(str(exc), "Save song tempo")
            return False

    @Slot(int, str, str)
    def correctListeningTempo(self, index, value, unit):
        try:
            row = self.listeningRows[index]
            tempo_store.correct(row, value, unit)
            self.table_model.set_frame(self.table_model._source, self.table_model.currentFile, remember_originals=False)
            self.listeningChanged.emit()
        except (ValueError, OSError, IndexError) as exc:
            self._error(str(exc))

    @Slot(str)
    def exportListeningPlaylist(self, name):
        rows = self.listeningRows
        uris = [str(row.get("uri", "")) for row in rows]
        self._run_task("Creating Spotify playlist", lambda: export_listening_playlist(self._spotify_settings(), name, uris),
                       lambda result: self.toastRequested.emit("Playlist created", str(result.get("name", name))))

    @Property("QVariantList", notify=errorReportsChanged)
    def errorReports(self):
        return list(reversed(self._error_reports))

    @Slot()
    def clearErrorReports(self):
        try:
            if error_reports.PATH.exists():
                error_reports.PATH.write_text("", encoding="utf-8")
            self._error_reports.clear()
            self.errorReportsChanged.emit()
            self.toastRequested.emit("Error reports cleared", "The saved error list is empty")
        except OSError as exc:
            self._error(str(exc), "Clear error reports")

    @Slot()
    def exportErrorReports(self):
        filename, _ = QFileDialog.getSaveFileName(None, "Export error reports", str(GENERATED_DIR / "error_reports.json"), "JSON files (*.json)")
        if not filename:
            return
        output = Path(filename)
        if not self._safe_output_or_notify(output):
            return
        try:
            import json
            output.write_text(json.dumps(self._error_reports, ensure_ascii=False, indent=2), encoding="utf-8")
            self.toastRequested.emit("Error reports exported", str(output))
        except OSError as exc:
            self._error(str(exc), "Export error reports")

    def _append_queue_plan(self, record):
        data = tempo_store.load()
        data["plan"].append(record)
        tempo_store.save(data)
        self._listening = data
        self.listeningChanged.emit()

    @Slot()
    def refreshQueuePlan(self):
        known = {tempo_store.key(tempo_store.song(record)): tempo_store.song(record)
                 for record in self.table_model._source.to_dict("records")}
        def completed(result):
            current, upcoming = result
            data = tempo_store.load()
            data["plan"] = []
            for item in upcoming:
                song = tempo_store.song(item)
                match = known.get(tempo_store.key(song), {})
                song.update({field: match.get(field, "") for field in ("bpm", "kod")})
                song["queue_status"] = "Queued in Spotify"
                data["plan"].append(song)
            tempo_store.save(data)
            self._listening = data
            self.listeningChanged.emit()
            self.toastRequested.emit("Queue refreshed", f"{len(upcoming)} upcoming songs from Spotify")
        self._run_task("Loading Spotify queue", lambda: list_queue(self._spotify_settings()), completed)

    @Slot()
    def sendLocalPlanToQueue(self):
        rows = [dict(row) for row in self._listening["plan"] if row.get("queue_status") != "Queued in Spotify"]
        if not rows:
            self.toastRequested.emit("Queue", "No local songs waiting to be queued")
            return
        settings = self._spotify_settings()
        def operation():
            # Save each successful addition so retrying a partially failed send does not duplicate it.
            for row in rows:
                details = queue_named_track(settings, row["name"], row["artists"], row.get("uri", ""))
                data = tempo_store.load()
                match = next((song for song in data["plan"] if song.get("queue_status") != "Queued in Spotify"
                              and tempo_store.key(song) == tempo_store.key(row)), None)
                if match is not None:
                    match["uri"] = details["track_uri"]
                    match["queue_status"] = "Queued in Spotify"
                    tempo_store.save(data)
            return tempo_store.load()
        def completed(data):
            self._listening = data
            self.listeningChanged.emit()
            self.toastRequested.emit("Queue sent", "Local songs appended to Spotify's queue")
        self._run_task("Sending local queue to Spotify queue", operation, completed)
