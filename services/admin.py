import json
import shutil
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request
from werkzeug.utils import secure_filename

from config import SCAN_FILE
from services.radio import load_stations, restore_scan_backup
from services.supervisor import supervisor
from services.logos import LOGO_DIR, logo_slug, logo_path_for_station
from services.dashboard_selection import selection_state, set_dashboard_enabled

admin_bp = Blueprint("admin", __name__)

STATE_FILE = Path("cache/admin_scan_state.json")
LOG_FILE = Path("logs/admin_scan.log")
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_scan_thread = None
ANALYZER_STATE_FILE = Path("cache/admin_analyzer_state.json")
ANALYZER_LOG_FILE = Path("logs/admin_analyzer.log")
_analyzer_thread = None


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def scan_file_info(path=SCAN_FILE):
    path = Path(path)
    try:
        st = path.stat()
        return {
            "exists": True,
            "path": str(path),
            "size": st.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        }
    except FileNotFoundError:
        return {"exists": False, "path": str(path), "size": None, "mtime": None}
    except Exception as exc:
        return {"exists": False, "path": str(path), "error": str(exc), "size": None, "mtime": None}


def _count_current_stations():
    try:
        return len(load_stations())
    except Exception:
        return 0


def _tail_log(lines=120):
    if not LOG_FILE.exists():
        return ""
    return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _append_log(text):
    with LOG_FILE.open("a", encoding="utf-8", errors="replace") as f:
        f.write(text)


def _base_state():
    return {
        "running": False,
        "phase": "idle",
        "ok": None,
        "message": "Bereit.",
        "started_at": None,
        "finished_at": None,
        "returncode": None,
        "backup_file": None,
        "command": ["supervisor.scan()"],
        "station_count": _count_current_stations(),
        "scan_file_info": scan_file_info(),
        "log_tail": _tail_log(),
    }


def _write_state(data):
    state = _base_state()
    state.update(data or {})
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)
    return state


def _read_state():
    if not STATE_FILE.exists():
        return _write_state({})
    try:
        old = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state = _base_state()
        state.update(old)
        state["scan_file_info"] = scan_file_info()
        state["station_count"] = _count_current_stations()
        state["log_tail"] = _tail_log()
        return state
    except Exception:
        return _write_state({"message": "Statusdatei konnte nicht gelesen werden."})


def _scan_worker(started_at):
    def log(msg):
        _append_log(str(msg).rstrip() + "\n")

    log(f"\n===== DAB Scan gestartet: {started_at} =====")
    log("Architektur: Admin -> Supervisor -> Radio-Engine")

    _write_state({
        "running": True,
        "phase": "scan_running",
        "ok": None,
        "message": "DAB-Suchlauf läuft. Supervisor hält Stream und Watchdog währenddessen an.",
        "started_at": started_at,
        "finished_at": None,
        "command": ["supervisor.scan()"],
        "log_tail": _tail_log(),
    })

    try:
        result = supervisor.scan(log_callback=log)
        station_count = int(result.get("station_count") or _count_current_stations())
        backup_file = result.get("backup_file")

        if station_count <= 0:
            raise RuntimeError("Sicherheitsabbruch: Nach dem Scan wurden 0 Sender geladen.")

        log(f"===== DAB Scan beendet: {_now()} | Sender={station_count} =====")
        _write_state({
            "running": False,
            "phase": "finished",
            "ok": True,
            "message": f"Suchlauf erfolgreich beendet. Aktuelle Senderanzahl: {station_count}.",
            "started_at": started_at,
            "finished_at": _now(),
            "returncode": 0,
            "backup_file": backup_file,
            "command": ["supervisor.scan()"],
            "station_count": station_count,
            "scan_file_info": scan_file_info(),
            "log_tail": _tail_log(),
        })
    except Exception as exc:
        log(f"FEHLER: {exc}")
        _write_state({
            "running": False,
            "phase": "failed",
            "ok": False,
            "message": "Suchlauf fehlgeschlagen: " + str(exc),
            "started_at": started_at,
            "finished_at": _now(),
            "command": ["supervisor.scan()"],
            "station_count": _count_current_stations(),
            "scan_file_info": scan_file_info(),
            "log_tail": _tail_log(),
        })


def _append_analyzer_log(text):
    with ANALYZER_LOG_FILE.open("a", encoding="utf-8", errors="replace") as f:
        f.write(text)


def _tail_analyzer_log(lines=160):
    if not ANALYZER_LOG_FILE.exists():
        return ""
    return "\n".join(ANALYZER_LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def _base_analyzer_state():
    return {
        "running": False,
        "phase": "idle",
        "ok": None,
        "message": "Bereit.",
        "started_at": None,
        "finished_at": None,
        "index": 3,
        "attempts": 6,
        "result": None,
        "log_tail": _tail_analyzer_log(),
    }


def _write_analyzer_state(data):
    state = _base_analyzer_state()
    state.update(data or {})
    tmp = ANALYZER_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ANALYZER_STATE_FILE)
    return state


