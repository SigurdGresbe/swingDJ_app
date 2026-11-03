import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QObject, QMetaObject, Q_ARG, QModelIndex, Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
import field_store, tempo_store
from table_model import SongTableModel
from controller import AppController
QQuickStyle.setStyle('Basic')
app=QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
app.setFont(QFont('Segoe UI',10))
with TemporaryDirectory() as folder, patch.object(field_store,'PATH',Path(folder)/'fields.json'), patch.object(tempo_store,'PATH',Path(folder)/'tempos.json'), patch('controller.load_settings',return_value={'viewer_file':'absent'}), patch('controller.save_settings'):
    model=SongTableModel()
    model.set_frame(pd.DataFrame([{'Track Name':'Song A','Spotify URI':'spotify:track:a','Style':'Swing','Theme':'Party'}, {'Track Name':'Song B','Spotify URI':'spotify:track:b','Style':'Blues; Boogie','Theme':'Winter'}]),'list.xlsx')
    controller=AppController(model)
    controller._playback_timer.stop()
    assert model.tagChoices('Style')==['Blues','Boogie','Swing']
    before=model.rowRecord(0)
    style=model.visibleColumns.index('Style')
    assert not model.editCell(0,style,'Invented style')
    assert model.rowRecord(0)==before
    assert model.editCell(0,style,'blues; SWING; Blues')
    assert model.rowRecord(0)['Style']=='Blues; Swing'
    assert not model.editCell(0,style,'Blues; Party')
    assert model.editCell(0,style,'')
    assert 'Swing' in model.tagChoices('Style')
    assert not model.validateTagEdit('Theme','Swing')['valid']
    model.setColumnVisible('Spotify URI',False)
    style=model.visibleColumns.index('Style')
    engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('controller',controller)
    engine.rootContext().setContextProperty('tableModel',model)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'qml/Main.qml')))
    assert engine.rootObjects()
    window=engine.rootObjects()[0]
    table=window.findChild(QObject,'songTable')
    QTest.qWait(300)
    assert QMetaObject.invokeMethod(table,'edit',Q_ARG(QModelIndex,model.index(0,style)))
    QTest.qWait(300)
    dialog=window.findChild(QObject,'tagEditDialog')
    assert dialog.property('visible')
    edit=window.findChild(QObject,'tagEditInput')
    edit.setProperty('text','Bl')
    QTest.keyClick(window,Qt.Key_Tab)
    QTest.qWait(50)
    assert edit.property('text')=='Blues; '
    edit.setProperty('text','Blues; Sw')
    QTest.keyClick(window,Qt.Key_Tab)
    assert edit.property('text')=='Blues; Swing; '
    edit.setProperty('text','Bad')
    QTest.qWait(20)
    assert not window.findChild(QObject,'saveTagEdit').property('enabled')
    edit.setProperty('text','Blues; Swing')
    QTest.qWait(20)
    assert window.findChild(QObject,'saveTagEdit').property('enabled')
    QMetaObject.invokeMethod(dialog,'saveTags')
    QTest.qWait(200)
    assert model.rowRecord(0)['Style']=='Blues; Swing'
    reloaded=SongTableModel()
    reloaded.set_frame(pd.DataFrame([{'Track Name':'Song A','Spotify URI':'spotify:track:a','Style':'Swing','Theme':'Party'}]),'list.xlsx')
    assert reloaded.rowRecord(0)['Style']=='Blues; Swing'
    controller._playback_timer.stop()
print('TAG_EDITING_OK predefined_validation case_normalization multi_tags dropdown Tab_completion persistence actual_table_editor')
