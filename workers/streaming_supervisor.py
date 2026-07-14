#!/usr/bin/env python3
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ICECAST_PUSH

LOG = Path("logs/streaming_supervisor.log")
STATUS = Path("cache/stream_status.json")
RESTART_REQUEST = Path("cache/stream_restart.request")
TUNING_LOCK = Path("cache/stream_tuning.lock")
POWER_STATE = Path("cache/power_state.json")
STANDBY_LOCK = Path("cache/standby.lock")

LOG.parent.mkdir(exist_ok=True)
STATUS.parent.mkdir(exist_ok=True)
RESTART_REQUEST.parent.mkdir(exist_ok=True)

proc = None
last_request_seen = None
missing_process_count = 0
missing_mount_count = 0
last_tuning_seen = 0


def log(msg):
    with LOG.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def write_status(running=False, process_running=False, mount_alive=False, error=None):
    data = {
        "timestamp": time.time(),
        "source": "streaming_supervisor",
        "running": bool(running),
        "process_running": bool(process_running),
        "icecast_mount_alive": bool(mount_alive),
    }
    if error:
        data["error"] = str(error)

    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(STATUS)


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


def proc_running():
    if proc is not None and proc.poll() is None:
        return True
    for cmd in (["pgrep", "-f", "arecord -D hw:CARD=dabboard"], ["pgrep", "-f", "ffmpeg.*live.mp3"], ["pgrep", "-f", "ffmpeg.*icecast"]):
        try:
            if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                return True
        except Exception:
            pass
    return False


def start_stream(restart=False):
    global proc

    if not power_is_on(default=False):
        log("Streamstart verweigert: Standby aktiv")
        stop_stream()
        write_status(False, False, False, "Standby aktiv")
        return False

    if not restart and (proc_running() or icecast_mount_alive()):
        log("Stream läuft bereits - kein Neustart")
        write_status(True, proc_running(), icecast_mount_alive())
        return True

    if restart:
        stop_stream()
        time.sleep(0.5)
    else:
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

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=ffmpeg_log,
        stderr=ffmpeg_log,
        preexec_fn=os.setsid,
    )
    return True


def stop_stream():
    global proc

    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=4)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass

    proc = None
    kill_leftovers()
    time.sleep(0.8)


def restart_stream(reason, hard=False):
    if hard:
        log(f"Stream-Neustart: {reason}")
        start_stream(restart=True)
        time.sleep(5)
    else:
        log(f"Stream sicherstellen: {reason}")
        start_stream(restart=False)
        time.sleep(1)


def read_restart_request():
    try:
        if RESTART_REQUEST.exists():
            return RESTART_REQUEST.read_text().strip()
    except Exception:
        return None
    return None


def main():
    global proc, last_request_seen, missing_process_count, missing_mount_count, last_tuning_seen

    log("Streaming Supervisor gestartet")
    write_status(False, False, False)

    last_request_seen = read_restart_request()
    if power_is_on(default=False):
        restart_stream("Initialstart", hard=False)
    else:
        log("Standby aktiv: kein Initialstart des Streams")
        stop_stream()
        write_status(False, False, False)

    while True:
        try:
            if not power_is_on(default=False):
                if proc is not None and proc.poll() is None:
                    log("Standby erkannt: Stream wird gestoppt")
                stop_stream()
                write_status(False, False, False)
                time.sleep(3)
                continue

            current_request = read_restart_request()
            if current_request and current_request != last_request_seen:
                last_request_seen = current_request
                restart_stream("Anforderung durch DAB Supervisor", hard=False)

            process_running = proc_running()
            mount_alive = icecast_mount_alive()

            if tuning_in_progress():
                last_tuning_seen = time.time()
                missing_process_count = 0
                missing_mount_count = 0
                log("Senderwechsel aktiv: Healthcheck-Neustart wird unterdrueckt")
                write_status(running=bool(process_running or mount_alive), process_running=process_running, mount_alive=mount_alive)
                time.sleep(1)
                continue

            # Nach einem Senderwechsel bekommt ALSA/Icecast eine kurze Schonfrist.
            if time.time() - last_tuning_seen < 6:
                write_status(running=bool(process_running or mount_alive), process_running=process_running, mount_alive=mount_alive)
                time.sleep(1)
                continue

            # Der Mount kann beim Fast-Tune kurz wackeln. Solange ein
            # arecord/ffmpeg-Pfad existiert, wird nur sichergestellt statt
            # hart neu gestartet. Ein harter Neustart passiert erst, wenn
            # wirklich kein Prozess mehr gefunden wird.
            if not process_running:
                missing_process_count += 1
                if missing_process_count >= 3:
                    restart_stream(f"Healthcheck fehlgeschlagen: process={process_running}, mount={mount_alive}", hard=True)
                    missing_process_count = 0
                    process_running = proc_running()
                    mount_alive = icecast_mount_alive()
            else:
                missing_process_count = 0

            if process_running and not mount_alive:
                missing_mount_count += 1
                if missing_mount_count >= 4:
                    restart_stream(f"Mount noch nicht gesund: process={process_running}, mount={mount_alive}", hard=False)
                    missing_mount_count = 0
                    process_running = proc_running()
                    mount_alive = icecast_mount_alive()
            else:
                missing_mount_count = 0

            write_status(
                running=bool(process_running or mount_alive),
                process_running=process_running,
                mount_alive=mount_alive,
            )

        except Exception as exc:
            log(f"ERROR: {exc}")
            write_status(False, False, False, error=exc)
            time.sleep(5)

        time.sleep(3)


if __name__ == "__main__":
    main()
