#!/usr/bin/env python3
import re
import unicodedata
from pathlib import Path

LOGO_DIR = Path("static/logos")


def logo_slug(label):
    """Return the canonical station-logo slug.

    This is the only place in the backend that defines how a station label
    becomes a logo filename. Frontends should use the logo fields returned by
    the API instead of duplicating this logic.
    """
    if not label:
        return "unknown"

    text = str(label).strip().lower()

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


def logo_filename_for_station(label):
    return f"{logo_slug(label)}.png"


def logo_file_for_station(label):
    return LOGO_DIR / logo_filename_for_station(label)


def logo_api_path_for_filename(filename):
    # Served by app.py as /api/logos/<filename>; public reverse proxy path is
    # /dab-api/logos/<filename>.
    return f"/api/logos/{filename}"


def logo_path_for_station(label):
    filename = logo_filename_for_station(label)
    path = LOGO_DIR / filename

    if path.exists():
        return logo_api_path_for_filename(filename)

    return ""


def default_logo_path():
    default_file = LOGO_DIR / "default.png"
    if default_file.exists():
        return logo_api_path_for_filename("default.png")
    return ""


def logo_info_for_station(label):
    filename = logo_filename_for_station(label)
    path = LOGO_DIR / filename
    exists = path.exists()
    return {
        "logo_slug": logo_slug(label),
        "logo_filename": filename,
        "logo_exists": exists,
        "logo": logo_api_path_for_filename(filename) if exists else "",
        "logo_fallback": default_logo_path(),
    }