def _read_analyzer_state():
    if not ANALYZER_STATE_FILE.exists():
        return _write_analyzer_state({})
    try:
        old = json.loads(ANALYZER_STATE_FILE.read_text(encoding="utf-8"))
        state = _base_analyzer_state()
        state.update(old)
        state["log_tail"] = _tail_analyzer_log()
        return state
    except Exception:
        return _write_analyzer_state({"message": "Analyzer-Statusdatei konnte nicht gelesen werden."})


def _analyzer_worker(started_at, index, attempts):
    def log(msg):
        _append_analyzer_log(str(msg).rstrip() + "\n")

    log(f"\n===== DAB Kanalanalyse gestartet: {started_at} | Index {index} | Versuche {attempts} =====")
    _write_analyzer_state({
        "running": True,
        "phase": "running",
        "ok": None,
        "message": f"Kanalanalyse läuft für Tune-Index {index}.",
        "started_at": started_at,
        "finished_at": None,
        "index": index,
        "attempts": attempts,
        "result": None,
        "log_tail": _tail_analyzer_log(),
    })

    try:
        result = supervisor.analyze_channel(index=index, attempts=attempts, log_callback=log)
        log(f"===== DAB Kanalanalyse beendet: {_now()} | {result.get('message')} =====")
        _write_analyzer_state({
            "running": False,
            "phase": "finished",
            "ok": bool(result.get("ok")),
            "message": result.get("message") or "Kanalanalyse beendet.",
            "started_at": started_at,
            "finished_at": _now(),
            "index": index,
            "attempts": attempts,
            "result": result,
            "log_tail": _tail_analyzer_log(),
        })
    except Exception as exc:
        log(f"FEHLER: {exc}")
        _write_analyzer_state({
            "running": False,
            "phase": "failed",
            "ok": False,
            "message": "Kanalanalyse fehlgeschlagen: " + str(exc),
            "started_at": started_at,
            "finished_at": _now(),
            "index": index,
            "attempts": attempts,
            "result": None,
            "log_tail": _tail_analyzer_log(),
        })


@admin_bp.route("/admin")
def admin_page():
    return render_template("admin.html")


@admin_bp.route("/api/admin/stations")
def api_admin_stations():
    stations = load_stations()
    dashboard = selection_state(stations)
    annotated = []

    for station in dashboard["stations"]:
        item = dict(station)
        label = item.get("label", "")
        slug = logo_slug(label)
        logo_path = logo_path_for_station(label)
        item["logo_slug"] = slug
        item["logo_filename"] = f"{slug}.png"
        item["logo_path"] = logo_path or "/static/logos/default.png"
        item["logo"] = logo_path
        item["logo_exists"] = bool(logo_path)
        annotated.append(item)

    return jsonify({
        "ok": True,
        "count": len(annotated),
        "scan_file": str(SCAN_FILE),
        "scan_file_info": scan_file_info(),
        "dashboard_selection": {
            "initialized": dashboard["initialized"],
            "selection_file": dashboard["selection_file"],
            "enabled_count": dashboard["enabled_count"],
            "total_count": dashboard["total_count"],
        },
        "stations": annotated,
    })


@admin_bp.route("/api/admin/dashboard/toggle", methods=["POST"])
def api_admin_dashboard_toggle():
    data = request.get_json(silent=True) or {}
    key = str(data.get("dashboard_key") or "")
    enabled = bool(data.get("enabled"))

    try:
        state = set_dashboard_enabled(load_stations(), key, enabled)
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    return jsonify({
        "ok": True,
        "message": "Dashboard-Auswahl wurde gespeichert.",
        "dashboard_selection": {
            "initialized": state["initialized"],
            "selection_file": state["selection_file"],
            "enabled_count": state["enabled_count"],
            "total_count": state["total_count"],
        },
        "stations": state["stations"],
    })


@admin_bp.route("/api/admin/scan/start", methods=["POST"])
def api_admin_scan_start():
    global _scan_thread

    with _lock:
        state = _read_state()
        if state.get("running"):
            return jsonify({"ok": False, "message": "Es läuft bereits ein Suchlauf.", "state": state})

        started_at = _now()
        _scan_thread = threading.Thread(target=_scan_worker, args=(started_at,), daemon=True)
        _scan_thread.start()

        state = _read_state()
        return jsonify({"ok": True, "message": "Suchlauf wurde gestartet.", "state": state})


@admin_bp.route("/api/admin/scan/status")
def api_admin_scan_status():
    state = _read_state()
    return jsonify({"ok": True, "state": state})


@admin_bp.route("/api/admin/analyzer/channel/start", methods=["POST"])
def api_admin_analyzer_channel_start():
    global _analyzer_thread

    payload = {}
    try:
        payload = __import__("flask").request.get_json(silent=True) or {}
    except Exception:
        payload = {}

    try:
        index = int(payload.get("index", 3))
    except Exception:
        index = 3
    try:
        attempts = int(payload.get("attempts", 6))
    except Exception:
        attempts = 6

    attempts = max(1, min(attempts, 20))

    with _lock:
        scan_state = _read_state()
        analyzer_state = _read_analyzer_state()
        if scan_state.get("running"):
            return jsonify({"ok": False, "message": "Während eines Vollscans kann keine Kanalanalyse gestartet werden.", "state": analyzer_state})
        if analyzer_state.get("running"):
            return jsonify({"ok": False, "message": "Es läuft bereits eine Kanalanalyse.", "state": analyzer_state})

        started_at = _now()
        _analyzer_thread = threading.Thread(target=_analyzer_worker, args=(started_at, index, attempts), daemon=True)
        _analyzer_thread.start()

        state = _read_analyzer_state()
        return jsonify({"ok": True, "message": "Kanalanalyse wurde gestartet.", "state": state})


