import json
import shutil
import subprocess
import time
from pathlib import Path

from config import SCAN_FILE, RADIO_CLI, DEFAULT_VOLUME


def fix_label_encoding(text):
    if not text:
        return ""

    text = text.strip()

    # Korrektur für DAB-Sonderzeichen aus der uGreen-Scan-Datei.
    replacements = {
        "\xf7": "ø",
        "\xe7": "Ø",
        "\x99": "ü",
        "\ufffd": "Ø",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # Kleine kosmetische Korrekturen
    text = text.replace("ØstJylland", "Østjylland")
    text = text.replace("KØbenhavn", "København")
    text = text.replace("WestkØste", "Westküste")

    return text


def load_stations(path=SCAN_FILE):
    # Scan-Datei ist inzwischen UTF-8. Latin-1 würde Umlaute zerstören.
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        ensembles = next((v for v in data.values() if isinstance(v, list)), [])
    elif isinstance(data, list):
        ensembles = data
    else:
        ensembles = []

    stations = []
    seen = set()

    for ens in ensembles:
        if not isinstance(ens, dict):
            continue

        status = ens.get("DigradStatus", {})
        service_block = ens.get("DigitalServiceList")
        if not service_block:
            continue

        for service in service_block.get("ServiceList", []):
            if service.get("AudioOrDataFlag") != 0:
                continue

            comps = service.get("ComponentList", [])
            if not comps:
                continue

            label = fix_label_encoding(service.get("Label", "").strip())

            # Dubletten entfernen: gleicher Sender + gleiche Service-ID nur einmal.
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)

            stations.append({
                "label": label,
                "tune_index": status.get("tune_index"),
                "tune_freq": status.get("tune_freq"),
                "service_id": service.get("ServId"),
                "component_id": comps[0].get("comp_ID"),
            })

    stations.sort(key=lambda s: s["label"].lower())
    return stations


