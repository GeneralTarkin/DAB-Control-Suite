import os
import signal
import subprocess
import time

from config import ICECAST_PUSH

stream_process = None


def kill_process_tree(proc):
    if not proc or proc.poll() is not None:
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait(timeout=3)
    except ProcessLookupError:
        pass


def stop_stream():
    global stream_process

    kill_process_tree(stream_process)
    stream_process = None

    subprocess.run(["sudo", "pkill", "-f", "arecord -D hw:CARD=dabboard"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sudo", "pkill", "-f", "ffmpeg.*live.mp3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(1.2)


def start_stream():
    global stream_process

    stop_stream()

    cmd = f"""
    arecord -D hw:CARD=dabboard,DEV=0 -f S16_LE -r 48000 -c 2 -t raw | \
    ffmpeg -re -f s16le -ar 48000 -ac 2 -i - \
    -c:a libmp3lame -b:a 128k \
    -f mp3 \
    {ICECAST_PUSH}
    """

    stream_process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
        text=False,
    )

    time.sleep(2.5)

    if stream_process.poll() is not None:
        err = stream_process.stderr.read().decode("utf-8", errors="replace") if stream_process.stderr else ""
        raise RuntimeError("Streamprozess ist beendet: " + err[-500:])


def stream_status():
    return {
        "running": stream_process is not None and stream_process.poll() is None
    }
