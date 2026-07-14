#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

import json
import re
import subprocess
import time
from pathlib import Path

from config import RADIO_CLI
from services.metadata import parse_dls_text
from services.text_encoding import normalize_dab_text
from services.locks import cli_file_lock

CACHE = Path("cache")
CACHE.mkdir(exist_ok=True)

OUT = CACHE / "dls.json"
LOG = CACHE / "radio_engine.log"
TUNING_LOCK = CACHE / "stream_tuning.lock"


def log(message):
    with LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


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


def write_json(data):
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(OUT)


def clean_output(out):
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    candidates = []

    for line in lines:
        if line.startswith(("Starting", "radio_cli", "Please note:", "SPI bus", "Running with")):
            continue
        if "software is property" in line:
            continue
        candidates.append(line)

    return candidates[-1] if candidates else ""


def fix_dls_text(text):
    """Zentrale DAB-Textreparatur verwenden."""
    return normalize_dab_text(text or "").strip()

def query_dls(waittime=12):
    """
    DLS-Abfrage mit kurzen Blöcken.

    Verhindert, dass radio_cli -D -z 12 beim Senderwechsel den Tuner blockiert.
    Gleichzeitig sind 3-Sekunden-Blöcke zuverlässiger als reine 1-Sekunden-Abfragen.
    """
    if tuning_in_progress():
        return "", ""

    chunks = []
    slice_seconds = 3
    loops = max(1, int(waittime / slice_seconds))

    for _ in range(loops):
        if tuning_in_progress():
            break

        try:
            with cli_file_lock(timeout=0.05):
                if tuning_in_progress():
                    break

                result = subprocess.run(
                    ["sudo", RADIO_CLI, "-D", "-z", str(slice_seconds)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=slice_seconds + 4,
                )

            raw_part = (result.stdout or b"").decode("latin-1", errors="replace")
            if raw_part:
                chunks.append(raw_part)

            text = fix_dls_text(clean_output("\n".join(chunks)))
            if text:
                return "\n".join(chunks), text

        except TimeoutError:
            break
        except subprocess.TimeoutExpired:
            break
        except Exception as exc:
            log(f"DLS slice error: {exc}")
            break

        time.sleep(0.2)

    raw = "\n".join(chunks)
    text = fix_dls_text(clean_output(raw))
    return raw, text

def main():
    last_text = ""
    empty_count = 0

    log("Radio Engine gestartet.")

    while True:
        try:
            raw, text = query_dls(waittime=12)

            if text:
                last_text = text
                empty_count = 0
                alive = True
                log(f"DLS OK: {text}")
            else:
                empty_count += 1
                alive = True
                log(f"DLS leer, empty_count={empty_count}")

            write_json({
                "timestamp": time.time(),
                "alive": alive,
                "source": "radio_engine",
                "station_text": last_text,
                "dls": parse_dls_text(last_text),
                "empty_count": empty_count,
                "last_result": "ok" if text else "empty",
            })

            time.sleep(2 if text else min(10, 2 + empty_count))

        except Exception as exc:
            empty_count += 1
            log(f"ERROR: {exc}")

            write_json({
                "timestamp": time.time(),
                "alive": False,
                "source": "radio_engine",
                "error": str(exc),
                "station_text": last_text,
                "dls": parse_dls_text(last_text),
                "empty_count": empty_count,
                "last_result": "error",
            })

            time.sleep(5)


if __name__ == "__main__":
    main()
