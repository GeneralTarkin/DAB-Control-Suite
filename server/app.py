#!/usr/bin/env python3
import json
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, Response, stream_with_context, abort, send_from_directory

from config import ICECAST_URL, FLASK_HOST, FLASK_PORT
from services.radio import load_stations
from services.dashboard_selection import dashboard_stations
from services.metadata import get_metadata
from services.logos import LOGO_DIR, logo_info_for_station, logo_path_for_station, logo_slug
from services.supervisor import supervisor
from services.admin import admin_bp

app = Flask(__name__)
app.register_blueprint(admin_bp)

CACHE_METADATA = Path("cache/metadata.json")


def read_cached_metadata(max_age=300):
    """Read the metadata cache robustly.

    Important:
    - Do not clear metadata just because the supervisor is temporarily busy.
    - Keep slightly older metadata visible; the worker updates it when it can.
    - Return a stable structure so frontend/API clients do not lose values.
    """
    fallback = {
        "station_text": "",
        "dls": {
            "raw": "",
            "artist": "",
            "title": "",
            "station_hint": "",
        },
        "dls_interpretation": {
            "raw": "",
            "type": "empty",
            "now_playing": None,
            "up_next": None,
            "info": "",
            "display_title": "",
            "display_subtitle": "",
        },
        "radio_state": {
            "service_active": False,
            "has_dls": False,
            "dls_age_seconds": None,
            "dls_empty_count": None,
            "dls_source": "cache_missing",
            "station_index": None,
        },
        "digrad_status": {},
        "event_status": {},
        "ensemble_info": {},
        "_cache": {
            "alive": False,
            "age_seconds": None,
            "stale": True,
            "source": "fallback",
        },
    }

    try:
        if not CACHE_METADATA.exists():
            return fallback

        raw = CACHE_METADATA.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)

        ts = float(data.get("timestamp", 0) or 0)
        age = round(time.time() - ts, 1) if ts else None

        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        # Preserve a stable shape even if a future worker version omits fields.
        stable = dict(fallback)
        stable.update(metadata)

        # Ensure nested defaults exist.
        for key in ("dls", "dls_interpretation", "radio_state", "digrad_status", "event_status", "ensemble_info"):
            if not isinstance(stable.get(key), dict):
                stable[key] = fallback[key]

        stable["_cache"] = {
            "alive": bool(data.get("alive", True)),
            "age_seconds": age,
            "stale": bool(age is not None and age > max_age),
            "source": "cache",
        }

        return stable

    except Exception as exc:
        fallback["_cache"] = {
            "alive": False,
            "age_seconds": None,
            "stale": True,
            "source": "exception",
            "error": str(exc),
        }
        return fallback


def with_logo_info(station):
    item = dict(station or {})
    item.update(logo_info_for_station(item.get("label", "")))
    return item


def get_dashboard_stations():
    return [with_logo_info(station) for station in dashboard_stations(load_stations())]


@app.route("/")
def index():
    return render_template(
        "index.html",
        stations=get_dashboard_stations(),
        stream_url=ICECAST_URL,
    )


@app.route("/logos")
def logos():
    stations = []
    for station in load_stations():
        item = dict(station)
        item.update(logo_info_for_station(station.get("label", "")))
        stations.append(item)

    return render_template("logos.html", stations=stations)


@app.route("/api/stations")
def api_stations():
    return jsonify(get_dashboard_stations())


@app.route("/api/status")
def api_status():
    state = supervisor.status()
    metadata = read_cached_metadata()

    current = state.get("current")
    if isinstance(current, dict):
        current = with_logo_info(current)

    return jsonify({
        "current": current,
        "current_index": state.get("current_index"),
        "stream": ICECAST_URL,
        "stream_status": state.get("stream_status", {}),
        "power": state.get("power", {"on": False}),
        "switching": state.get("switching", False),
        "scanning": state.get("scanning", False),
        # Always return cached metadata, even if supervisor.current is briefly None.
        # Otherwise the frontend clears Radiotext and signal values during short transitions.
        "metadata": metadata,
    })


@app.route("/api/metadata")
def api_metadata():
    if not CACHE_METADATA.exists():
        return jsonify({"alive": False, "error": "metadata cache not found"}), 404

    return jsonify(json.loads(CACHE_METADATA.read_text(encoding="utf-8", errors="replace")))


@app.route("/api/history")
def api_history():
    path = Path("cache/song_history.json")
    if not path.exists():
        return jsonify([])

    return jsonify(json.loads(path.read_text(encoding="utf-8", errors="replace")))




@app.route("/api/logos/<path:filename>")
def api_logo(filename):
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.lower().endswith(".png"):
        abort(404)
    logo_file = LOGO_DIR / safe_name
    if not logo_file.exists():
        abort(404)
    return send_from_directory(LOGO_DIR, safe_name, mimetype="image/png", max_age=0)


@app.route("/api/stream")
def api_stream():
    import urllib.request
    state = supervisor.status()
    if not (state.get("power") or {}).get("on", False):
        return Response("DAB-Board ist im Standby.\n", status=503, mimetype="text/plain", headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Accept-Ranges": "none",
        })

    def generate():
        with urllib.request.urlopen("http://127.0.0.1:8000/live.mp3", timeout=10) as r:
            while True:
                chunk = r.read(16384)
                if not chunk:
                    break
                yield chunk

    return Response(
        stream_with_context(generate()),
        mimetype="audio/mpeg",
        direct_passthrough=True,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Accept-Ranges": "none",
            "X-Accel-Buffering": "no",
        },
    )

@app.route("/api/play/<int:index>", methods=["POST"])
def api_play(index):
    try:
        visible_stations = get_dashboard_stations()
        if index < 0 or index >= len(visible_stations):
            return jsonify({
                "ok": False,
                "error": "Dieser Sender ist im Dashboard nicht freigegeben oder existiert nicht.",
            }), 404

        selected = visible_stations[index]
        all_stations = load_stations()
        real_index = next(
            (i for i, station in enumerate(all_stations)
             if station.get("tune_index") == selected.get("tune_index")
             and station.get("service_id") == selected.get("service_id")
             and station.get("component_id") == selected.get("component_id")
             and station.get("label") == selected.get("label")),
            None,
        )
        if real_index is None:
            return jsonify({
                "ok": False,
                "error": "Sender wurde in der vollständigen Senderliste nicht gefunden.",
            }), 404

        station = with_logo_info(supervisor.play(real_index, save=True))

        return jsonify({
            "ok": True,
            "station": station,
            "stream": ICECAST_URL,
            "logo": station.get("logo", ""),
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    supervisor.power_off()
    return jsonify({"ok": True, "power": {"on": False}})


@app.route("/api/power/off", methods=["POST"])
def api_power_off():
    supervisor.power_off()
    return jsonify({"ok": True, "power": {"on": False}})


@app.route("/api/power/on", methods=["POST"])
def api_power_on():
    supervisor.power_on()
    return jsonify({"ok": True, "power": {"on": True}})


if __name__ == "__main__":
    supervisor.start()
    app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True)
