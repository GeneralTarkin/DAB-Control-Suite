import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from config import ICECAST_PUSH

stream_process = None
STATUS = Path("cache/stream_status.json")
LOG = Path("logs/stream_direct.log")
POWER_STATE = Path("cache/power_state.json")
STANDBY_LOCK = Path("cache/standby.lock")
RESTART_REQUEST = Path("cache/stream_restart.request")
TUNING_LOCK = Path("cache/stream_tuning.lock")

STATUS.parent.mkdir(exist_ok=True)
LOG.parent.mkdir(exist_ok=True)


def log(message):
    with LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def write_status(running=False, process_running=False, mount_alive=False, error=None):
    data = {
        "timestamp": time.time(),
        "source": "direct_stream",
        "running": bool(running),
        "process_running": bool(process_running),
        "icecast_mount_alive": bool(mount_alive),
    }
    if error:
        data["error"] = str(error)

    try:
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(STATUS)
    except Exception:
        pass


def kill_process_tree(proc):
    if not proc or proc.poll() is not None:
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=4)
        except Exception:
            pass
    except ProcessLookupError:
        pass
    except Exception:
        pass


def kill_leftovers():
    subprocess.run(
        ["pkill", "-f", "arecord -D hw:CARD=dabboard"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["pkill", "-f", "ffmpeg.*live.mp3"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["pkill", "-f", "ffmpeg.*icecast"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "arecord"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def local_stream_process_running():
    return stream_process is not None and stream_process.poll() is None


def external_stream_running():
    """Erkennt einen bereits laufenden arecord/ffmpeg-Pfad.

    Wichtig: Je nach Startart kann der Stream-Prozess vom Flask-Prozess oder
    von einem systemd-Worker erzeugt worden sein. Deshalb verlassen wir uns
    nicht nur auf die lokale Python-Variable stream_process.
    """
    checks = [
        ["pgrep", "-f", "arecord -D hw:CARD=dabboard"],
        ["pgrep", "-f", "ffmpeg.*live.mp3"],
        ["pgrep", "-f", "ffmpeg.*icecast"],
    ]
    for cmd in checks:
        try:
            if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                return True
        except Exception:
            pass
    return False


def stream_process_running():
    return local_stream_process_running() or external_stream_running()


def power_is_on(default=False):
    try:
        if STANDBY_LOCK.exists():
            return False
        if not POWER_STATE.exists():
            return bool(default)
        data = json.loads(POWER_STATE.read_text(encoding="utf-8", errors="replace"))
        return bool(data.get("on", default))
    except Exception:
        return bool(default)



def mark_tuning_start():
    """Signalisiert dem externen Streaming-Supervisor einen gewollten Senderwechsel.

    Während eines Fast-Tune darf der Stream kurzfristig ungesund aussehen.
    Der Watchdog soll in dieser Zeit nicht hektisch arecord/ffmpeg neu starten.
    """
    try:
        TUNING_LOCK.parent.mkdir(exist_ok=True)
        TUNING_LOCK.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def mark_tuning_end():
    try:
        TUNING_LOCK.unlink(missing_ok=True)
    except Exception:
        pass


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

def force_standby_marker():
    try:
        STANDBY_LOCK.parent.mkdir(exist_ok=True)
        STANDBY_LOCK.write_text(str(time.time()), encoding="utf-8")
        POWER_STATE.write_text(json.dumps({"on": False, "timestamp": time.time()}, indent=2), encoding="utf-8")
        RESTART_REQUEST.unlink(missing_ok=True)
    except Exception:
        pass


def clear_standby_marker():
    try:
        STANDBY_LOCK.unlink(missing_ok=True)
        POWER_STATE.write_text(json.dumps({"on": True, "timestamp": time.time()}, indent=2), encoding="utf-8")
    except Exception:
        pass


def stop_stream():
    global stream_process

    log("Stoppe Stream")
    kill_process_tree(stream_process)
    stream_process = None
    kill_leftovers()
    time.sleep(1.0)
    write_status(False, False, False)
    return True


def start_stream(restart=False):
    """Startet den Audiostream oder lässt ihn bewusst weiterlaufen.

    Bis 0.9.2 wurde der Stream bei jedem Senderwechsel hart gestoppt und neu
    gestartet. Genau das verursachte die lange Umschaltzeit. Ab 0.9.3 ist diese
    Funktion idempotent: Wenn arecord/ffmpeg bzw. der Icecast-Mount bereits
    laufen, bleibt der Audiopfad erhalten. Nur Standby, Scan oder ein echter
    Fehler erzwingen einen Neustart.
    """
    global stream_process

    if not power_is_on(default=False):
        stop_stream()
        write_status(False, False, False, "Standby aktiv")
        raise RuntimeError("Streamstart verweigert: DAB-Board ist im Standby")

    process_running = stream_process_running()
    mount = icecast_mount_alive()

    if not restart and (process_running or mount):
        log("Stream läuft bereits - kein Neustart")
        write_status(
            running=bool(mount or process_running),
            process_running=bool(process_running),
            mount_alive=bool(mount),
        )
        return True

    if restart:
        log("Stream-Neustart angefordert")
        stop_stream()
    else:
        # Nur verwaiste Reste entfernen, wenn wirklich kein Stream aktiv ist.
        kill_leftovers()
        time.sleep(0.2)

    cmd = (
        "arecord -D hw:CARD=dabboard,DEV=0 -f S16_LE -r 48000 -c 2 -t raw | "
        "ffmpeg -hide_banner -loglevel warning "
        "-fflags nobuffer -flags low_delay "
        "-f s16le -ar 48000 -ac 2 -i - "
        "-c:a libmp3lame -b:a 128k "
        "-flush_packets 1 -muxdelay 0 -muxpreload 0 "
        "-content_type audio/mpeg "
        "-f mp3 "
        f"{ICECAST_PUSH}"
    )

    log("Starte arecord/ffmpeg")
    ffmpeg_log = open("logs/stream_ffmpeg.log", "ab", buffering=0)

    stream_process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=ffmpeg_log,
        stderr=ffmpeg_log,
        preexec_fn=os.setsid,
    )

    # Nur kurz prüfen, ob der Prozess direkt abstürzt. Der eigentliche
    # Icecast-Healthcheck passiert danach im Supervisor. Dadurch spart jeder
    # Senderwechsel mehrere Sekunden.
    time.sleep(0.8)

    if stream_process.poll() is not None:
        msg = "Streamprozess ist direkt wieder beendet"
        log(msg)
        write_status(False, False, False, msg)
        raise RuntimeError(msg)

    mount = icecast_mount_alive()
    write_status(
        running=bool(mount or stream_process_running()),
        process_running=True,
        mount_alive=mount,
    )

    return True


def icecast_mount_alive():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/status-json.xsl", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))

        source = data.get("icestats", {}).get("source")
        if isinstance(source, dict):
            return source.get("listenurl", "").endswith("/live.mp3") or source.get("@mount") == "/live.mp3"
        if isinstance(source, list):
            return any(
                item.get("listenurl", "").endswith("/live.mp3") or item.get("@mount") == "/live.mp3"
                for item in source
            )
    except Exception:
        return False

    return False


def stream_status():
    if not power_is_on(default=False):
        stop_stream()
        write_status(False, False, False, "Standby aktiv")
        return {"running": False, "process_running": False, "icecast_mount_alive": False, "source": "direct_stream", "standby": True}

    process_running = stream_process_running()
    mount_alive = icecast_mount_alive()

    data = {
        # Im laufenden Betrieb ist der Icecast-Mount das wichtigste Signal.
        # Zusätzlich gilt ein noch startender arecord/ffmpeg-Prozess als aktiv,
        # damit der Supervisor nicht während des Aufbaus unnötig neu startet.
        "running": bool(mount_alive or process_running),
        "process_running": bool(process_running),
        "icecast_mount_alive": bool(mount_alive),
        "source": "direct_stream",
    }

    write_status(
        running=data["running"],
        process_running=data["process_running"],
        mount_alive=data["icecast_mount_alive"],
    )

    return data
