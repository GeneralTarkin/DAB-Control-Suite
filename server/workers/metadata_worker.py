#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

import json
import time
from pathlib import Path

from services.metadata import (
    get_digrad_status,
    get_event_status,
    get_ensemble_info,
    get_station_text,
    parse_dls_text,
)
from services.song_parser import parse_song, interpret_dls
from services.history import add_song

CACHE = Path("cache")
CACHE.mkdir(exist_ok=True)

METADATA_OUT = CACHE / "metadata.json"
LAST_STATION_FILE = CACHE / "last_station.json"
DLS_CACHE_FILE = CACHE / "dls.json"
TUNING_LOCK = CACHE / "stream_tuning.lock"

# Letzte gueltige Werte bleiben erhalten, bis neue gueltige Werte kommen.
# Wichtig: Beim Senderwechsel wird DLS bewusst geloescht, damit kein alter
# Radiotext des vorherigen Senders stehen bleibt.
last_digrad_status = {}
last_event_status = {}
last_ensemble_info = {}

last_station_index = None
last_station_text = ""
last_dls_timestamp = None
empty_count = 0
last_cache_payload = None


def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def current_station_index():
    data = read_json(LAST_STATION_FILE, {})
    try:
        return int(data.get("index"))
    except Exception:
        return None


def write_cache(data):
    """Schreibt den Cache atomar, damit die API nie halbfertige JSON-Daten liest."""
    tmp = METADATA_OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(METADATA_OUT)


def tuning_in_progress(max_age=25):
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


def read_dls_cache(expected_station_index=None):
    data = read_json(DLS_CACHE_FILE, {})
    if expected_station_index is not None:
        try:
            dls_station_index = int(data.get("station_index"))
        except Exception:
            dls_station_index = None

        if dls_station_index != expected_station_index:
            return "", None

    text = data.get("station_text") or ""
    ts = data.get("timestamp")
    return text, ts


def is_valid_mapping(value):
    return isinstance(value, dict) and bool(value)


def has_useful_digrad(status):
    if not isinstance(status, dict) or not status:
        return False
    useful_keys = ("valid", "acq", "FIC_quality", "snr", "rssi", "cnr", "tune_freq", "tune_index")
    return any(status.get(k) not in (None, "") for k in useful_keys)


def is_dab_service_active(digrad_status, ensemble_info):
    if not digrad_status:
        return False

    if digrad_status.get("valid") == 1:
        return True

    if digrad_status.get("acq") == 1:
        return True

    fic_quality = digrad_status.get("FIC_quality")
    if isinstance(fic_quality, (int, float)) and fic_quality > 0:
        return True

    snr = digrad_status.get("snr")
    if isinstance(snr, (int, float)) and snr > 0:
        return True

    rssi = digrad_status.get("rssi")
    if isinstance(rssi, (int, float)) and rssi > 0:
        return True

    if ensemble_info and ensemble_info.get("label"):
        return True

    return False


def reset_dls_state():
    global last_station_text, last_dls_timestamp, empty_count
    last_station_text = ""
    last_dls_timestamp = None
    empty_count = 0


def build_metadata_payload():
    global last_digrad_status, last_event_status, last_ensemble_info
    global last_station_index, last_station_text, last_dls_timestamp, empty_count

    idx = current_station_index()

    if idx != last_station_index:
        last_station_index = idx
        reset_dls_state()

    if tuning_in_progress():
        raise RuntimeError("Tuning läuft - Metadata-Abfrage übersprungen")

    digrad_status = get_digrad_status()
    event_status = get_event_status()
    ensemble_info = get_ensemble_info()

    # Nur gueltige neue Daten uebernehmen. Kurze Aussetzer loeschen nicht mehr
    # die letzten bekannten Empfangswerte.
    if has_useful_digrad(digrad_status):
        last_digrad_status = digrad_status

    if is_valid_mapping(event_status):
        last_event_status = event_status

    if is_valid_mapping(ensemble_info) and ensemble_info.get("label"):
        last_ensemble_info = ensemble_info

    # Wichtig: Der Metadata-Worker ruft radio_cli fuer DLS NICHT mehr direkt auf.
    # DLS kommt ausschliesslich aus dem separaten, kurzen dls_poller.py.
    station_text, station_ts = read_dls_cache(idx)

    if station_text:
        last_station_text = station_text
        last_dls_timestamp = station_ts or time.time()
        empty_count = 0
    else:
        empty_count += 1

    dls_age = None
    if last_dls_timestamp:
        dls_age = round(time.time() - last_dls_timestamp, 1)

    service_active = is_dab_service_active(last_digrad_status, last_ensemble_info)

    # Anzeige: letzter gueltiger DLS bleibt stehen, bis ein neuer kommt oder
    # beim Senderwechsel reset_dls_state() greift.
    visible_station_text = last_station_text
    has_dls = bool(visible_station_text)

    dls = parse_dls_text(visible_station_text)
    dls_interpretation = interpret_dls(visible_station_text)

    radio_state = {
        "service_active": service_active,
        "has_dls": has_dls,
        "dls_age_seconds": dls_age,
        "dls_empty_count": empty_count,
        "dls_source": "dls_poller",
        "station_index": last_station_index,
    }

    metadata = {
        "station_text": visible_station_text,
        "dls": dls,
        "dls_interpretation": dls_interpretation,
        "radio_state": radio_state,
        "digrad_status": last_digrad_status,
        "event_status": last_event_status,
        "ensemble_info": last_ensemble_info,
    }

    song = None
    if has_dls:
        song = dls_interpretation.get("now_playing") or parse_song(visible_station_text)

    if song:
        add_song(song)

    return {
        "timestamp": time.time(),
        "alive": True,
        "metadata": metadata,
    }


def build_error_payload(exc):
    """Bei Fehlern letzten guten Payload behalten, aber alive/error aktualisieren."""
    global last_cache_payload

    if isinstance(last_cache_payload, dict):
        payload = dict(last_cache_payload)
        payload["timestamp"] = time.time()
        payload["alive"] = False
        payload["error"] = str(exc)
        return payload

    return {
        "timestamp": time.time(),
        "alive": False,
        "error": str(exc),
        "metadata": {
            "station_text": "",
            "dls": parse_dls_text(""),
            "dls_interpretation": interpret_dls(""),
            "radio_state": {
                "service_active": False,
                "has_dls": False,
                "dls_age_seconds": None,
                "dls_empty_count": empty_count,
                "dls_source": "dls_poller",
                "station_index": last_station_index,
            },
            "digrad_status": last_digrad_status,
            "event_status": last_event_status,
            "ensemble_info": last_ensemble_info,
        },
    }


def main():
    global last_cache_payload

    while True:
        try:
            payload = build_metadata_payload()
            last_cache_payload = payload
            write_cache(payload)

        except Exception as exc:
            write_cache(build_error_payload(exc))

        time.sleep(3)


if __name__ == "__main__":
    main()
