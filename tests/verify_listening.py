import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QObject, QMetaObject
import tempo_store
from table_model import SongTableModel
from controller import AppController
from spotify_tools import export_listening_playlist

QQuickStyle.setStyle("Basic")
assert tempo_store.normalize({"bpm": "nan", "kod": "76.0"})["bpm"] == 152
assert tempo_store.normalize({"bpm": "nan", "kod": "nan"})["bpm"] == ""
assert tempo_store.normalize({"bpm": "120", "kod": ""})["kod"] == 60
app = QApplication([])
app.setFont(QFont("Segoe UI"))
with TemporaryDirectory() as folder, patch.object(tempo_store, "PATH", Path(folder) / "history.json"), patch("controller.load_settings", return_value={}), patch("controller.save_settings"):

    model = SongTableModel()
    model.set_frame(pd.DataFrame([{"Track Name": "Song", "Artist(s)": "Artist", "Spotify URI": "spotify:track:abc", "KOD": 60}]))
    controller = AppController(model)
    controller._set_playback({"track_name": "Current", "is_playing": "True"})
    controller._spotify_completed("Search results", {"name": "Previous"})
    assert controller.playbackState["track_name"] == "Current"
    with patch.object(controller, "spotifyPlayback") as playback:
        controller.spotifyTogglePlayback()
        playback.assert_called_with("pause", "")
        controller._set_playback({"is_playing": "False"})
        controller.spotifyTogglePlayback()
        playback.assert_called_with("play", "")
    controller._set_playback({})
    assert not controller.playbackState.get("track_name")
    controller.addPlanSong(0)
    controller.addPlanSong(0)
    controller.correctListeningTempo(0, "134", "BPM")
    assert controller.listeningRows[0]["kod"] == 67
    assert model.rowRecord(0)["KOD"] == "67"
    assert tempo_store.load()["corrections"]["spotify:track:abc"]["bpm"] == 134
    controller.movePlanSong(0, 1)
    controller.removePlanSong(1)
    assert len(controller.listeningRows) == 1
    model.set_frame(pd.DataFrame([{"Track Name": "Song", "Spotify URI": "spotify:track:abc", "KOD": 99}]))
    assert model.rowRecord(0)["KOD"] == "67"
    for invalid in ("0", "nan", "wrong"):
        try:
            tempo_store.correct(controller.listeningRows[0], invalid, "BPM")
            raise AssertionError("invalid tempo accepted")
        except ValueError:
            pass
    client = Mock()
    client._post.return_value = {"id": "new", "name": "Dance night"}
    with patch("spotify_tools.build_spotify_client", return_value=client):
        export_listening_playlist(None, "Dance night", ["spotify:track:abc"] * 201)
    assert client._post.call_count == 4
    assert len(client._post.call_args_list[-1].kwargs["payload"]["uris"]) == 1
    data = tempo_store.load()
    data["history"] = [{"name": "Song", "artists": "Artist", "uri": "spotify:track:abc", "played_at": "2026-10-06T10:00:00Z"},
                       {"name": "Song", "artists": "Artist", "uri": "spotify:track:abc", "played_at": "2026-10-06T11:00:00Z"}]
    tempo_store.save(data)
    controller.removeHistorySong(0)
    assert len(tempo_store.load()["history"]) == 1
    controller.clearListeningHistory()
    cleared = tempo_store.load()
    assert not cleared["history"] and len(cleared["deleted_history"]) == 2
    assert cleared["corrections"] and cleared["plan"]

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("controller", controller)
    engine.rootContext().setContextProperty("tableModel", model)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "qml/Main.qml")))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    dialog = window.findChild(QObject, "listeningDialog")
    assert dialog is not None
    QMetaObject.invokeMethod(dialog, "open")
    QTest.qWait(100)
    app.processEvents()
    image = window.grabWindow()
    assert not image.isNull()
    from config import GENERATED_DIR
    image.save(str(GENERATED_DIR / "qml_smoke_plan.png"))
    controller.thread_pool.waitForDone()
    print("LISTENING_OK persistence corrections plan export_batches dialog_plot")
