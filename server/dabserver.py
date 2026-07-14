#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path

SCAN_FILE = Path("/usr/local/lib/DABBoard/ensemblescan__.json")
RADIO_CLI = Path("/usr/local/lib/DABBoard/radio_cli_v3.1.0")


def load_ensembles():
    with SCAN_FILE.open("r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)

    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value

    if isinstance(data, list):
        return data

    raise RuntimeError("Keine Ensemble-Liste gefunden.")


def collect_stations():
    stations = []

    for ensemble in load_ensembles():
        if not isinstance(ensemble, dict):
            continue

        status = ensemble.get("DigradStatus", {})
        tune_index = status.get("tune_index")
        tune_freq = status.get("tune_freq")

        service_block = ensemble.get("DigitalServiceList")
        if not service_block:
            continue

        for service in service_block.get("ServiceList", []):
            if service.get("AudioOrDataFlag") != 0:
                continue

            components = service.get("ComponentList", [])
            if not components:
                continue

            stations.append({
                "label": service.get("Label", "").strip(),
                "tune_index": tune_index,
                "tune_freq": tune_freq,
                "service_id": service.get("ServId"),
                "component_id": components[0].get("comp_ID"),
            })

    return stations


def print_stations(stations):
    print()
    print("MWI DAB Server 0.2")
    print("==================")
    print()

    for i, s in enumerate(stations, start=1):
        print(
            f"{i:02d}. {s['label']:<20} "
            f"freq_index={s['tune_index']:<2} "
            f"service={s['service_id']} "
            f"component={s['component_id']}"
        )

    print()


def play_station(station):
    print()
    print(f"▶ Starte {station['label']} ...")
    print()

    cmd = [
        "sudo",
        str(RADIO_CLI),
        "-b", "D",
        "-f", str(station["tune_index"]),
        "-e", str(station["service_id"]),
        "-c", str(station["component_id"]),
        "-p",
    ]

    print("Befehl:")
    print(" ".join(cmd))
    print()

    subprocess.run(cmd)


def main():
    stations = collect_stations()

    if not stations:
        print("Keine Audio-Sender gefunden.")
        return

    while True:
        print_stations(stations)

        choice = input("Sendernummer wählen (0 = Ende): ").strip()

        if choice == "0":
            print("Beendet.")
            return

        if not choice.isdigit():
            print("Bitte eine Zahl eingeben.")
            continue

        number = int(choice)

        if number < 1 or number > len(stations):
            print("Ungültige Sendernummer.")
            continue

        play_station(stations[number - 1])


if __name__ == "__main__":
    main()
