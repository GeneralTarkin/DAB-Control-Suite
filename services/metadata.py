import json
import re
import subprocess
import time
from pathlib import Path

from config import RADIO_CLI
from services.locks import cli_file_lock
from services.text_encoding import normalize_dab_text


CACHE = Path("cache")
DEBUG_DIR = CACHE / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

METADATA_CACHE = CACHE / "metadata.json"
DLS_CACHE = CACHE / "dls.json"
ENSEMBLE_CACHE = CACHE / "ensemble.json"
TUNING_LOCK = CACHE / "stream_tuning.lock"


def _read_json(path, default):
    try:
        path = Path(path)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def tuning_in_progress(max_age=30):
    try:
        if not TUNING_LOCK.exists():
            return False
        ts = float(TUNING_LOCK.read_text(encoding="utf-8", errors="replace") or 0)
        if time.time() - ts <= max_age:
            return True
        TUNING_LOCK.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def fix_dab_text_encoding(text):
    return normalize_dab_text(text)



def _extract_json(raw):
    if not raw:
        return {}

    text = raw.strip()
    start_positions = [p for p in (text.find("{"), text.find("[")) if p >= 0]
    if not start_positions:
        return {}

    candidate = text[min(start_positions):].strip()
    decoder = json.JSONDecoder()

    try:
        obj, _ = decoder.raw_decode(candidate)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _run_radio_json(args, timeout=5, lock_timeout=1.0):
    if tuning_in_progress():
        return {}

    try:
        with cli_file_lock(timeout=lock_timeout):
            if tuning_in_progress():
                return {}

            result = subprocess.run(
                ["sudo", RADIO_CLI] + list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )

        return _extract_json(result.stdout or "")

    except Exception:
        return {}

def get_station_text(waittime=5, retries=4):
    """Kompatibilität: DLS kommt ausschließlich aus cache/dls.json."""
    data = _read_json(DLS_CACHE, {})
    return normalize_dab_text(data.get("station_text") or "")


def get_digrad_status():
    """Liest die aktuellen DIGRAD-Empfangswerte direkt über radio_cli."""
    data = _run_radio_json(["-d", "-j"], timeout=4, lock_timeout=1.0)

    if not isinstance(data, dict):
        return {}

    status = data.get("DigradStatus")
    if isinstance(status, dict):
        return status

    return data


def get_event_status():
    """Liest den aktuellen DAB-Ereignisstatus direkt über radio_cli."""
    data = _run_radio_json(["-n", "-j"], timeout=4, lock_timeout=1.0)

    if not isinstance(data, dict):
        return {}

    status = data.get("EventStatus")
    if isinstance(status, dict):
        return status

    return data


def get_ensemble_info():
    """Liest Ensemble-Informationen aus cache/ensemble.json.

    Der Ensemble-Name wird von workers/ensemble_worker.py nur bei Sender-/Ensemblewechsel
    per radio_cli -G abgefragt. Diese Funktion selbst startet kein radio_cli.
    """
    data = _read_json(ENSEMBLE_CACHE, {})
    label = normalize_dab_text(data.get("label") or "")

    if not label:
        return {}

    return {
        "label": label,
        "ensemble_id": data.get("ensemble_id", ""),
        "ecc": data.get("ecc", ""),
        "abrev": data.get("abrev", ""),
        "station_index": data.get("station_index"),
        "timestamp": data.get("timestamp"),
    }


def parse_dls_text(text):
    if not text:
        return {
            "raw": "",
            "artist": "",
            "title": "",
            "station_hint": ""
        }

    raw = normalize_dab_text(text).strip()
    artist = ""
    title = ""
    station_hint = ""

    before = raw

    before = re.sub(
        r"(?i)^\s*(gerade läuft|jetzt läuft|now playing|now|aktuell|on air)\s*:\s*",
        "",
        before,
    )

    if " auf " in raw:
        before, station_hint = raw.rsplit(" auf ", 1)

    if " mit " in before:
        title, artist = before.split(" mit ", 1)
    elif " - " in before:
        artist, title = before.split(" - ", 1)
    elif " – " in before:
        artist, title = before.split(" – ", 1)
    else:
        title = before

    return {
        "raw": raw,
        "artist": artist.strip(),
        "title": title.strip(),
        "station_hint": station_hint.strip()
    }


def get_metadata(waittime=5):
    """Kompatibilitätsfunktion ohne direkte Hardwarezugriffe."""
    station_text = get_station_text()

    return {
        "station_text": station_text,
        "dls": parse_dls_text(station_text),
        "digrad_status": get_digrad_status(),
        "event_status": get_event_status(),
        "ensemble_info": get_ensemble_info(),
    }