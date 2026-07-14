"""Robuste Textdekodierung fuer DAB-/radio_cli-Ausgaben.

radio_cli liefert je nach Ausgabeart und Sender keine einheitliche Kodierung.
Diese Hilfsfunktionen sammeln die Zeichenkorrektur an einer zentralen Stelle,
damit DLS, Metadaten und Parser nicht jeweils eigene Sonderregeln brauchen.
"""

from __future__ import annotations

import html
import re
import unicodedata


def decode_radio_cli_bytes(raw: bytes | bytearray | None) -> str:
    """Dekodiert rohe radio_cli-Bytes moeglichst verlustarm.

    Reihenfolge:
    1. UTF-8, falls die Ausgabe bereits korrekt ist.
    2. Windows-1252, weil viele Sonderzeichen dort sinnvoller abgebildet sind.
    3. Latin-1 als verlustfreier Fallback.

    Anschliessend werden typische Mojibake- und radio_cli-Hex-Fragmente
    normalisiert.
    """
    if not raw:
        return ""

    data = bytes(raw)

    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding, errors="strict")
            return normalize_dab_text(text)
        except UnicodeDecodeError:
            continue

    return normalize_dab_text(data.decode("latin-1", errors="replace"))


def _repair_utf8_mojibake(text: str) -> str:
    """Repariert klassische UTF-8-als-Latin-1-Fehler wie 'lÃ¤uft'."""
    if not text:
        return ""

    # Nur versuchen, wenn typische Mojibake-Marker vorkommen.
    if not any(marker in text for marker in ("Ã", "Â", "â")):
        return text

    try:
        repaired = text.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
        # Reparatur nur uebernehmen, wenn sie sichtbar plausibler ist.
        if repaired.count("�") <= text.count("�"):
            return repaired
    except Exception:
        pass

    return text


def normalize_dab_text(text: object) -> str:
    """Normalisiert DAB-Radiotext und repariert bekannte radio_cli-Artefakte."""
    if text is None:
        return ""

    text = str(text)
    if not text:
        return ""

    text = html.unescape(text)
    text = _repair_utf8_mojibake(text)
    text = unicodedata.normalize("NFC", text)

    # Steuerzeichen entfernen, normale Leerzeichen erhalten.
    text = "".join(ch if (ch in "\n\r\t" or ord(ch) >= 32) else " " for ch in text)

    replacements = {
        "l 0xuft": "läuft",
        "l0xuft": "läuft",
        "l 0x uft": "läuft",
        "l 0x91uft": "läuft",
        "l0x91uft": "läuft",
        "l 0x▒uft": "läuft",
        "l0x▒uft": "läuft",
        "l 0x�uft": "läuft",
        "l0x�uft": "läuft",
        "l�uft": "läuft",
        "l äuft": "läuft",
        "laeuft": "läuft",
        "Laeuft": "Läuft",
        "demn ächst": "demnächst",
        "demnaechst": "demnächst",
        "Demnaechst": "Demnächst",
        "f�r": "für",
        "F�r": "Für",
        "fuer": "für",
        "Fuer": "Für",
        "�ber": "über",
        "ueber": "über",
        "Ueber": "Über",
        "sch�n": "schön",
        "Sch�n": "Schön",
        "gro�e": "große",
        "Gro�e": "Große",
        "gr��e": "größe",
        "Gr��e": "Größe",
    }

    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # Kontextbezogene Reparatur fuer radio_cli-Hex-Fragmente.
    # Beispiel: "gerade l 0xuft:" oder "jetzt l 0x91uft:".
    text = re.sub(
        r"(?i)\b(gerade|jetzt)\s+l\s*0x(?:[0-9a-f]{0,2}|[�▒]{0,2})\s*uft\s*:",
        lambda m: f"{m.group(1).lower()} läuft:",
        text,
    )
    text = re.sub(r"(?i)\bl\s*0x[^\s:;-]{0,4}uft\b", "läuft", text)
    text = re.sub(r"(?i)\bl\s*0x[^\s:;-]{0,4}ft\b", "läuft", text)
    text = re.sub(r"(?i)\b(gerade|jetzt)\s+l\s*0x[^\s:;-]{0,4}ft\s*:", lambda m: f"{m.group(1).lower()} läuft:", text)
    text = re.sub(r"(?i)\bl\s*[äa]\s*uft\b", "läuft", text)
    text = re.sub(r"(?i)\bdemn\s*0x[^\s:;-]{0,4}chst\b", "demnächst", text)
    text = re.sub(r"(?i)\bdemn\s*[äa]\s*chst\b", "demnächst", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([:;,.!?])", r"\1", text)
    return text.strip()
