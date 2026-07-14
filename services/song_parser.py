import re


PREFIXES = [
    "nu:",
    "now:",
    "jetzt:",
    "aktuell:",
    "on air:",
]


INFO_KEYWORDS = [
    "www.",
    "http",
    ".de",
    ".com",
    "telefon",
    "hotline",
    "studiohotline",
    "whatsapp",
    "gewinn",
    "verlosung",
    "aktion",
    "nachrichten",
    "verkehr",
    "wetter",
    "werbung",
    "radioavisen",
    "radio avis",
    "jetzt einschalten",
    "mehr musik",
]


PROGRAM_HINTS = [
    "radioavisen",
    "nachrichten",
    "news",
    "wetter",
    "verkehr",
    "sendung",
    "show",
]


NOW_MARKERS = [
    "gerade läuft:",
    "gerade laeuft:",
    "gerade l 0xuft:",
    "gerade l0xuft:",
    "jetzt läuft:",
    "jetzt laeuft:",
    "now playing:",
    "now:",
]


NEXT_MARKERS = [
    "demnächst:",
    "gleich:",
    "als nächstes:",
    "als naechstes:",
    "next:",
]


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.strip()
    text = re.sub(r"\s+", " ", text)

    text = re.sub(r"(?i)\bgerade\s+l\s*0x\s*uft\s*:", "gerade läuft:", text)
    text = re.sub(r"(?i)\bjetzt\s+l\s*0x\s*uft\s*:", "jetzt läuft:", text)

    for prefix in PREFIXES:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()

    return text


def cleanup_artist_title(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^[^\wÄÖÜäöüß]+", "", value)
    value = re.sub(r"[\s,;:]+$", "", value)
    return value.strip()


def split_artist_title(text: str):
    clean = normalize_text(text)

    parts = [p.strip() for p in re.split(r"\s[-–]\s", clean, maxsplit=1) if p.strip()]
    if len(parts) < 2:
        return None

    artist = cleanup_artist_title(parts[0])
    title = cleanup_artist_title(parts[1])

    if not artist or not title:
        return None

    return artist, title


def score_candidate(raw: str, artist: str, title: str, remaining_parts=None):
    remaining_parts = remaining_parts or []

    score = 50
    reasons = []

    combined = " ".join([raw, artist, title] + remaining_parts).lower()

    if artist and title:
        score += 20
        reasons.append("artist_title_pattern")

    if 2 <= len(artist) <= 40:
        score += 10
        reasons.append("artist_length_ok")
    else:
        score -= 15
        reasons.append("artist_length_suspicious")

    if 2 <= len(title) <= 80:
        score += 10
        reasons.append("title_length_ok")
    else:
        score -= 15
        reasons.append("title_length_suspicious")

    if any(word in combined for word in INFO_KEYWORDS):
        score -= 35
        reasons.append("info_keyword")

    if any(word in combined for word in PROGRAM_HINTS):
        score -= 30
        reasons.append("program_hint")

    if re.search(r"\b\d{1,2}:\d{2}\b", combined):
        score -= 30
        reasons.append("time_reference")

    if re.search(r"\b\d{3,}[- /\d]{3,}\b", combined):
        score -= 40
        reasons.append("phone_number")

    if "http" in combined or "www." in combined:
        score -= 40
        reasons.append("url")

    score = max(0, min(100, score))

    return score, reasons


def make_song(raw: str, artist: str, title: str, parser: str, confidence: int = 90):
    artist = cleanup_artist_title(artist)
    title = cleanup_artist_title(title)

    if not artist or not title:
        return None

    return {
        "artist": artist,
        "title": title,
        "raw": raw,
        "normalized": f"{artist} - {title}",
        "confidence": confidence,
        "parser": parser,
        "reasons": [parser],
    }


def parse_song(text: str):
    raw = (text or "").strip()
    clean = normalize_text(raw)

    if not clean:
        return None

    if len(clean) < 5 or len(clean) > 220:
        return None

    lowered = clean.lower()

    for marker in NOW_MARKERS:
        if marker in lowered:
            idx = lowered.rfind(marker)
            candidate = clean[idx + len(marker):].strip()
            pair = split_artist_title(candidate)
            if pair:
                return make_song(raw, pair[0], pair[1], "now_marker", 95)

    if any(marker in lowered for marker in NEXT_MARKERS):
        return None

    parts = [p.strip() for p in re.split(r"\s[-–]\s", clean) if p.strip()]

    if len(parts) < 2:
        return None

    artist = parts[0]
    title = parts[1]
    remaining = parts[2:]

    confidence, reasons = score_candidate(raw, artist, title, remaining)

    if confidence < 70:
        return None

    return {
        "artist": artist,
        "title": title,
        "raw": raw,
        "normalized": clean,
        "confidence": confidence,
        "parser": "score_v4",
        "reasons": reasons,
    }


def parse_next_song(text: str):
    raw = (text or "").strip()
    clean = normalize_text(raw)
    lowered = clean.lower()

    for marker in NEXT_MARKERS:
        if marker in lowered:
            idx = lowered.rfind(marker)
            candidate = clean[idx + len(marker):].strip()
            pair = split_artist_title(candidate)
            if pair:
                return make_song(raw, pair[0], pair[1], "next_marker", 90)

    return None


def extract_info_text(text: str):
    clean = normalize_text(text)
    lowered = clean.lower()

    if any(word in lowered for word in INFO_KEYWORDS):
        parts = re.split(r"\s---\s", clean, maxsplit=1)
        return parts[0].strip()

    return ""


def interpret_dls(text: str):
    raw = (text or "").strip()

    result = {
        "raw": raw,
        "type": "empty" if not raw else "unknown",
        "now_playing": None,
        "up_next": None,
        "info": "",
        "display_title": "",
        "display_subtitle": "",
    }

    if not raw:
        return result

    now_song = parse_song(raw)
    next_song = parse_next_song(raw)
    info = extract_info_text(raw)

    result["now_playing"] = now_song
    result["up_next"] = next_song
    result["info"] = info

    if now_song:
        result["type"] = "now_playing"
        result["display_title"] = now_song["title"]
        result["display_subtitle"] = now_song["artist"]
    elif next_song:
        result["type"] = "up_next"
        result["display_title"] = "Als Nächstes: " + next_song["title"]
        result["display_subtitle"] = next_song["artist"]
    elif info:
        result["type"] = "info"
        result["display_title"] = "Senderinfo"
        result["display_subtitle"] = info
    else:
        result["type"] = "text"
        result["display_title"] = raw
        result["display_subtitle"] = ""

    return result
