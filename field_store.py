"""Persistent cell overrides and source values, keyed by Spotify URI or local row."""
import json
import threading
import tempfile
from pathlib import Path
from config import LOCAL_DATA_DIR
PATH = LOCAL_DATA_DIR / "field_edits.json"
_LOCK = threading.RLock()

def identity(record, path, index):
    uri = record.get("Spotify URI", record.get("uri", ""))
    if isinstance(uri, str) and uri.startswith("spotify:"):
        return uri
    return f"file:{Path(path).resolve() if path else 'unsaved'}|row:{index}"

def load():
    with _LOCK:
        if not PATH.exists():
            return {"edits": {}, "originals": {}}
        data = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("edits"), dict) or not isinstance(data.get("originals"), dict):
            raise ValueError("Saved field edits are invalid. Preserve field_edits.json before repairing it.")
        return data

def _save(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=PATH.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
    try:
        temporary.replace(PATH)
    finally:
        temporary.unlink(missing_ok=True)

def remember(frame, path, refresh=False):
    # JSON-normalize pandas scalars and missing values.
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    with _LOCK:
        data = load()
        for index, record in enumerate(records):
            key = identity(record, path, index)
            if refresh or key not in data["originals"]:
                data["originals"][key] = record
        _save(data)

def edit(key, column, value):
    with _LOCK:
        data = load()
        data["edits"].setdefault(key, {})[column] = value
        _save(data)

def reset(key, columns):
    with _LOCK:
        data = load()
        changes = data["edits"].get(key, {})
        for column in columns:
            changes.pop(column, None)
        if not changes:
            data["edits"].pop(key, None)
        _save(data)

def apply(frame, path):
    data = load()
    frame = frame.copy()
    for index, record in frame.iterrows():
        key = identity(record.to_dict(), path, index)
        for column, value in data["edits"].get(key, {}).items():
            if column in frame:
                frame[column] = frame[column].astype(object)
                frame.at[index, column] = value
    return frame
