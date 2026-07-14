#!/usr/bin/env python3
import sys
sys.path.insert(0, ".")

import json
import subprocess
import time
from pathlib import Path

from config import RADIO_CLI
from services.metadata import parse_dls_text

CACHE = Path("cache")
CACHE.mkdir(exist_ok=True)

OUT = CACHE / "dls.json"
DEBUG = CACHE / "dls_listener_raw.log"


NOISE_PREFIXES = (
    "Starting...",
    "radio_cli",
    "Please note:",
    "SPI bus enabled.",
    "Running with",
    "Usage:",
    "Commands and options",
)


def write_json(data):
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(OUT)


def is_dls_line(line):
    if not line:
        return False

    if line.startswith(NOISE_PREFIXES):
        return False

    if "software is property" in line:
        return False

    if "Raspberry Pi DAB Board" in line:
        return False

    return True


def run_listener():
    while True:
        try:
            cmd = ["sudo", RADIO_CLI, "-D", "-z", "999999"]

            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="latin-1",
                errors="replace",
                bufsize=1,
            ) as proc:
                for raw_line in proc.stdout:
                    line = raw_line.strip()

                    with DEBUG.open("a", encoding="utf-8", errors="replace") as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")

                    if not is_dls_line(line):
                        continue

                    dls = parse_dls_text(line)

                    write_json({
                        "timestamp": time.time(),
                        "alive": True,
                        "station_text": line,
                        "dls": dls,
                    })

        except Exception as exc:
            write_json({
                "timestamp": time.time(),
                "alive": False,
                "error": str(exc),
            })

        time.sleep(2)


if __name__ == "__main__":
    run_listener()
