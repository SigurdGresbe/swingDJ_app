import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from table_model import SongTableModel, BACKGROUND_ROLE, FOREGROUND_ROLE, DARK_STYLE_COLORS
from controller import AppController
import tempo_store, field_store
app=QApplication([])
with TemporaryDirectory() as folder, patch.object(tempo_store,"PATH",Path(folder)/"tempo.json"), patch.object(field_store,"PATH",Path(folder)/"fields.json"), patch("controller.load_settings",return_value={"theme":"Night","viewer_file":"absent"}), patch("controller.save_settings"):
    model=SongTableModel()
    controller=AppController(model)
    controller._playback_timer.stop()
    model.set_frame(pd.DataFrame({"Track Name":["One","Two"],"Style":["Swing","Blues"]}))
    assert controller.darkMode and model._dark_theme
    assert model.data(model.index(0,0),BACKGROUND_ROLE)=="#1C211E"
    assert model.data(model.index(1,0),BACKGROUND_ROLE)=="#222825"
    assert model.data(model.index(0,0),FOREGROUND_ROLE)=="#F7F5F0"
    assert model.data(model.index(0,1),BACKGROUND_ROLE) in DARK_STYLE_COLORS
    assert model.legendEntries[0]["color"]=="#28513F"
    controller.setTheme("Paper")
    assert model.data(model.index(0,0),BACKGROUND_ROLE)=="#FFFFFF"
    controller.setTheme("Night")
    assert model.data(model.index(0,0),BACKGROUND_ROLE)=="#1C211E"
    model.setFilter("All columns","One",False)
    assert model.data(model.index(0,0),BACKGROUND_ROLE)=="#1C211E"
print("THEME_OK saved_night_startup rows text style_colors legend switching filtering")
