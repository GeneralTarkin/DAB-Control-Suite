#!/usr/bin/env python3

import json
from pathlib import Path
from datetime import datetime

HISTORY_FILE = Path("cache/song_history.json")
MAX_HISTORY = 200
MIN_CONFIDENCE = 70


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return []


def save_history(history):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def add_song(song):
    if not song:
        return

    confidence = int(song.get("confidence", 0))
    if confidence < MIN_CONFIDENCE:
        return

    artist = (song.get("artist") or "").strip()
    title = (song.get("title") or "").strip()

    if not artist or not title:
        return

    history = load_history()

    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "artist": artist,
        "title": title,
        "confidence": confidence,
        "parser": song.get("parser"),
        "raw": song.get("raw"),
    }

    if history:
        last = history[-1]
        if last.get("artist") == artist and last.get("title") == title:
            return

    history.append(entry)
    history = history[-MAX_HISTORY:]
    save_history(history)
