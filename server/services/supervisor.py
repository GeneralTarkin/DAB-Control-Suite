import json
import threading
import time
from pathlib import Path

from services.radio import load_stations, tune_station, shutdown_radio, scan_dab, test_dab_channel
from services.stream import start_stream, stop_stream, stream_status, force_standby_marker, clear_standby_marker, mark_tuning_start, mark_tuning_end
from services.locks import cli_file_lock


class DABSupervisor:
    def __init__(self):
        self.lock = threading.RLock()
        # Serialisiert steuernde Aktionen. Wichtig: Ein zweiter
        # Senderwechsel darf nicht warten und danach veraltet ausgeführt werden.
        self.command_lock = threading.Lock()
        self.current_station = None
        self.current_index = None
        self.switching = False
        self.scanning = False
        # Startet bewusst im Standby. Erst eine Senderwahl oder /api/power/on
        # aktiviert die Radio-Hardware wieder.
        self.power_state_file = Path("cache/power_state.json")
        self.powered_on = self.load_power_state(default=False)
        self.last_station_file = Path("cache/last_station.json")
        self.thread = None
        self.running = False


    def save_power_state(self, powered_on):
        self.power_state_file.parent.mkdir(exist_ok=True)
        if powered_on:
            clear_standby_marker()
        else:
            force_standby_marker()
        tmp = self.power_state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"on": bool(powered_on), "timestamp": time.time()}, indent=2), encoding="utf-8")
        tmp.replace(self.power_state_file)

    def load_power_state(self, default=False):
        try:
            if not self.power_state_file.exists():
                return bool(default)
            data = json.loads(self.power_state_file.read_text(encoding="utf-8", errors="replace"))
            return bool(data.get("on", default))
        except Exception:
            return bool(default)

    def save_last_station(self, index):
        self.last_station_file.parent.mkdir(exist_ok=True)
        self.last_station_file.write_text(json.dumps({"index": index}))

    def load_last_station_index(self):
        try:
            if not self.last_station_file.exists():
                return None
            return int(json.loads(self.last_station_file.read_text()).get("index"))
        except Exception:
            return None

    def clear_runtime_caches(self):
        for name in [
            "cache/metadata.json",
            "cache/dls.json",
            "cache/song_history.json",
        ]:
            try:
                Path(name).unlink(missing_ok=True)
            except Exception:
                pass

    def _find_station_after_scan(self, previous_station, previous_index):
        stations = load_stations()

        if previous_station:
            for i, station in enumerate(stations):
                if (
                    station.get("service_id") == previous_station.get("service_id")
                    and station.get("component_id") == previous_station.get("component_id")
                ):
                    return i, station

        if previous_index is not None and 0 <= previous_index < len(stations):
            return previous_index, stations[previous_index]

        return None, None

    def _log(self, log_callback, msg):
        if log_callback:
            log_callback(msg)
        print(str(msg).rstrip(), flush=True)

    def _wait_for_stream(self, log_callback=None, timeout=12, retry=True):
        """Wartet nach einem Streamstart auf einen gesunden Icecast/ffmpeg-Status.

        Der Stream braucht nach Tune/Scan manchmal einige Sekunden, bis arecord,
        ffmpeg und Icecast wirklich stabil laufen. Diese Methode verhindert,
        dass der Adminbereich zu früh einen Fehler meldet.
        """
        def log(msg):
            self._log(log_callback, msg)

        log("Supervisor: Warte auf Stream und Icecast-Mount...")
        deadline = time.time() + timeout
        last_status = {}

        while time.time() < deadline:
            last_status = stream_status() or {}
            if last_status.get("running"):
                log("Supervisor: Stream ist online.")
                return True
            time.sleep(0.5)

        log(
            "Supervisor: Stream noch nicht gesund "
            f"(process={last_status.get('process_running')}, "
            f"mount={last_status.get('icecast_mount_alive')})."
        )

        if not retry:
            return False

        log("Supervisor: Starte Stream sicherheitshalber erneut...")
        try:
            stop_stream()
        except Exception as exc:
            log(f"Supervisor: Hinweis beim Stoppen des Streams: {exc}")
        time.sleep(1.5)

        try:
            start_stream(restart=True)
        except Exception as exc:
            log(f"Supervisor: Stream-Neustart konnte nicht ausgelöst werden: {exc}")
            return False

        deadline = time.time() + timeout
        last_status = {}
        while time.time() < deadline:
            last_status = stream_status() or {}
            if last_status.get("running"):
                log("Supervisor: Stream ist nach Neustart online.")
                return True
            time.sleep(0.5)

        log(
            "Supervisor: Stream bleibt nach Neustart nicht gesund "
            f"(process={last_status.get('process_running')}, "
            f"mount={last_status.get('icecast_mount_alive')})."
        )
        return False

    def _start_stream_and_wait(self, log_callback=None, timeout=12, restart=False, retry=True):
        if restart:
            self._log(log_callback, "Supervisor: Starte Audio-Stream neu...")
        else:
            self._log(log_callback, "Supervisor: Stelle Audio-Stream sicher...")
        start_stream(restart=restart)
        return self._wait_for_stream(log_callback=log_callback, timeout=timeout, retry=retry)

    def _should_fast_tune(self, index):
        """Fast-Tune nur bei echtem Senderwechsel aus laufendem Betrieb.

        Nach Standby oder ohne bekannten aktuellen Sender bleibt der vollständige
        Bootpfad aktiv. Dadurch bleibt das Aufwecken zuverlässig, während normale
        Senderwechsel deutlich schneller werden.
        """
        return (
            self.powered_on
            and self.current_station is not None
            and self.current_index is not None
            and self.current_index != index
        )

    def play(self, index, save=True):
        """Startet einen Sender oder schaltet darauf um.

        0.10.1: Dieser Pfad ist bewusst als kleiner Zustandsautomat gebaut.
        Während eines Senderwechsels werden keine weiteren Tune-Befehle
        angenommen und Healthchecks/Metadatenabfragen bleiben durch
        stream_tuning.lock außen vor. Dadurch entstehen keine konkurrierenden
        radio_cli-Aufrufe mehr.
        """
        if not self.command_lock.acquire(blocking=False):
            raise RuntimeError("Senderwechsel läuft bereits")

        try:
            stations = load_stations()

            if index < 0 or index >= len(stations):
                raise ValueError("Ungültiger Sender")

            station = stations[index]

            with self.lock:
                self.switching = True
                mark_tuning_start()

                try:
                    self.powered_on = True
                    self.save_power_state(True)
                    t_play_start = time.time()
                    print(f"PLAY TIMING start index={index}", flush=True)
                    print(f"PLAY AUFGERUFEN: index={index}", flush=True)

                    fast_tune = self._should_fast_tune(index)

                    t0 = time.time()
                    self.clear_runtime_caches()
                    print(f"PLAY TIMING clear_runtime_caches {time.time() - t0:.3f}s total={time.time() - t_play_start:.3f}s", flush=True)

                    if fast_tune:
                        print("PLAY FAST-TUNE: Stream bleibt aktiv", flush=True)

                        # Kein stop_stream() im Fast-Tune-Pfad. arecord/ffmpeg
                        # bleiben aktiv, nur das DAB-Board wird umgetuned.
                        t0 = time.time()
                        print(f"PLAY TIMING waiting for cli_file_lock total={time.time() - t_play_start:.3f}s", flush=True)
                        with cli_file_lock(timeout=45):
                            print(f"PLAY TIMING cli_file_lock acquired after {time.time() - t0:.3f}s total={time.time() - t_play_start:.3f}s", flush=True)
                            t_tune = time.time()
                            print(f"PLAY TIMING fast tune_station BEGIN total={time.time() - t_play_start:.3f}s", flush=True)
                            tune_station(station, fast=True)
                        print(f"PLAY TIMING fast tune_station END {time.time() - t_tune:.3f}s total={time.time() - t_play_start:.3f}s", flush=True)

                        self.current_station = station
                        self.current_index = index

                        if save:
                            self.save_last_station(index)

                        # Kurze Einpendelzeit für Audio/Empfang. Nicht auf DLS
                        # warten und den Stream nicht neu starten.
                        t0 = time.time()
                        time.sleep(0.8)
                        print(f"PLAY TIMING fast settle_sleep {time.time() - t0:.3f}s total={time.time() - t_play_start:.3f}s", flush=True)

                        t0 = time.time()
                        start_stream(restart=False)
                        print(f"PLAY TIMING fast start_stream {time.time() - t0:.3f}s total={time.time() - t_play_start:.3f}s", flush=True)

                    else:
                        # Erster Start oder Aufwecken aus Standby: konservativ.
                        stop_stream()
                        time.sleep(0.8)

                        with cli_file_lock(timeout=60):
                            tune_station(station, fast=False)

                        self.current_station = station
                        self.current_index = index

                        if save:
                            self.save_last_station(index)

                        time.sleep(1.2)
                        self._start_stream_and_wait(timeout=12, restart=False, retry=True)

                    print(f"PLAY TIMING finished total={time.time() - t_play_start:.3f}s", flush=True)
                    print(f"PLAY TIMING finished total={time.time() - t_play_start:.3f}s", flush=True)
                    print(f"PLAY TIMING finished total={time.time() - t_play_start:.3f}s", flush=True)
                    print(f"PLAY FERTIG: {station['label']}", flush=True)
                    return station

                finally:
                    # Tuning-Lock noch einen Moment stehen lassen, damit der
                    # externe Streaming-Supervisor nicht genau in der Audio-
                    # Einpendelphase eingreift.
                    time.sleep(1.0)
                    mark_tuning_end()
                    self.switching = False
        finally:
            self.command_lock.release()

    def play_temporary_station(self, station, log_callback=None):
        """Spielt einen nicht gespeicherten Dienst direkt aus Analyzer-Daten.

        Damit können unbekannte Dienste auf 5D probeweise gestartet werden,
        ohne dass sie schon in der normalen Senderliste stehen.
        """
        with self.lock:
            self.switching = True

            def log(msg):
                self._log(log_callback, msg)

            try:
                self.powered_on = True
                self.save_power_state(True)
                label = station.get("label") or f"Service {station.get('service_id')}"
                log(f"Supervisor: Starte temporären Dienst: {label}")
                stop_stream()
                time.sleep(1.0)
                self.clear_runtime_caches()

                with cli_file_lock(timeout=60):
                    tune_station(station, fast=False)

                self.current_station = station
                self.current_index = None
                time.sleep(1.5)
                stream_ok = self._start_stream_and_wait(log_callback=log_callback, timeout=12)
                if not stream_ok:
                    log("Supervisor: Temporärer Dienst wurde getuned, aber der Stream ist noch nicht gesund.")
                else:
                    log(f"Supervisor: Temporärer Dienst läuft: {label}")
                return station

            finally:
                self.switching = False

    def scan(self, log_callback=None):
        """Exklusiver DAB-Suchlauf über die zentrale Radio-Engine."""
        with self.lock:
            self.switching = True
            self.scanning = True

            previous_station = self.current_station
            previous_index = self.current_index

            def log(msg):
                self._log(log_callback, msg)

            try:
                self.powered_on = True
                self.save_power_state(True)
                log("Supervisor: Suchlauf übernimmt exklusiv die Radio-Hardware.")
                stop_stream()
                time.sleep(1.5)
                self.clear_runtime_caches()

                with cli_file_lock(timeout=120):
                    result = scan_dab(log_callback=log_callback)

                # Nach dem Suchlauf ist der Chip auf irgendeiner Scan-Frequenz. Wenn vorher
                # ein Sender lief, versuchen wir, ihn in der neuen Liste wiederzufinden.
                restore_index, restore_station = self._find_station_after_scan(previous_station, previous_index)
                if restore_station is not None:
                    log(f"Supervisor: Stelle vorherigen Sender wieder her: {restore_station.get('label')}")
                    tune_station(restore_station)
                    self.current_station = restore_station
                    self.current_index = restore_index
                    if restore_index is not None:
                        self.save_last_station(restore_index)
                    time.sleep(2.5)
                    stream_ok = self._start_stream_and_wait(log_callback=log_callback, timeout=12)
                    if stream_ok:
                        log("Supervisor: Vorheriger Sender und Stream wurden erfolgreich wiederhergestellt.")
                    else:
                        log("Supervisor: Hinweis: Sender wurde wiederhergestellt, aber der Stream ist noch nicht stabil.")
                else:
                    log("Supervisor: Kein vorheriger Sender in der neuen Liste gefunden.")
                    self.current_station = None
                    self.current_index = None

                return result

            finally:
                self.scanning = False
                self.switching = False


    def analyze_channel(self, index, attempts=6, log_callback=None):
        """Exklusive Mehrfachmessung eines einzelnen DAB-Kanals."""
        with self.lock:
            self.switching = True
            self.scanning = True

            previous_station = self.current_station
            previous_index = self.current_index

            def log(msg):
                self._log(log_callback, msg)

            try:
                self.powered_on = True
                self.save_power_state(True)
                log(f"Supervisor: Kanalanalyse übernimmt exklusiv die Radio-Hardware. Index={index}")
                stop_stream()
                time.sleep(1.5)
                self.clear_runtime_caches()

                with cli_file_lock(timeout=120):
                    result = test_dab_channel(index, attempts=attempts, log_callback=log_callback)

                restore_index, restore_station = self._find_station_after_scan(previous_station, previous_index)
                if restore_station is not None:
                    log(f"Supervisor: Stelle vorherigen Sender wieder her: {restore_station.get('label')}")
                    tune_station(restore_station)
                    self.current_station = restore_station
                    self.current_index = restore_index
                    if restore_index is not None:
                        self.save_last_station(restore_index)
                    time.sleep(2.5)
                    stream_ok = self._start_stream_and_wait(log_callback=log_callback, timeout=12)
                    if stream_ok:
                        log("Supervisor: Vorheriger Sender und Stream wurden erfolgreich wiederhergestellt.")
                    else:
                        log("Supervisor: Hinweis: Sender wurde wiederhergestellt, aber der Stream ist noch nicht stabil.")
                else:
                    log("Supervisor: Kein vorheriger Sender zum Wiederherstellen gefunden.")
                    self.current_station = None
                    self.current_index = None

                return result

            finally:
                self.scanning = False
                self.switching = False

    def stop(self):
        self.power_off()

    def power_off(self):
        with self.lock:
            self.switching = True
            try:
                self.powered_on = False
                self.save_power_state(False)
                stop_stream()
                shutdown_radio()
                stop_stream()
                self.current_station = None
                self.current_index = None
                self.clear_runtime_caches()
            finally:
                self.switching = False

    def power_on(self):
        # Einschalten bedeutet: Standby-Sperre aufheben und den letzten Sender
        # serverseitig wiederherstellen. Das ist zuverlässiger als nur ein
        # Browser-LocalStorage-Wert.
        with self.lock:
            self.powered_on = True
            self.save_power_state(True)

        idx = self.load_last_station_index()
        if idx is None:
            print("Supervisor: Einschalten ohne gespeicherten letzten Sender.", flush=True)
            return False

        return self.restore_last_station()

    def status(self):
        return {
            "current": self.current_station,
            "current_index": self.current_index,
            "switching": self.switching,
            "scanning": self.scanning,
            "stream_status": stream_status(),
            "power": {"on": bool(self.powered_on)},
        }

    def restore_last_station(self):
        idx = self.load_last_station_index()
        if idx is None:
            print("Supervisor: Kein letzter Sender gespeichert.", flush=True)
            return False

        try:
            station = self.play(idx, save=False)
            print(
                f"Supervisor: Letzter Sender wiederhergestellt: {station.get('label')}",
                flush=True,
            )
            return True
        except Exception as exc:
            print(f"Supervisor: Restore fehlgeschlagen: {exc}", flush=True)
            return False

    def watchdog_loop(self):
        time.sleep(20)

        while self.running:
            try:
                if self.switching or self.scanning:
                    time.sleep(1)
                    continue

                st = stream_status()

                if self.switching or self.scanning:
                    time.sleep(1)
                    continue

                self.powered_on = self.load_power_state(default=self.powered_on)
                if not self.powered_on:
                    try:
                        stop_stream()
                    except Exception:
                        pass
                    time.sleep(1)
                    continue

                if self.current_station is None:
                    time.sleep(1)
                    continue

                elif not st.get("running"):
                    if self.command_lock.locked():
                        time.sleep(1)
                        continue
                    print(
                        "Supervisor: Stream nicht gesund, starte aktuellen Sender neu.",
                        flush=True,
                    )
                    self.play(self.current_index, save=False)

            except Exception as exc:
                print(f"Supervisor: Watchdog-Fehler: {exc}", flush=True)

            time.sleep(10)

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        self.running = True
        self.thread = threading.Thread(target=self.watchdog_loop, daemon=True)
        self.thread.start()
        print("Supervisor: gestartet.", flush=True)


supervisor = DABSupervisor()
