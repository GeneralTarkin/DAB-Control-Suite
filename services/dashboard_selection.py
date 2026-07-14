import json
import time
from pathlib import Path

try:
    from config import DASHBOARD_SELECTION_FILE
except Exception:
    DASHBOARD_SELECTION_FILE = Path("cache/dashboard_stations.json")

SELECTION_FILE = Path(DASHBOARD_SELECTION_FILE)
SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)


def station_key(station):
    """Build a stable key for a DAB service without modifying the scan file."""
    return "|".join([
        str(station.get("tune_index", "")),
        str(station.get("tune_freq", "")),
        str(station.get("service_id", "")),
        str(station.get("component_id", "")),
        str(station.get("label", "")).strip(),
    ])


def _read_selection():
    if not SELECTION_FILE.exists():
        return {"version": 1, "initialized": False, "enabled_keys": []}

    try:
        data = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
        enabled = data.get("enabled_keys", [])
        if not isinstance(enabled, list):
            enabled = []
        return {
            "version": int(data.get("version", 1) or 1),
            "initialized": bool(data.get("initialized", False)),
            "enabled_keys": [str(x) for x in enabled],
            "updated_at": data.get("updated_at"),
        }
    except Exception:
        return {"version": 1, "initialized": False, "enabled_keys": []}


def _write_selection(enabled_keys):
    data = {
        "version": 1,
        "initialized": True,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "enabled_keys": sorted(set(str(x) for x in enabled_keys)),
    }
    tmp = SELECTION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SELECTION_FILE)
    return data


def selection_state(stations):
    """Return annotated stations and current selection metadata.

    Compatibility rule:
    - If no selection file exists yet, all currently known stations are shown in the dashboard.
    - Once the admin saves/toggles the selection, only selected keys are shown.
    - New stations after later scans remain unchecked until explicitly enabled.
    """
    data = _read_selection()
    keys = [station_key(s) for s in stations]

    if not data.get("initialized"):
        enabled = set(keys)
    else:
        enabled = set(data.get("enabled_keys", []))

    annotated = []
    for station, key in zip(stations, keys):
        item = dict(station)
        item["dashboard_key"] = key
        item["dashboard_enabled"] = key in enabled
        annotated.append(item)

    return {
        "initialized": bool(data.get("initialized")),
        "selection_file": str(SELECTION_FILE),
        "enabled_count": sum(1 for s in annotated if s.get("dashboard_enabled")),
        "total_count": len(annotated),
        "stations": annotated,
    }


def dashboard_stations(stations):
    state = selection_state(stations)
    return [s for s in state["stations"] if s.get("dashboard_enabled")]


def set_dashboard_enabled(stations, key, enabled):
    state = selection_state(stations)
    known_keys = {s["dashboard_key"] for s in state["stations"]}

    key = str(key or "")
    if key not in known_keys:
        raise ValueError("Unbekannter Sender-Schlüssel. Bitte Senderliste neu laden.")

    current_enabled = {s["dashboard_key"] for s in state["stations"] if s.get("dashboard_enabled")}
    if enabled:
        current_enabled.add(key)
    else:
        current_enabled.discard(key)

    _write_selection(current_enabled)
    return selection_state(stations)