def run_radio_cmd(args, timeout=None):
    result = subprocess.run(
        ["sudo", RADIO_CLI] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return result.returncode, result.stdout


def shutdown_radio():
    try:
        run_radio_cmd(["-k"], timeout=15)
    except subprocess.TimeoutExpired:
        # Beim Shutdown ist ein Timeout nicht schön, aber der nächste Bootversuch
        # liefert den eigentlichen Zustand. Deshalb hier nicht sofort abbrechen.
        pass

    # Sicherheitsnetz: laufende radio_cli-Instanzen dürfen den Chip nach Standby
    # nicht wieder wachhalten. Das betrifft vor allem DLS-/MOT-Listener oder alte
    # Testprozesse.
    for pattern in ["radio_cli_v3.1.0", "radio_cli", "DABBoardRadio"]:
        subprocess.run(["pkill", "-TERM", "-f", pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    for pattern in ["radio_cli_v3.1.0", "radio_cli", "DABBoardRadio"]:
        subprocess.run(["pkill", "-KILL", "-f", pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)


def _play_station_cmd(station, timeout=24):
    return run_radio_cmd([
        "-f", str(station["tune_index"]),
        "-e", str(station["service_id"]),
        "-c", str(station["component_id"]),
        "-p",
        "-l", str(DEFAULT_VOLUME),
    ], timeout=timeout)


def tune_station(station, fast=False):
    """Tune und starte einen DAB-Dienst.

    fast=True nutzt den bereits gebooteten Si468x weiter und sendet nur den
    eigentlichen Senderstart. Das spart beim normalen Senderwechsel mehrere
    Sekunden. Falls der Chip nicht bereit ist, erkennt die Funktion typische
    Fehlerausgaben und fällt automatisch auf den vollständigen Bootpfad zurück.
    """
    if fast:
        rc, out = _play_station_cmd(station, timeout=18)
        if rc == 0 and "Si468x is not booted" not in (out or ""):
            time.sleep(0.4)
            return

        # Fast-Tune kann nach echtem Standby oder instabilem Empfang scheitern.
        # Dann sauber vollständig neu initialisieren, statt dem Benutzer einen
        # Fehler zu zeigen.

    run_radio_cmd(["-k"], timeout=15)
    time.sleep(0.4)

    rc, out = run_radio_cmd(["-b", "D"], timeout=45)
    if rc != 0:
        raise RuntimeError("Boot fehlgeschlagen: " + out[-400:])

    time.sleep(0.5)

    rc, out = run_radio_cmd(["-o", "1"], timeout=15)
    if rc != 0:
        raise RuntimeError("I2S-Aktivierung fehlgeschlagen: " + out[-400:])

    time.sleep(0.4)

    rc, out = _play_station_cmd(station, timeout=30)
    if rc != 0:
        raise RuntimeError("Senderstart fehlgeschlagen: " + out[-400:])

    time.sleep(0.8)


def _sanitize_json_text(text):
    if not text:
        return ""
    # JSON erlaubt nur bestimmte Steuerzeichen. radio_cli kann rohe Bytes in
    # Labels ausgeben; die entfernen wir, ohne die Struktur zu verändern.
    return "".join(ch for ch in text if ch in "\n\r\t" or ord(ch) >= 32)


def _count_audio_services(payload):
    count = 0

    def walk(obj):
        nonlocal count
        if isinstance(obj, dict):
            service_list = obj.get("ServiceList")
            if isinstance(service_list, list):
                for service in service_list:
                    if not isinstance(service, dict):
                        continue
                    if service.get("AudioOrDataFlag") != 0:
                        continue
                    if service.get("ComponentList"):
                        count += 1
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return count


def _extract_ensemble_objects(text):
    """Extrahiert Ensemble-Objekte aus radio_cli-Ausgaben.

    Manche Versionen geben kein sauberes einzelnes JSON-Dokument aus, sondern
    eine Folge von JSON-Objekten mit Log-Objekten davor. Für unsere Scan-Datei
    reicht eine Liste aller Ensemble-Objekte mit DigradStatus.
    """
    decoder = json.JSONDecoder()
    ensembles = []
    idx = 0

    while True:
        idx = text.find('{"EnsembleNo"', idx)
        if idx == -1:
            break
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except Exception:
            idx += 1
            continue

        if isinstance(obj, dict) and "DigradStatus" in obj:
            ensembles.append(obj)
        idx += max(end, 1)

    return ensembles


def _decode_scan_payload(raw_output):
    text = _sanitize_json_text(raw_output or "")
    Path("cache/debug").mkdir(parents=True, exist_ok=True)
    Path("cache/debug/last_radio_scan_raw.txt").write_text(raw_output or "", encoding="utf-8", errors="replace")
    Path("cache/debug/last_radio_scan_sanitized.txt").write_text(text, encoding="utf-8", errors="replace")

    if not text.strip():
        raise RuntimeError("radio_cli hat keine Scan-Ausgabe geliefert.")

    if "Si468x is not booted" in text:
        raise RuntimeError("DAB-Chip ist nicht gebootet. Der Suchlauf wurde abgebrochen.")

    # 1. Versuch: komplettes JSON-Dokument lesen.
    decoder = json.JSONDecoder()
    best_payload = None
    best_count = -1
    best_size = -1

    for start, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            payload, end = decoder.raw_decode(text[start:])
        except Exception:
            continue
        count = _count_audio_services(payload)
        if count > best_count or (count == best_count and end > best_size):
            best_payload = payload
            best_count = count
            best_size = end

    if best_payload is not None and best_count > 0:
        return best_payload, best_count

    # 2. Versuch: einzelne Ensemble-Objekte aus einer Objektfolge extrahieren.
    ensembles = _extract_ensemble_objects(text)
    count = _count_audio_services(ensembles)
    if ensembles and count > 0:
        return ensembles, count

    raise RuntimeError(
        "Scan-Ausgabe wurde gelesen, enthält aber keine spielbaren Audio-Sender. "
        "Die bestehende Senderliste wurde nicht überschrieben."
    )


def _backup_scan_file(backup_dir=Path("backups/scans")):
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not Path(SCAN_FILE).exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"ensemblescan__.json.bak.{stamp}"
    shutil.copy2(SCAN_FILE, backup)
    return str(backup)


def _save_scan_payload(payload):
    target = Path(SCAN_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def restore_scan_backup(backup_file):
    if backup_file and Path(backup_file).exists():
        shutil.copy2(backup_file, SCAN_FILE)
        return True
    return False



DAB_CHANNELS = [
    {"index": 0, "channel": "5A", "freq": 174928},
    {"index": 1, "channel": "5B", "freq": 176640},
    {"index": 2, "channel": "5C", "freq": 178352},
    {"index": 3, "channel": "5D", "freq": 180064},
    {"index": 4, "channel": "6A", "freq": 181936},
    {"index": 5, "channel": "6B", "freq": 183648},
    {"index": 6, "channel": "6C", "freq": 185360},
    {"index": 7, "channel": "6D", "freq": 187072},
    {"index": 8, "channel": "7A", "freq": 188928},
    {"index": 9, "channel": "7B", "freq": 190640},
    {"index": 10, "channel": "7C", "freq": 192352},
    {"index": 11, "channel": "7D", "freq": 194064},
    {"index": 12, "channel": "8A", "freq": 195936},
    {"index": 13, "channel": "8B", "freq": 197648},
    {"index": 14, "channel": "8C", "freq": 199360},
    {"index": 15, "channel": "8D", "freq": 201072},
    {"index": 16, "channel": "9A", "freq": 202928},
    {"index": 17, "channel": "9B", "freq": 204640},
    {"index": 18, "channel": "9C", "freq": 206352},
    {"index": 19, "channel": "9D", "freq": 208064},
    {"index": 20, "channel": "10A", "freq": 209936},
    {"index": 21, "channel": "10N", "freq": 210096},
    {"index": 22, "channel": "10B", "freq": 211648},
    {"index": 23, "channel": "10C", "freq": 213360},
    {"index": 24, "channel": "10D", "freq": 215072},
    {"index": 25, "channel": "11A", "freq": 216928},
    {"index": 26, "channel": "11N", "freq": 217088},
    {"index": 27, "channel": "11B", "freq": 218640},
    {"index": 28, "channel": "11C", "freq": 220352},
    {"index": 29, "channel": "11D", "freq": 222064},
    {"index": 30, "channel": "12A", "freq": 223936},
    {"index": 31, "channel": "12N", "freq": 224096},
    {"index": 32, "channel": "12B", "freq": 225648},
    {"index": 33, "channel": "12C", "freq": 227360},
    {"index": 34, "channel": "12D", "freq": 229072},
    {"index": 35, "channel": "13A", "freq": 230784},
    {"index": 36, "channel": "13B", "freq": 232496},
    {"index": 37, "channel": "13C", "freq": 234208},
    {"index": 38, "channel": "13D", "freq": 235776},
    {"index": 39, "channel": "13E", "freq": 237488},
    {"index": 40, "channel": "13F", "freq": 239200},
]


def dab_channel_info(index):
    for item in DAB_CHANNELS:
        if int(item["index"]) == int(index):
            return dict(item)
    return {"index": int(index), "channel": str(index), "freq": None}


def _decode_first_json_object(text):
    text = _sanitize_json_text(text or "")
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[i:])
            return payload
        except Exception:
            continue
    return None


def _extract_services(payload):
    if not isinstance(payload, dict):
        return []
    service_block = payload.get("DigitalServiceList") or {}
    service_list = service_block.get("ServiceList") or []
    services = []
    for service in service_list:
        if not isinstance(service, dict):
            continue
        comps = service.get("ComponentList") or []
        raw_label = service.get("Label")
        label = fix_label_encoding((raw_label or "").strip())
        if not label or set(label) <= {"?"}:
            label = "Unbekannter Dienst"

        services.append({
            "label": label,
            "raw_label": "" if raw_label is None else str(raw_label),
            "service_id": service.get("ServId"),
            "service_no": service.get("ServiceNo"),
            "serv_ref": service.get("ServRef"),
            "program_type": service.get("ProgramType"),
            "audio": service.get("AudioOrDataFlag") == 0,
            "audio_or_data_flag": service.get("AudioOrDataFlag"),
            "component_id": comps[0].get("comp_ID") if comps else None,
            "sub_channel_id": comps[0].get("SubChId") if comps else None,
            "component_no": comps[0].get("ComponentNo") if comps else None,
        })
    return services


def test_dab_channel(index, attempts=6, settle_seconds=2.0, log_callback=None):
    """Misst einen einzelnen DAB-Kanal mehrfach und versucht die Serviceliste zu lesen.

    Diese Funktion verändert die Senderliste nicht. Der Aufrufer muss exklusiven
    Hardwarezugriff sicherstellen, z.B. über Supervisor-Lock + cli_file_lock.
    """
    info = dab_channel_info(index)
    attempts = max(1, min(int(attempts or 1), 20))

    def log(msg):
        if log_callback:
            log_callback(str(msg).rstrip() + "\n")

    result = {
        "ok": False,
        "index": info["index"],
        "channel": info["channel"],
        "freq": info["freq"],
        "attempts_requested": attempts,
        "measurements": [],
        "services": [],
        "service_count": 0,
        "best": {},
        "message": "",
    }

    log(f"Kanalanalyse: {info['channel']} / {info.get('freq') or '-'} kHz / Index {info['index']}")
    log("Radio herunterfahren (-k).")
    shutdown_radio()
    time.sleep(1.5)

    log("DAB-Firmware booten (-b D).")
    rc, out = run_radio_cmd(["-b", "D"], timeout=60)
    if out:
        log(out[-1200:])
    if rc != 0:
        raise RuntimeError("Boot fehlgeschlagen: " + out[-800:])

    time.sleep(2.0)

    best = None
    best_score = -1

    for attempt in range(1, attempts + 1):
        log(f"Messung {attempt}/{attempts}: tune/status (-f {info['index']} -d -j).")
        rc, out = run_radio_cmd(["-f", str(info["index"]), "-d", "-j"], timeout=25)
        payload = _decode_first_json_object(out)
        status = payload.get("DigradStatus", {}) if isinstance(payload, dict) else {}
        error = payload.get("error") if isinstance(payload, dict) else None

        measurement = {
            "attempt": attempt,
            "returncode": rc,
            "error": error,
            "status": status,
        }
        result["measurements"].append(measurement)

        if status:
            score = int(status.get("FIC_quality") or 0) * 10 + int(status.get("rssi") or 0) + int(status.get("valid") or 0) * 100
            if score > best_score:
                best_score = score
                best = status
            log(
                "Status: "
                f"valid={status.get('valid')} acq={status.get('acq')} "
                f"RSSI={status.get('rssi')} SNR={status.get('snr')} "
                f"FIC={status.get('FIC_quality')} FIBerr={status.get('FIB_error_count')}"
            )
        elif error:
            log(f"Status-Fehler: {error}")
        else:
            log("Keine DigradStatus-Daten gelesen.")

        time.sleep(float(settle_seconds))

        log(f"Messung {attempt}/{attempts}: Serviceliste (-f {info['index']} -g -j).")
        rc_g, out_g = run_radio_cmd(["-f", str(info["index"]), "-g", "-j"], timeout=30)
        payload_g = _decode_first_json_object(out_g)
        services = _extract_services(payload_g)
        audio_services = [s for s in services if s.get("audio")]
        measurement["service_returncode"] = rc_g
        measurement["service_count"] = len(audio_services)
        measurement["service_error"] = payload_g.get("error") if isinstance(payload_g, dict) else None

        if audio_services:
            result["services"] = audio_services
            result["service_count"] = len(audio_services)
            log("Serviceliste gelesen: " + ", ".join(s.get("label") or "?" for s in audio_services))
            # Weiter messen ist nicht nötig; wir haben den Multiplex vollständig genug gelesen.
            break
        if measurement.get("service_error"):
            log(f"Servicelisten-Fehler: {measurement['service_error']}")
        else:
            log("Serviceliste enthält noch keine Audio-Services.")

        time.sleep(1.0)

    result["best"] = best or {}
    result["ok"] = result["service_count"] > 0

    if result["ok"]:
        result["message"] = f"{result['service_count']} Audio-Sender auf {info['channel']} gefunden."
    elif result["best"].get("valid"):
        result["message"] = (
            f"{info['channel']} wurde erkannt, aber die Serviceliste ist nicht stabil lesbar. "
            f"Beste Werte: RSSI {result['best'].get('rssi')}, FIC {result['best'].get('FIC_quality')}, "
            f"SNR {result['best'].get('snr')}."
        )
    else:
        result["message"] = f"Auf {info['channel']} wurde kein stabiler DAB-Multiplex gelesen."

    log("Ergebnis: " + result["message"])
    return result


def scan_dab(log_callback=None, timeout=360):
    """Führt einen DAB-Vollscan durch und speichert SCAN_FILE sicher.

    Diese Funktion erwartet, dass der Aufrufer exklusiven Zugriff auf die
    Hardware sicherstellt, z.B. über Supervisor-Lock und cli_file_lock.
    """
    def log(msg):
        if log_callback:
            log_callback(str(msg).rstrip() + "\n")

    backup_file = _backup_scan_file()
    log(f"Backup erstellt: {backup_file}")

    try:
        log("Radio herunterfahren (-k).")
        shutdown_radio()
        time.sleep(1.5)

        log("DAB-Firmware booten (-b D).")
        rc, out = run_radio_cmd(["-b", "D"], timeout=60)
        if out:
            log(out[-1200:])
        if rc != 0:
            raise RuntimeError("Boot fehlgeschlagen: " + out[-800:])

        time.sleep(2.0)

        log("DAB-Vollscan starten (-u -j).")
        rc, out = run_radio_cmd(["-u", "-j"], timeout=timeout)
        if rc != 0:
            log(out[-4000:])
            raise RuntimeError(f"radio_cli -u -j wurde mit rc={rc} beendet.")

        payload, station_count = _decode_scan_payload(out)
        _save_scan_payload(payload)

        loaded = len(load_stations())
        if loaded <= 0:
            restore_scan_backup(backup_file)
            raise RuntimeError("Neue Scan-Datei konnte nicht geladen werden. Backup wurde wiederhergestellt.")

        log(f"Scan gespeichert: {SCAN_FILE}")
        log(f"Gefundene spielbare Sender: {loaded}")
        return {
            "ok": True,
            "backup_file": backup_file,
            "station_count": loaded,
            "raw_station_count": station_count,
            "scan_file": str(SCAN_FILE),
        }
    except Exception:
        restore_scan_backup(backup_file)
        raise


def get_station_text(waittime=5):
    rc, out = run_radio_cmd(["-D", "-z", str(waittime)], timeout=waittime + 5)
    if rc != 0:
        return ""
    return out.strip().splitlines()[-1] if out.strip() else ""
