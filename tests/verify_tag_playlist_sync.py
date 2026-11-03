import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from controller import AppController
from table_model import SongTableModel
from spotify_tools import preview_tag_playlist_additions, add_previewed_tag_songs
import field_store, tempo_store

class Client:
    def __init__(self):
        self.members={"blues":{"spotify:track:already"},"party":set()}
        self.posts=[]
        self.fail=False
    def current_user(self): return {"id":"me"}
    def current_user_playlists(self,limit,offset):
        items=[{"id":"blues","name":"Stil: Blues","owner":{"id":"me"}},
               {"id":"party","name":"Tema: Party","owner":{"id":"me"}},
               {"id":"other","name":"Stil: Other","owner":{"id":"other"}},
               {"id":"d1","name":"Tema: Duplicate","owner":{"id":"me"}},
               {"id":"d2","name":"Tema: Duplicate","owner":{"id":"me"}}]
        return {"items":items[:2] if offset==0 else items[2:],"next":"next" if offset==0 else None}
    def playlist_items(self,playlist_id,**kwargs):
        return {"items":[{"track":{"uri":uri}} for uri in self.members[playlist_id]],"next":None}
    def _post(self,url,payload):
        playlist_id=url.split("/")[1]
        if self.fail and playlist_id=="party": raise TimeoutError("lost response")
        self.posts.append((playlist_id,payload["uris"]))
        self.members[playlist_id].update(payload["uris"])

changes=[{"column":"Style","tag":"Blues","uri":"spotify:track:already","name":"Already"},
         {"column":"Style","tag":"Blues","uri":"spotify:track:a","name":"A"},
         {"column":"Style","tag":"Blues","uri":"spotify:track:a","name":"A"},
         {"column":"Theme","tag":"Party","uri":"spotify:track:a","name":"A"},
         {"column":"Theme","tag":"Missing","uri":"spotify:track:a","name":"A"},
         {"column":"Theme","tag":"Duplicate","uri":"spotify:track:a","name":"A"},
         {"column":"Style","tag":"Other","uri":"spotify:track:a","name":"A"}]
client=Client()
with patch("spotify_tools.build_spotify_client",return_value=client):
    preview=preview_tag_playlist_additions(None,changes)
    assert preview["count"]==2 and preview["already_present"]==1
    assert len(preview["issues"])==3 and not client.posts
    client.fail=True
    result=add_previewed_tag_songs(None,preview)
    assert result["added"]==1 and len(result["failures"])==1
    client.fail=False
    retry=add_previewed_tag_songs(None,preview)
    assert retry["added"]==1 and retry["skipped"]==1
    assert len(client.posts)==2
    preview2=preview_tag_playlist_additions(None,changes)
    assert preview2["count"]==0
    bulk={"playlists":[{"id":"blues","name":"Stil: Blues","uris":[f"spotify:track:bulk{i}" for i in range(205)]}]}
    add_previewed_tag_songs(None,bulk)
    assert [len(uris) for _,uris in client.posts[-3:]]==[100,100,5]

app=QApplication([])
with TemporaryDirectory() as folder, patch.object(field_store,"PATH",Path(folder)/"fields.json"), patch.object(tempo_store,"PATH",Path(folder)/"tempos.json"), patch("controller.load_settings",return_value={"viewer_file":"absent"}), patch("controller.save_settings"):
    field_store._save({"edits":{"spotify:track:a":{"Style":"Swing; Blues","Theme":"Party"}},"originals":{"spotify:track:a":{"Track Name":"A","Style":"Swing","Theme":"Winter"}}})
    controller=AppController(SongTableModel())
    controller._playback_timer.stop()
    additions=controller._changed_tag_additions()
    assert {(item["column"],item["tag"]) for item in additions}=={("Style","Blues"),("Theme","Party")}
    controller._tag_sync_preview={"count":1}
    controller._tag_sync_changes=[]
    with patch("controller.add_previewed_tag_songs") as add:
        controller.addChangedTagsToSpotify()
        add.assert_not_called()
print("TAG_SYNC_OK paginated_discovery preview_only matching permissions duplicate_guard partial_failure retry batching edited_tag_deltas stale_preview")
