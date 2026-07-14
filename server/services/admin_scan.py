import json
import subprocess
import threading
import time
from pathlib import Path

from config import RADIO_CLI, SCAN_FILE
from services.locks import cli_file_lock


STATE_FILE = Path("cache/admin_scan_status.json")
LOG_FILE = Path("logs/admin_scan.log")
BACKUP_DIR = Path("backups/scans")

STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_thread = None
_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "ok": False,
    "returncode": None,
    "message": "Noch kein Scan gestartet.",
    "log_tail": "",
    "scan_file": str(SCAN_FILE),
    "scan_modified": None,
    "scan_size": 0,
}


def _scan_file_info():
    try:
        if not SCAN_FILE.exists():
            return None, 0
        st = SCAN_FILE.stat()
        return st.st_mtime, st.st_size
    except Exception:
        return None, 0


def _save_state():
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception:
        pass


def _set_state(**kwargs):
    with _lock:
        _state.update(kwargs)
        mtime, size = _scan_file_info()
        _state["scan_modified"] = mtime
        _state["scan_size"] = size
        _save_state()


def _read_tail(max_chars=5000):
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
        return text[-max_chars:]
    except Exception:
        return ""


def _backup_scan_file():
    if not SCAN_FILE.exists():
        return ""

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"ensemblescan__.json.bak.{stamp}"
    backup.write_bytes(SCAN_FILE.read_bytes())
    return str(backup)


def _run_scan_worker():
    started = time.time()
    before_mtime, before_size = _scan_file_info()

    _set_state(
        running=True,
        started_at=started,
        finished_at=None,
        ok=False,
        returncode=None,
        message="Scan läuft. Bitte warten...",
        log_tail="",
    )

    try:
        backup_path = _backup_scan_file()
        with LOG_FILE.open("a", encoding="utf-8", errors="replace") as log:
            log.write("\n" + "=" * 72 + "\n")
            log.write(time.strftime("%Y-%m-%d %H:%M:%S") + " Admin-Scan gestartet\n")
            if backup_path:
                log.write(f"Backup der alten Scan-Datei: {backup_path}\n")
            log.write(f"Befehl: sudo {RADIO_CLI} -S\n\n")
            log.flush()

            with cli_file_lock(timeout=10):
                proc = subprocess.run(
                    ["sudo", RADIO_CLI, "-S"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=420,
                )

            output = (proc.stdout or b"").decode("utf-8", errors="replace")
            log.write(output)
            log.write("\n")
            log.write(time.strftime("%Y-%m-%d %H:%M:%S") + f" Admin-Scan beendet, rc={proc.returncode}\n")

        after_mtime, after_size = _scan_file_info()
        changed = (after_mtime != before_mtime) or (after_size != before_size)

        if proc.returncode == 0 and SCAN_FILE.exists():
            msg = "Scan beendet. Senderliste wurde aktualisiert." if changed else "Scan beendet. Scan-Datei wurde nicht verändert."
            ok = True
        else:
            msg = "Scan fehlgeschlagen. Bitte Log im Admin-Panel prüfen."
            ok = False

        _set_state(
            running=False,
            finished_at=time.time(),
            ok=ok,
            returncode=proc.returncode,
            message=msg,
            log_tail=_read_tail(),
        )

    except subprocess.TimeoutExpired:
        with LOG_FILE.open("a", encoding="utf-8", errors="replace") as log:
            log.write("\nTIMEOUT: Scan hat länger als 7 Minuten gedauert.\n")
        _set_state(
            running=False,
            finished_at=time.time(),
            ok=False,
            returncode=None,
            message="Scan-Timeout nach 7 Minuten.",
            log_tail=_read_tail(),
        )
    except Exception as exc:
        with LOG_FILE.open("a", encoding="utf-8", errors="replace") as log:
            log.write(f"\nFEHLER: {exc}\n")
        _set_state(
            running=False,
            finished_at=time.time(),
            ok=False,
            returncode=None,
            message=f"Scan-Fehler: {exc}",
            log_tail=_read_tail(),
        )


def start_scan():
    global _thread

    with _lock:
        if _state.get("running"):
            return {"ok": False, "error": "Ein Scan läuft bereits.", **_state}

        _thread = threading.Thread(target=_run_scan_worker, daemon=True)
        _thread.start()

    return {"ok": True, "message": "Scan gestartet."}


def scan_status():
    with _lock:
        mtime, size = _scan_file_info()
        _state["scan_modified"] = mtime
        _state["scan_size"] = size
        _state["log_tail"] = _read_tail()
        return dict(_state)
