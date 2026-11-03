"""Failure-path checks; use temporary storage and mocked network requests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import config, tempo_store, table_io, lastfm_tools, error_reports
from controller import AppController
from table_model import SongTableModel
from spotify_tools import build_spotify_client, SpotifySettings

app = QApplication([])
with TemporaryDirectory() as folder:
    root = Path(folder)
    with patch.object(tempo_store, 'PATH', root / 'listening.json'):
        tempo_store.PATH.write_text('{broken', encoding='utf-8')
        assert tempo_store.load()['plan'] == []
        assert (root / 'listening.corrupt.json').read_text() == '{broken'
        tempo_store.save({'history': [], 'plan': [{'name': 'Song'}], 'corrections': {}})
        assert tempo_store.load()['plan'][0]['name'] == 'Song'
    with patch.object(config, 'SETTINGS_PATH', root / 'settings.json'):
        config.save_settings({'theme': 'Night'})
        assert 'Night' in config.SETTINGS_PATH.read_text()
    target = root / 'list.csv'
    target.write_text('original', encoding='utf-8')
    with patch.object(pd.DataFrame, 'to_csv', side_effect=OSError('disk full')):
        try: table_io.write_table_file(pd.DataFrame({'A': [1]}), target)
        except OSError: pass
        else: raise AssertionError('Expected write failure')
    assert target.read_text() == 'original'
    assert list(root.glob('*.csv')) == [target]
    with patch.object(lastfm_tools, 'urlopen', side_effect=TimeoutError()) as request:
        try: lastfm_tools._request({'method': 'artist.getsimilar'})
        except TimeoutError: pass
        assert request.call_args.kwargs['timeout'] == 15
    with patch('spotify_tools.ConcurrentSpotifyOAuth') as oauth, patch('spotify_tools.CurrentSpotifyClient') as client:
        build_spotify_client(SpotifySettings('id', 'secret', 'http://127.0.0.1', [], cache_path=root/'cache'))
        assert oauth.call_args.kwargs['requests_timeout'] == 15
        assert client.call_args.kwargs['retries'] == 0
    with patch.object(error_reports, 'PATH', root/'errors.jsonl'), patch('controller.load_settings', return_value={}), patch('controller.save_settings'), patch('controller.tempo_store.load', return_value={'history': [], 'plan': [], 'corrections': {}}):
        controller = AppController(SongTableModel())
        controller._playback_timer.stop()
        def broken_completion(result): raise ValueError('completion failed')
        controller._run_task('test completion', lambda: 42, broken_completion)
        for _ in range(100):
            QTest.qWait(10)
            if not controller._workers: break
        assert controller._busy_count == 0 and not controller._workers
        assert 'completion failed' in controller.statusMessage
        with patch('controller.get_playback_state', side_effect=TimeoutError()):
            controller._fetch_playback()
            for _ in range(100):
                QTest.qWait(10)
                if not controller._playback_pending: break
        assert controller._playback['stale'] and controller._playback_timer.interval() == 10000
        with patch('controller.get_playback_state', return_value={'track_name': 'Recovered'}):
            controller._fetch_playback()
            for _ in range(100):
                QTest.qWait(10)
                if not controller._playback_pending: break
        assert controller._playback['track_name'] == 'Recovered'
        assert controller._playback_timer.interval() == 5000
        controller._playback_timer.stop()
print('ROBUSTNESS_OK corrupt_storage atomic_exports network_timeouts callback_errors playback_recovery')
