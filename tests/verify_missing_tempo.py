import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from table_model import SongTableModel
from controller import AppController
import tempo_store
app = QApplication([])
with TemporaryDirectory() as folder, patch.object(tempo_store, "PATH", Path(folder)/"listening.json"), patch("controller.load_settings", return_value={"viewer_file": "absent.csv"}), patch("controller.save_settings"):
    model = SongTableModel()
    model.set_frame(pd.DataFrame([
        {"Track Name": "Blank", "Artist(s)": "A", "BPM": "", "KOD": ""},
        {"Track Name": "Known BPM", "BPM": 120, "KOD": ""},
        {"Track Name": "Known KOD", "BPM": "", "KOD": 75},
        {"Track Name": "Invalid", "BPM": float("inf"), "KOD": -1},
        {"Track Name": "Zero", "BPM": 0, "KOD": "unknown"},
    ]))
    assert model.missingTempoCount == 3
    model.setMissingTempoOnly(True)
    assert model.rowCount() == 3
    model.setFilter("All columns", "Blank", False)
    assert model.rowCount() == 1
    record = model.rowRecord(0)
    controller = AppController(model)
    controller._playback_timer.stop()
    model.setMissingTempoOnly(True)
    model.setFilter("All columns", "Blank", False)
    assert controller.correctSongTempo(record, "128", "BPM")
    assert model.rowCount() == 0 and model.missingTempoCount == 2
    model.clearFilter()
    assert model.rowCount() == 2
    model.setMissingTempoOnly(False)
    assert model.rowCount() == 5
    saved = tempo_store.load()["corrections"][tempo_store.key(tempo_store.song(record))]
    assert saved["bpm"] == 128 and saved["kod"] == 64
    with patch("controller.QDesktopServices.openUrl", return_value=True) as opened:
        controller.lookupSongTempo(record)
        assert "Blank" in opened.call_args.args[0].toString()
    no_columns = SongTableModel()
    no_columns.set_frame(pd.DataFrame({"Track Name": ["No tempo column"]}))
    no_columns.setMissingTempoOnly(True)
    assert no_columns.rowCount() == no_columns.missingTempoCount == 1
print("MISSING_TEMPO_OK invalid_values combined_filters persisted_correction lookup no_tempo_columns")
