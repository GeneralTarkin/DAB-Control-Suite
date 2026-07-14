# MWI DAB Server – Architektur

## Ziel

Der MWI DAB Server ist eine modulare DAB+-Streaming-Plattform für Embedded-Linux-Systeme.

## Grundprinzip

Flask dient nur als Web- und API-Schicht.

Hintergrundprozesse sammeln kontinuierlich Daten und schreiben diese in Cache-Dateien.

## Komponenten

- Flask Dashboard
- REST-API
- Metadata Worker
- DLS Listener
- Icecast Streaming
- Logo Manager
- Song History
- Cache Layer

## Architekturentscheidung

Radiotext soll künftig nicht mehr durch wiederholtes Polling abgefragt werden.

Stattdessen wird ein persistenter DLS-Listener verwendet, der `radio_cli` dauerhaft geöffnet hält und neue Radiotext-Zeilen kontinuierlich verarbeitet.

Begründung:

- weniger Prozessstarts
- geringere Fehleranfälligkeit
- weniger verlorene DLS-Ereignisse
- bessere Testbarkeit
- bessere wissenschaftliche Begründbarkeit
