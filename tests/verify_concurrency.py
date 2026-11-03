"""Concurrent import safety and measured progress without live Spotify writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import threading
import time
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from controller import AppController
from table_model import SongTableModel
import tempo_store, error_reports

app = QApplication([])
def wait_for(condition):
    for _ in range(1000):
        QTest.qWait(10)
        time.sleep(0.005)
        if condition(): return
    raise AssertionError('Task did not finish')

with TemporaryDirectory() as folder:
    root = Path(folder)
    started, release = threading.Event(), threading.Event()
    progress_seen = []
    def import_table(settings, progress, **kwargs):
        started.set()
        assert release.wait(15)
        progress('Reading tagged playlists', 1, 2, '3 unique songs')
        return pd.DataFrame({'Track Name': ['Imported']}), {'tracks': 1, 'style_playlists': 1, 'event_playlists': 0, 'theme_playlists': 0, 'kod_tracks': 0}
    with patch('controller.GENERATED_DIR', root), patch('controller.load_settings', return_value={'viewer_file': str(root/'absent.csv')}), patch('controller.save_settings'), patch.object(tempo_store, 'PATH', root/'listening.json'), patch.object(error_reports, 'PATH', root/'errors.jsonl'), patch('controller.build_tagged_playlist_table', side_effect=import_table) as build:
        model = SongTableModel()
        model.set_frame(pd.DataFrame({'Track Name': ['Original']}))
        controller = AppController(model)
        controller._playback_timer.stop()
        controller.updateProgressChanged.connect(lambda: progress_seen.append(dict(controller.updateProgress)))
        controller.spotifyBuildTaggedList()
        wait_for(started.is_set)
        assert controller.taggedUpdateRunning and controller.working and not controller.busy
        controller.spotifyBuildTaggedList()
        assert build.call_count == 1
        completed = []
        controller._run_task('Independent search', lambda: 'found', completed.append)
        wait_for(lambda: completed == ['found'])
        assert controller.taggedUpdateRunning
        try: controller._ensure_safe_output(root/'Spotify_Style_Theme_Tags.xlsx')
        except ValueError: pass
        else: raise AssertionError('Conflicting output allowed')
        controller._ensure_safe_output(root/'other.xlsx')
        model.set_frame(pd.DataFrame({'Track Name': ['Newly opened']}))
        release.set()
        wait_for(lambda: not controller._workers)
        assert not controller.taggedUpdateRunning and not controller.working
        assert model.rowRecord(0)['Track Name'] == 'Newly opened'
        assert (root/'Spotify_Style_Theme_Tags.xlsx').exists()
        assert any(p['completed'] == 1 and p['total'] == 2 for p in progress_seen)
        assert controller.updateProgress['completed'] == controller.updateProgress['total'] == 1
        # Failure releases the import lane and permits a retry.
        with patch('controller.build_tagged_playlist_table', side_effect=TimeoutError()):
            controller.spotifyBuildTaggedList()
            wait_for(lambda: not controller._workers)
        assert not controller.taggedUpdateRunning
        controller._playback_timer.stop()
print('CONCURRENCY_OK independent_tasks duplicate_guard output_guard preserve_current_list measured_progress failure_unlock')