@admin_bp.route("/api/admin/analyzer/channel/status")
def api_admin_analyzer_channel_status():
    return jsonify({"ok": True, "state": _read_analyzer_state()})


@admin_bp.route("/api/admin/scan/accept", methods=["POST"])
def api_admin_scan_accept():
    state = _read_state()
    if state.get("running"):
        return jsonify({"ok": False, "message": "Während des Suchlaufs kann nicht übernommen werden."})

    state.update({
        "phase": "accepted",
        "message": "Aktuelle Senderliste wurde übernommen.",
        "station_count": _count_current_stations(),
        "scan_file_info": scan_file_info(),
        "log_tail": _tail_log(),
    })
    _write_state(state)
    return jsonify({"ok": True, "message": "Aktuelle Senderliste wurde übernommen.", "scan_file_info": scan_file_info()})


@admin_bp.route("/api/admin/scan/discard", methods=["POST"])
def api_admin_scan_discard():
    state = _read_state()
    if state.get("running"):
        return jsonify({"ok": False, "message": "Während des Suchlaufs kann nicht verworfen werden."})

    backup_file = state.get("backup_file")
    if not backup_file or not Path(backup_file).exists():
        return jsonify({"ok": False, "message": "Keine Sicherung zum Wiederherstellen gefunden."})

    ok = restore_scan_backup(backup_file)
    if not ok:
        return jsonify({"ok": False, "message": "Backup konnte nicht wiederhergestellt werden."})

    station_count = _count_current_stations()
    state.update({
        "phase": "discarded",
        "message": "Suchlauf wurde verworfen. Alte Senderliste wurde wiederhergestellt.",
        "station_count": station_count,
        "scan_file_info": scan_file_info(),
        "log_tail": _tail_log(),
    })
    _write_state(state)
    return jsonify({"ok": True, "message": "Alte Senderliste wurde wiederhergestellt.", "scan_file_info": scan_file_info()})


@admin_bp.route("/api/admin/logos/upload", methods=["POST"])
def api_admin_logos_upload():
    """Upload a PNG logo for one station.

    The admin frontend sends three multipart fields:
    - station: human readable station label
    - filename: expected logo filename generated by the frontend
    - logo: uploaded PNG file

    The backend deliberately derives the final filename from the station label
    using the same slug logic as the dashboard. This keeps scan data untouched
    and prevents unsafe path/file names from being written.
    """
    station = (request.form.get("station") or "").strip()
    uploaded = request.files.get("logo")

    if not station:
        return jsonify({"ok": False, "message": "Sendername fehlt."}), 400

    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "message": "Keine Logo-Datei empfangen."}), 400

    original_name = uploaded.filename or ""
    safe_original = secure_filename(original_name)
    if not safe_original.lower().endswith(".png"):
        return jsonify({"ok": False, "message": "Bitte nur PNG-Dateien hochladen."}), 400

    # Quick signature check: real PNG files start with this 8-byte magic value.
    head = uploaded.stream.read(8)
    uploaded.stream.seek(0)
    if head != b"\x89PNG\r\n\x1a\n":
        return jsonify({"ok": False, "message": "Die Datei ist keine gültige PNG-Datei."}), 400

    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    slug = logo_slug(station)
    filename = f"{slug}.png"
    target = LOGO_DIR / filename

    try:
        uploaded.save(target)
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Logo konnte nicht gespeichert werden: {exc}"}), 500

    return jsonify({
        "ok": True,
        "message": f"Logo wurde hochgeladen: {filename}",
        "station": station,
        "filename": filename,
        "logo_filename": filename,
        "path": f"/static/logos/{filename}",
        "logo_path": f"/static/logos/{filename}",
    })


@admin_bp.route("/api/admin/analyzer/play_service", methods=["POST"])
def api_admin_analyzer_play_service():
    data = request.get_json(silent=True) or {}
    try:
        tune_index = int(data.get("tune_index"))
        service_id = int(data.get("service_id"))
        component_id = int(data.get("component_id"))
    except Exception:
        return jsonify({"ok": False, "message": "Ungültige oder fehlende Tune-/Service-/Component-ID."}), 400

    label = (data.get("label") or f"Service {service_id}").strip()
    station = {
        "label": label,
        "tune_index": tune_index,
        "tune_freq": data.get("tune_freq"),
        "service_id": service_id,
        "component_id": component_id,
        "temporary": True,
    }

    try:
        played = supervisor.play_temporary_station(station)
        return jsonify({"ok": True, "message": f"Temporärer Dienst gestartet: {played.get('label')}", "station": played})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 500
