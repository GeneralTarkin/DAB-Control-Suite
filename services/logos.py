#!/usr/bin/env python3
import re
import unicodedata
from pathlib import Path

LOGO_DIR = Path("static/logos")


def logo_slug(label):
    if not label:
        return "unknown"

    text = label.strip().lower()

    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "ø": "oe",
        "æ": "ae",
        "å": "aa",
        "&": "and",
        "+": "plus",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")

    return text or "unknown"


def logo_path_for_station(label):
    slug = logo_slug(label)
    path = LOGO_DIR / f"{slug}.png"

    if path.exists():
        return f"/static/logos/{slug}.png"

    return ""
