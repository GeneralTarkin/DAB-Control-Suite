#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

import json
import subprocess
import time
from pathlib import Path

from config import RADIO_CLI
from services.locks import cli_file_lock
from services.text_encoding import normalize_dab_text

CACHE = Path("cache")
CACHE.mkdir(exist_ok=True)

OUT = CACHE / "ensemble.json"
LOG = CACHE / "ensemble_worker.log"
LAST_STATION_FILE = CACHE / "last_station.json"
TUNING_LOCK = CACHE / "stream_tuning.lock"


def log(msg):
    with LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def write_json(data):
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def current_station_index():
    data = read_json(LAST_STATION_FILE, {})
    try:
        return int(data.get("index"))
    except Exception:
        return None


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


def query_ensemble():
    if tuning_in_progress():
        raise RuntimeError("Tuning läuft - Ensemble-Abfrage übersprungen")

    with cli_file_lock(timeout=1):
        if tuning_in_progress():
            raise RuntimeError("Tuning läuft - Ensemble-Abfrage nach Lock übersprungen")

        result = subprocess.run(
            ["sudo", RADIO_CLI, "-G"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=8,
        )

    out = (result.stdout or b"").decode("utf-8", errors="replace")

    label = ""
    info = {}

    for line in out.splitlines():
        line = line.strip()

        if line.startswith("Label:"):
            label = line.split(":", 1)[1].strip()
        elif line.startswith("Ensemble ID"):
            info["ensemble_id"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line.startswith("Extended Country Code"):
            info["ecc"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line.startswith("Label Abbreviation Mask"):
            info["abrev"] = line.split(":", 1)[1].strip() if ":" in line else ""

    label = normalize_dab_text(label)

    if not label:
        raise RuntimeError("Ensemble-Abfrage lieferte kein Label")

    return {
        "timestamp": time.time(),
        "alive": True,
        "label": label,
        **info,
    }


def publish_error_preserve_last(exc, station_index):
    old = read_json(OUT, {})
    label = normalize_dab_text(old.get("label") or "")

    # Wichtig:
    # Niemals ein gültiges Ensemble-Label mit leerem Text überschreiben.
    # Bei Busy/Tuning bleibt der letzte gültige Wert sichtbar.
    if label:
        old["timestamp"] = time.time()
        old["alive"] = False
        old["error"] = str(exc)
        old["last_result"] = "error_preserved"
        old["station_index"] = old.get("station_index", station_index)
        write_json(old)
    else:
        write_json({
            "timestamp": time.time(),
            "alive": False,
            "error": str(exc),
            "label": "",
            "last_result": "error_no_previous_label",
            "station_index": station_index,
        })


def main():
    last_index = None
    pending_retry_until = 0.0

    log("Ensemble Worker gestartet.")

    while True:
        idx = current_station_index()

        # Bei Senderwechsel nicht sofort alte Daten löschen.
        # Das neue Label wird erst nach erfolgreicher Abfrage ersetzt.
        if idx != last_index:
            last_index = idx
            pending_retry_until = time.time() + 30
            log(f"Senderwechsel erkannt - Ensemble-Abfrage geplant, station_index={idx}")

        should_try = False

        if time.time() < pending_retry_until:
            should_try = True
        else:
            current = read_json(OUT, {})
            if current.get("station_index") != idx or not current.get("label"):
                should_try = True

        if should_try:
            try:
                # Direkt nach Tuning kurz warten, damit -G nicht mit Fast-Tune kollidiert.
                if tuning_in_progress():
                    raise RuntimeError("Tuning läuft - Ensemble-Abfrage übersprungen")

                data = query_ensemble()
                data["station_index"] = idx
                data["last_result"] = "ok"
                write_json(data)
                log(f"Ensemble OK: {data.get('label')} station_index={idx}")
                pending_retry_until = 0.0

            except Exception as exc:
                publish_error_preserve_last(exc, idx)
                log(f"ERROR: {exc}")

        time.sleep(2)


if __name__ == "__main__":
    main()
