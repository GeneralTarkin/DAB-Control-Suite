#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template_string

SCAN_FILE = Path("/usr/local/lib/DABBoard/ensemblescan__.json")
RADIO_CLI = "/usr/local/lib/DABBoard/radio_cli_v3.1.0"

ICECAST_URL = "http://192.168.123.168:8000/live.mp3"
ICECAST_PUSH = "icecast://source:hackme@localhost:8000/live.mp3"

app = Flask(__name__)

arecord_process = None
ffmpeg_process = None
current_station = None
radio_lock = threading.Lock()


def load_stations():
    with SCAN_FILE.open("r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    if isinstance(data, dict):
        ensembles = next((v for v in data.values() if isinstance(v, list)), [])
    elif isinstance(data, list):
        ensembles = data
    else:
        ensembles = []

    stations = []

    for ens in ensembles:
        if not isinstance(ens, dict):
            continue

        status = ens.get("DigradStatus", {})
        tune_index = status.get("tune_index")
        tune_freq = status.get("tune_freq")

        service_block = ens.get("DigitalServiceList")
        if not service_block:
            continue

        for service in service_block.get("ServiceList", []):
            if service.get("AudioOrDataFlag") != 0:
                continue

            comps = service.get("ComponentList", [])
            if not comps:
                continue

            stations.append({
                "label": service.get("Label", "").strip(),
                "tune_index": tune_index,
                "tune_freq": tune_freq,
                "service_id": service.get("ServId"),
                "component_id": comps[0].get("comp_ID"),
            })

    stations.sort(key=lambda s: s["label"].lower())
    return stations


def run_radio_cmd(args):
    result = subprocess.run(
        ["sudo", RADIO_CLI] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.returncode, result.stdout


def kill_process_tree(proc):
    if not proc:
        return

    if proc.poll() is not None:
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=3)
        except Exception:
            pass
    except ProcessLookupError:
        pass


def stop_stream():
    global arecord_process, ffmpeg_process

    kill_process_tree(ffmpeg_process)
    kill_process_tree(arecord_process)

    ffmpeg_process = None
    arecord_process = None

    subprocess.run(["sudo", "pkill", "-f", "arecord -D hw:CARD=dabboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sudo", "pkill", "-f", "ffmpeg.*icecast"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)


def start_stream():
    global arecord_process, ffmpeg_process

    stop_stream()

    arecord_cmd = [
        "arecord",
        "-D", "hw:CARD=dabboard,DEV=0",
        "-f", "S16_LE",
        "-r", "48000",
        "-c", "2",
        "-t", "raw",
    ]

    ffmpeg_cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        "-re",
        "-f", "s16le",
        "-ar", "48000",
        "-ac", "2",
        "-i", "-",
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        "-content_type", "audio/mpeg",
        "-f", "mp3",
        ICECAST_PUSH,
    ]

    arecord_process = subprocess.Popen(
        arecord_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
        bufsize=0,
    )

    ffmpeg_process = subprocess.Popen(
        ffmpeg_cmd,
        stdin=arecord_process.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
        bufsize=0,
        text=False,
    )

    if arecord_process.stdout:
        arecord_process.stdout.close()

    time.sleep(2.0)

    if arecord_process.poll() is not None:
        err = arecord_process.stderr.read().decode("utf-8", errors="replace") if arecord_process.stderr else ""
        raise RuntimeError("arecord ist beendet: " + err[-300:])

    if ffmpeg_process.poll() is not None:
        err = ffmpeg_process.stderr.read().decode("utf-8", errors="replace") if ffmpeg_process.stderr else ""
        raise RuntimeError("ffmpeg ist beendet: " + err[-300:])


def tune_station(station):
    rc, out = run_radio_cmd(["-k"])
    time.sleep(1.0)

    rc, out = run_radio_cmd(["-b", "D"])
    if rc != 0:
        raise RuntimeError("Boot fehlgeschlagen: " + out[-400:])
    time.sleep(1.0)

    rc, out = run_radio_cmd(["-o", "1"])
    if rc != 0:
        raise RuntimeError("I2S-Aktivierung fehlgeschlagen: " + out[-400:])
    time.sleep(1.0)

    rc, out = run_radio_cmd([
        "-f", str(station["tune_index"]),
        "-e", str(station["service_id"]),
        "-c", str(station["component_id"]),
        "-p",
        "-l", "50",
    ])
    if rc != 0:
        raise RuntimeError("Senderstart fehlgeschlagen: " + out[-400:])

    time.sleep(2.0)


def play_station(station):
    global current_station

    with radio_lock:
        stop_stream()
        tune_station(station)
        start_stream()
        current_station = station


HTML = """
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>MWI DAB Radio</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root { --gold:#ffd34d; --gold2:#ffe27a; --card:rgba(20,20,20,.84); }
* { box-sizing:border-box; }
body {
    margin:0; min-height:100vh;
    background: radial-gradient(circle at top, #242424 0%, #070707 68%);
    color:var(--gold); font-family: Arial, Helvetica, sans-serif;
}
.wrap { max-width:1100px; margin:0 auto; padding:38px 18px; }
.card {
    background:var(--card); border:1px solid rgba(255,211,77,.28);
    border-radius:24px; box-shadow:0 0 38px rgba(0,0,0,.66);
    padding:28px; backdrop-filter: blur(8px);
}
h1 { text-align:center; font-size:42px; margin:8px 0 5px; }
.sub { text-align:center; color:#fff3b0; margin-bottom:24px; }
.now { text-align:center; font-size:24px; color:#fff; margin:18px 0; }
.status { text-align:center; color:#ddd; font-size:14px; min-height:20px; }
audio { width:100%; margin:18px 0 24px; }
.toolbar { display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin:10px 0 22px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-top:20px; }
button {
    background:var(--gold); color:#111; border:0; border-radius:13px;
    padding:13px 15px; font-weight:bold; cursor:pointer; font-size:15px;
    box-shadow:0 4px 12px rgba(0,0,0,.35);
}
button:hover { background:var(--gold2); }
button.secondary { background:#333; color:var(--gold); border:1px solid rgba(255,211,77,.3); }
button.secondary:hover { background:#444; }
button.active { outline:3px solid rgba(255,255,255,.45); background:#fff1a6; }
.footer { text-align:center; color:#aaa; margin-top:25px; font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>📻 MWI DAB Radio</h1>
    <div class="sub">Digitaler DAB+-Stream von Michael Willner</div>

    <div class="now" id="now">Noch kein Sender gewählt</div>
    <div class="status" id="status">Bereit.</div>

    <audio id="player" controls autoplay>
      <source src="{{ stream_url }}" type="audio/mpeg">
    </audio>

    <div class="toolbar">
      <button class="secondary" onclick="reloadPlayer()">🔄 Player neu laden</button>
      <button class="secondary" onclick="refreshStatus()">📡 Status aktualisieren</button>
      <button class="secondary" onclick="stopRadio()">■ Stop</button>
    </div>

    <div class="grid">
      {% for s in stations %}
      <button id="station-{{ loop.index0 }}" onclick="playStation({{ loop.index0 }})">{{ s.label }}</button>
      {% endfor %}
    </div>

    <div class="footer">
      MWI DAB Server · Raspberry Pi Zero 2 W · uGreen DAB Board · Icecast
    </div>
  </div>
</div>

<script>
function setStatus(text) { document.getElementById("status").innerText = text; }

function markActive(id) {
    document.querySelectorAll(".grid button").forEach(b => b.classList.remove("active"));
    const btn = document.getElementById("station-" + id);
    if (btn) btn.classList.add("active");
}

function reloadPlayer() {
    const audio = document.getElementById("player");
    const source = audio.querySelector("source");
    source.src = "{{ stream_url }}?t=" + Date.now();
    audio.load();
    audio.play().catch(() => {});
}

async function playStation(id) {
    markActive(id);
    document.getElementById("now").innerText = "Starte Sender...";
    setStatus("Bitte warten: Tuner und Stream werden neu gestartet.");

    const res = await fetch("/api/play/" + id, {method:"POST"});
    const data = await res.json();

    if (!data.ok) {
        setStatus("Fehler: " + (data.error || "Unbekannt"));
        return;
    }

    document.getElementById("now").innerText = "Jetzt läuft: " + data.station.label;
    setStatus("Stream läuft. Falls kein Ton kommt: Player neu laden.");
    setTimeout(reloadPlayer, 1500);
}

async function stopRadio() {
    await fetch("/api/stop", {method:"POST"});
    document.getElementById("now").innerText = "Gestoppt";
    setStatus("Stream gestoppt.");
}

async function refreshStatus() {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.current) {
        document.getElementById("now").innerText = "Jetzt läuft: " + data.current.label;
    }
}
refreshStatus();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML, stations=load_stations(), stream_url=ICECAST_URL)


@app.route("/api/status")
def api_status():
    return jsonify({
        "current": current_station,
        "stream": ICECAST_URL,
        "arecord_running": arecord_process is not None and arecord_process.poll() is None,
        "ffmpeg_running": ffmpeg_process is not None and ffmpeg_process.poll() is None,
    })


@app.route("/api/play/<int:index>", methods=["POST"])
def api_play(index):
    try:
        stations = load_stations()
        if index < 0 or index >= len(stations):
            return jsonify({"ok": False, "error": "Ungültiger Sender"}), 400

        station = stations[index]
        play_station(station)
        return jsonify({"ok": True, "station": station, "stream": ICECAST_URL})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global current_station
    with radio_lock:
        stop_stream()
        run_radio_cmd(["-k"])
        current_station = None
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088, threaded=False)
