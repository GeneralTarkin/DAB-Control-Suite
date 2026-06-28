#!/usr/bin/env python3
import json
import re
import subprocess
from config import RADIO_CLI


def _run_radio_cli(args, timeout=8):
    try:
        result = subprocess.run(
            ["sudo", RADIO_CLI] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return result.stdout or ""
    except Exception as exc:
        return f"ERROR: {exc}"


def _extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def get_station_text(waittime=3):
    out = _run_radio_cli(["-D", "-z", str(waittime)], timeout=waittime + 4)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    noise = (
        "Starting...",
        "radio_cli",
        "Please note:",
        "SPI bus enabled.",
        "Running with",
    )
    clean = [l for l in lines if not l.startswith(noise)]
    return clean[-1] if clean else ""


def get_digrad_status():
    out = _run_radio_cli(["-d", "-j"], timeout=6)
    data = _extract_json(out)
    if not data:
        return {}
    return data.get("DigradStatus", {})


def get_event_status():
    out = _run_radio_cli(["-n", "-j"], timeout=6)
    data = _extract_json(out)
    if not data:
        return {}
    return data.get("EventStatus", {})


def get_ensemble_info():
    out = _run_radio_cli(["-G"], timeout=6)

    info = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Ensemble ID"):
            m = re.search(r":\s*(.+)$", line)
            if m:
                info["ensemble_id"] = m.group(1).strip()
        elif line.startswith("Label:"):
            info["label"] = line.split(":", 1)[1].strip()
        elif line.startswith("Extended Country Code"):
            info["ecc"] = line.split(":", 1)[1].strip()
        elif line.startswith("Label Abbreviation Mask"):
            info["abrev"] = line.split(":", 1)[1].strip()

    return info


def get_metadata(waittime=2):
    return {
        "station_text": get_station_text(waittime=waittime),
        "digrad_status": get_digrad_status(),
        "event_status": get_event_status(),
        "ensemble_info": get_ensemble_info(),
    }
