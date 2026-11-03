"""Local listening history, ordered plans, and user-counted tempo overrides."""
import json
import math
import re
from config import LOCAL_DATA_DIR

PATH = LOCAL_DATA_DIR / "listening.json"

def kod_from_bpm(bpm):
    bpm = float(bpm)
    return bpm / 2 if bpm / 2 >= 60 else bpm

def load():
    if not PATH.exists():
        return {"history": [], "plan": [], "corrections": {}}
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid listening data")
        if not all(isinstance(data.get(k, default), type(default))
                   for k, default in (("history", []), ("plan", []), ("corrections", {}))):
            raise ValueError("Invalid listening data")
        for field in ("history", "plan"):
            data[field] = [normalize(row) for row in data.get(field, []) if isinstance(row, dict)]
        data.setdefault("corrections", {})
        data["corrections"] = {k: v for k, v in data["corrections"].items() if isinstance(v, dict)}
        return data
    except (ValueError, UnicodeError):
        # Preserve damaged data before allowing subsequent saves.
        backup = PATH.with_suffix(".corrupt.json")
        import shutil
        import time
        if backup.exists():
            backup = PATH.with_name(f"listening.{time.time_ns()}.corrupt.json")
        shutil.copy2(PATH, backup)
        return {"history": [], "plan": [], "corrections": {}}

def save(data):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PATH)

def song(record):
    values = {str(k).casefold(): "" if str(v).casefold() in ("nan", "none", "<na>") else str(v) for k, v in record.items()}
    return normalize({
        "name": values.get("track name", values.get("name", values.get("title", ""))),
        "artists": values.get("artist(s)", values.get("artists", values.get("subtitle", ""))),
        "uri": values.get("spotify uri", values.get("uri", "")),
        "bpm": values.get("bpm", ""), "kod": values.get("kod", ""),
    })

def normalize(row):
    row = dict(row)
    def tempo(value):
        try:
            number = float(value)
            return number if math.isfinite(number) and number > 0 else None
        except (ValueError, TypeError):
            return None
    bpm, kod = tempo(row.get("bpm")), tempo(row.get("kod"))
    row["bpm"] = bpm if bpm is not None else kod * 2 if kod is not None else ""
    row["kod"] = kod if kod is not None else kod_from_bpm(bpm) if bpm is not None else ""
    return row

def key(row):
    return row.get("uri") or (row["name"].casefold() + "|" + row["artists"].casefold())

def parse_tempo_input(value):
    """Accept numbers and bounded multiplication; never execute input as code."""
    text = str(value).strip().replace("\u00d7", "*")
    factors = text.split("*")
    if len(text) > 80 or not 1 <= len(factors) <= 8:
        raise ValueError("Enter a tempo or multiplication such as 30*2.")
    result = 1.0
    for factor in factors:
        factor = factor.strip()
        if not re.fullmatch(r"[+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?", factor):
            raise ValueError("Enter a tempo or multiplication such as 30*2.")
        number = float(factor.replace(",", "."))
        if not math.isfinite(number) or number <= 0:
            raise ValueError("Tempo factors must be positive, finite numbers.")
        result *= number
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Enter a positive, finite tempo.")
    return result


def validated_tempo(value, unit):
    if unit not in {"BPM", "KOD"}:
        raise ValueError("Choose BPM or KOD.")
    number = parse_tempo_input(value)
    if number > (400 if unit == "BPM" else 200):
        raise ValueError("Enter a positive tempo (BPM up to 400, KOD up to 200).")
    return number


def correct(row, value, unit):
    number = validated_tempo(value, unit)
    bpm = number if unit == "BPM" else number * 2
    data = load()
    data["corrections"][key(row)] = {"bpm": bpm, "kod": number if unit == "KOD" else kod_from_bpm(bpm)}
    save(data)

def apply(frame):
    overrides = load()["corrections"]
    if not overrides:
        return frame
    frame = frame.copy()
    for index, record in frame.iterrows():
        override = overrides.get(key(song(record.to_dict())))
        if override:
            for column, field in (("BPM", "bpm"), ("KOD", "kod")):
                if column not in frame:
                    frame[column] = ""
                frame[column] = frame[column].astype(object)
                frame.at[index, column] = override[field]
    return frame
