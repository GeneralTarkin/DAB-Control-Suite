#!/usr/bin/env python3
"""
MWI-DAB-Server - DLS Poller

Ziel:
- genau ein Prozess liest DLS ueber radio_cli
- kein alter Radiotext nach Senderwechsel
- nach Senderwechsel schnell nach neuem Radiotext suchen
- zentrale Textdekodierung verwenden
- radio_cli nicht minutenlang oder 12 Sekunden am Stueck blockieren

Wichtig:
Der Dienst mwi-dab-radio-engine.service sollte deaktiviert bleiben.
Produktiver DLS-Datenfluss:
    dls_poller.py -> cache/dls.json -> metadata_worker.py -> API/WordPress
"""

import sys
sys.path.insert(0, ".")

import json
import subprocess
import time
from pathlib import Path

from config import RADIO_CLI
from services.metadata import parse_dls_text
from services.locks import cli_file_lock
from services.text_encoding import decode_radio_cli_bytes, normalize_dab_text

CACHE = Path("cache")
CACHE.mkdir(exist_ok=True)

OUT = CACHE / "dls.json"
LOG = CACHE / "dls_poller.log"
TUNING_LOCK = CACHE / "stream_tuning.lock"
LAST_STATION_FILE = CACHE / "last_station.json"

NOISE_PREFIXES = (
    "Starting...",
    "radio_cli",
    "Please note:",
    "SPI bus enabled.",
    "Running with",
    "Usage:",
    "Commands and options",
)


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return default


def write_json(data: dict) -> None:
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def current_station_index():
    data = read_json(LAST_STATION_FILE, {})
    try:
        return int(data.get("index"))
    except Exception:
        return None


def tuning_in_progress(max_age: int = 25) -> bool:
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


def clean_output(out: str) -> str:
    out = normalize_dab_text(out)
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    candidates = []

    for line in lines:
        if line.startswith(NOISE_PREFIXES):
            continue

        low = line.lower()
        if "software is property" in low:
            continue
        if "raspberry pi dab board" in low:
            continue
        if line.startswith("ERROR:"):
            continue
        if "not booted" in low:
            continue
        if "no firmware loaded" in low:
            continue
        if "please use the command boot first" in low:
            continue
        if "radio_cli ist gerade beschäftigt" in low:
            continue

        candidates.append(line)

    return normalize_dab_text(candidates[-1] if candidates else "")


def publish_empty(reason: str, station_index=None, alive: bool = True, empty_count: int = 0) -> None:
    write_json({
        "timestamp": time.time(),
        "alive": alive,
        "source": "radio_cli_poll",
        "station_text": "",
        "dls": parse_dls_text(""),
        "empty_count": empty_count,
        "last_result": reason,
        "station_index": station_index,
    })


def publish_text(text: str, raw: str, station_index, empty_count: int) -> None:
    text = normalize_dab_text(text)
    write_json({
        "timestamp": time.time(),
        "alive": True,
        "source": "radio_cli_poll",
        "station_text": text,
        "raw": raw,
        "dls": parse_dls_text(text),
        "empty_count": empty_count,
        "last_result": "ok",
        "station_index": station_index,
    })


def query_dls(waittime: int = 3):
    """
    Fragt DLS ab.

    waittime=3 ist der Kompromiss:
    - deutlich reaktionsfreudiger als -z 12
    - verlaesslicher als reine -z 1 Abfragen
    """
    if tuning_in_progress():
        raise RuntimeError("Tuning läuft - DLS übersprungen")

    with cli_file_lock(timeout=0):
        if tuning_in_progress():
            raise RuntimeError("Tuning läuft - DLS nach Lock übersprungen")

        result = subprocess.run(
            ["sudo", RADIO_CLI, "-D", "-z", str(waittime)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=waittime + 4,
        )

    raw = decode_radio_cli_bytes(result.stdout or b"")
    text = clean_output(raw)
    return raw, text


def main() -> None:
    last_station_index = current_station_index()
    empty_count = 0

    # Nach Senderwechsel aggressiver pollen, damit Radiotext schneller kommt.
    fast_until = time.time() + 10

    log("DLS Poller gestartet.")
    publish_empty("startup", station_index=last_station_index)

    while True:
        station_index = current_station_index()

        if station_index != last_station_index:
            last_station_index = station_index
            empty_count = 0
            fast_until = time.time() + 30

            # Wichtig: Sofort leeren, damit alter Radiotext nicht mehr angezeigt wird.
            publish_empty("station_changed", station_index=last_station_index)
            log(f"Senderwechsel erkannt - DLS gelöscht, station_index={last_station_index}")

            # Direkt weiterpollen, keine lange Pause nach Senderwechsel.
            time.sleep(0.2)
            continue

        try:
            raw, text = query_dls(waittime=3)

            if text:
                empty_count = 0
                publish_text(text, raw, last_station_index, empty_count)
                log(f"DLS OK: {text}")
                sleep_time = 1.0 if time.time() < fast_until else 2.0
            else:
                empty_count += 1

                # Wichtig:
                # Bei leerem Ergebnis NICHT den alten Text behalten.
                # Leere DLS bleibt leer, damit WordPress nicht alte Info zeigt.
                publish_empty("empty", station_index=last_station_index, empty_count=empty_count)
                log(f"DLS leer, empty_count={empty_count}")

                # Kein exponentielles/langes Backoff mehr.
                sleep_time = 0.7 if time.time() < fast_until else 2.0

        except Exception as exc:
            empty_count += 1
            publish_empty("error", station_index=last_station_index, alive=False, empty_count=empty_count)
            log(f"ERROR: {exc}")

            # Auch bei Busy nicht 5-10 Sekunden warten.
            sleep_time = 0.7 if time.time() < fast_until else 2.0

        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
