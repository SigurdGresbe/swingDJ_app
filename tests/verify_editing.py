import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from table_model import SongTableModel, EDITED_ROLE
from controller import AppController
import tempo_store, field_store
app=QApplication([])
with TemporaryDirectory() as folder, patch.object(tempo_store,'PATH',Path(folder)/'tempos.json'), patch.object(field_store,'PATH',Path(folder)/'fields.json'), patch('controller.load_settings',return_value={'viewer_file':'absent'}), patch('controller.save_settings'):
    for value,result in [('30*2',60),('30.5 * 2',61),('30,5*2',61),('2*3*4',24)]:
        assert tempo_store.parse_tempo_input(value)==result
    for value in ['__import__("os")', '30**2','30/2','nan','-30*2','1e999','0*2','2*']:
        try: tempo_store.parse_tempo_input(value)
        except ValueError: pass
        else: raise AssertionError(value)
    frame=pd.DataFrame([{'Track Name':'One','Artist(s)':'Artist','Spotify URI':'spotify:track:one','KOD':30,'Style':'Swing'}, {'Track Name':'Two','Artist(s)':'Artist','Spotify URI':'spotify:track:two','KOD':45,'Style':'Blues'}, {'Track Name':'Three','Spotify URI':'spotify:track:three','KOD':80}])
    model=SongTableModel(); model.set_frame(frame,'source.xlsx')
    assert model.editCell(0,model.visibleColumns.index('Style'),'Blues')
    assert model.data(model.index(0,model.visibleColumns.index('Style')),EDITED_ROLE)
    refresh=frame.copy(); refresh.loc[0,'Style']='New Spotify style'
    field_store.remember(refresh,'source.xlsx',refresh=True)
    model.set_frame(refresh,'source.xlsx')
    assert model.rowRecord(0)['Style']=='Blues'
    request=model.fieldResetPreview(0,model.visibleColumns.index('Style'))
    assert request['original']=='New Spotify style'
    assert model.resetField(request)
    assert model.rowRecord(0)['Style']=='New Spotify style'
    assert not model.data(model.index(0,model.visibleColumns.index('Style')),EDITED_ROLE)
    controller=AppController(model); controller._playback_timer.stop()
    controller.previewBulkTempo('KOD','2',True,'1-2')
    assert controller.bulkTempoPreview['count']==2
    controller.applyBulkTempo()
    assert model.rowRecord(0)['KOD']=='60' and model.rowRecord(1)['KOD']=='90'
    assert model.data(model.index(0,model.visibleColumns.index('KOD')),EDITED_ROLE)
    controller.undoBulkTempo()
    assert model.rowRecord(0)['KOD']=='30' and model.rowRecord(1)['KOD']=='45'
    assert model.editCell(0,model.visibleColumns.index('KOD'),'30*2')
    assert model.rowRecord(0)['KOD']=='60'
    request=model.fieldResetPreview(0,model.visibleColumns.index('KOD'))
    assert request['linked'] and model.resetField(request)
    assert model.rowRecord(0)['KOD']=='30'
    controller.previewBulkTempo('KOD','2',True,'1')
    model.setFilter('All columns','Two',False)
    controller.applyBulkTempo()
    assert model.rowRecord(0)['KOD']=='45'
    assert tempo_store.kod_from_bpm(81)==81 and tempo_store.kod_from_bpm(160)==80
print('EDITING_OK arithmetic validation text_persistence latest_original reset_indicator bulk_preview apply undo stale_preview conversion')
