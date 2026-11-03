"""Read-only live Spotify queue: polling, ordering, failure/recovery and UI."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys, time, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import QObject, QUrl, QMetaObject
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
import tempo_store, error_reports
from controller import AppController
from table_model import SongTableModel
from spotify_tools import SpotifySettings
QQuickStyle.setStyle('Basic')
app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
app.setFont(QFont("Segoe UI", 10))
def wait_for(condition):
    for _ in range(1000):
        QTest.qWait(10)
        time.sleep(.005)
        if condition(): return
    raise AssertionError('Queue request did not finish')
with TemporaryDirectory() as folder:
    root = Path(folder)
    settings = SpotifySettings('id', 'secret', 'http://127.0.0.1', [], cache_path=root/'cache')
    settings.cache_path.write_text('{}')
    with patch.object(tempo_store, 'PATH', root/'listening.json'), patch.object(error_reports, 'PATH', root/'errors.jsonl'), patch('controller.load_settings', return_value={'viewer_file': str(root/'absent.csv')}), patch('controller.save_settings'):
        tempo_store.save({'history': [], 'plan': [{'name': 'Saved', 'artists': 'Artist', 'uri': 'spotify:track:saved', 'queue_status': 'Local plan'}], 'corrections': {}})
        original = tempo_store.PATH.read_bytes()
        model = SongTableModel()
        model.set_frame(pd.DataFrame([{'Track Name': 'A', 'Artist(s)': 'Artist', 'Spotify URI': 'spotify:track:a', 'KOD': 64}]))
        controller = AppController(model)
        controller._playback_timer.stop()
        controller.listeningMode('live')
        started, release = threading.Event(), threading.Event()
        upcoming = [{'name': 'A', 'subtitle': 'Artist', 'uri': 'spotify:track:a'}, {'name': 'B', 'subtitle': 'Artist', 'uri': 'spotify:track:b'}, {'name': 'A', 'subtitle': 'Artist', 'uri': 'spotify:track:a'}]
        def fetch(settings):
            started.set()
            assert release.wait(15)
            return {'name': 'Now', 'subtitle': 'Artist'}, upcoming
        with patch.object(controller, '_spotify_settings', return_value=settings), patch('controller.list_queue', side_effect=fetch) as queue:
            controller.setLiveQueueActive(True)
            wait_for(started.is_set)
            assert not controller.busy
            controller.refreshLiveQueue()
            assert queue.call_count == 1
            release.set()
            wait_for(lambda: not controller._workers)
            assert [row['name'] for row in controller.listeningRows] == ['A', 'B', 'A']
            assert controller.listeningRows[0]['kod'] == 64
            assert controller.liveQueueState['current']['name'] == 'Now'
            assert not controller.liveQueueState['stale']
            assert tempo_store.PATH.read_bytes() == original
            controller._tagged_update_running = True
            before = queue.call_count
            controller._live_queue_timer.setInterval(30)
            wait_for(lambda: queue.call_count > before and not controller._workers)
            controller._tagged_update_running = False
        with patch.object(controller, '_spotify_settings', return_value=settings), patch('controller.list_queue', side_effect=TimeoutError()):
            controller.refreshLiveQueue()
            wait_for(lambda: not controller._workers)
            assert controller.liveQueueState['stale'] and len(controller.listeningRows) == 3
            assert controller._live_queue_timer.interval() == 10000
        with patch.object(controller, '_spotify_settings', return_value=settings), patch('controller.list_queue', return_value=(None, [])):
            controller.refreshLiveQueue()
            wait_for(lambda: not controller._workers)
            assert controller.listeningRows == [] and not controller.liveQueueState['stale']
            assert controller._live_queue_timer.interval() == 5000
        controller.setLiveQueueActive(False)
        assert not controller._live_queue_timer.isActive()
        with patch('controller.list_queue') as queue:
            controller.refreshLiveQueue()
            queue.assert_not_called()
        controller.listeningMode('queue')
        assert controller.listeningRows[0]['name'] == 'Saved'
        assert controller.listeningRows[0]['queue_status'] == 'Local queue'
        assert tempo_store.PATH.read_bytes() == original
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty('controller', controller)
        engine.rootContext().setContextProperty('tableModel', model)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qml/Main.qml')))
        assert engine.rootObjects()
        window = engine.rootObjects()[0]
        dialog = window.findChild(QObject, 'listeningDialog')
        with patch.object(controller, '_spotify_settings', return_value=settings), patch('controller.list_queue', return_value=({'name':'Now', 'subtitle':'Artist'}, upcoming)):
            QMetaObject.invokeMethod(dialog, 'open')
            wait_for(lambda: controller._live_queue_active and not controller._workers)
            QTest.qWait(100)
            assert controller._live_queue_active and controller._listening_mode == 'live'
            assert not window.grabWindow().isNull()
            assert not dialog.property('modal')
            assert abs(dialog.property('x') + dialog.property('width') - window.width()) < 2
            from config import GENERATED_DIR
            window.grabWindow().save(str(GENERATED_DIR/'qml_smoke_queue_drawer.png'))
            controller.setTheme('Night')
            QTest.qWait(100)
            assert controller.darkMode
            window.grabWindow().save(str(GENERATED_DIR/'qml_smoke_queue_dark.png'))
            with patch('controller.play_reference') as play, patch.object(controller, 'spotifyNowPlaying'):
                controller.spotifyPlayback('play', 'spotify:track:b')
                wait_for(lambda: not controller._workers)
                assert play.call_args.args[1] == 'spotify:track:b'
            QMetaObject.invokeMethod(dialog, 'close')
            QTest.qWait(300)
            assert not controller._live_queue_timer.isActive()
        controller._playback_timer.stop()
        engine.deleteLater()
        app.processEvents()
print('LIVE_QUEUE_OK automatic_refresh single_request ordering repeats current_song local_data_unchanged failure_recovery legacy_labels dialog_lifecycle')
