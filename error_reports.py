"""Persistent, credential-redacted diagnostic reports."""
from datetime import datetime, timezone
import json
import re
from config import LOCAL_DATA_DIR

PATH = LOCAL_DATA_DIR / "error_reports.jsonl"

def redact(message):
    message = re.sub(r"(?i)(access_token|refresh_token|client_secret|authorization|code)(\s*[=:]\s*)[^\s&,;]+", r"\1\2[redacted]", str(message))
    return re.sub(r"(?i)Bearer\s+[^\s]+", "Bearer [redacted]", message)

def append(action, message, secrets=()):
    message = str(message)
    for secret in secrets:
        if secret:
            message = message.replace(str(secret), "[redacted]")
    report = {"time": datetime.now(timezone.utc).isoformat(), "action": action, "message": redact(message)}
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False) + "\n")
    return report

def read():
    if not PATH.exists():
        return []
    reports = []
    try:
        lines = PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            report = json.loads(line)
            if isinstance(report, dict) and all(key in report for key in ("time", "action", "message")):
                reports.append(report)
        except json.JSONDecodeError:
            continue
    return reports
