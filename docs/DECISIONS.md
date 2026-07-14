# MWI DAB Server – Architekturentscheidungen

## ADR-001: Persistenter DLS-Listener statt DLS-Polling

### Status

Geplant

### Kontext

Der bisherige Metadata-Worker ruft regelmäßig `radio_cli -D -z <waittime>` auf, um Radiotext zu lesen.

In Tests zeigte sich, dass manuelle Aufrufe von `radio_cli -D -z 5` Radiotext liefern, während Aufrufe aus Python über `subprocess.run()` häufig nur Startmeldungen liefern, aber keinen DLS-Text.

Dadurch bleibt `station_text` in der REST-API teilweise leer, obwohl das DAB-Board grundsätzlich Radiotext empfängt.

### Entscheidung

Der DLS-Abruf soll von periodischem Polling auf einen persistenten Listener umgestellt werden.

Der neue Listener startet `radio_cli -D` als dauerhaften Prozess und liest dessen Standardausgabe kontinuierlich zeilenweise aus.

### Begründung

- weniger Prozessstarts
- geringere Fehleranfälligkeit
- geringere CPU-Last
- weniger verlorene DLS-Ereignisse
- bessere Testbarkeit
- sauberere Trennung von Datenquelle und API
- bessere Grundlage für WordPress-Integration
- wissenschaftlich besser begründbare Architektur

### Konsequenzen

- `workers/dls_listener.py` wird als eigener Worker eingeführt
- `cache/dls.json` speichert den letzten gültigen Radiotext
- `metadata_worker.py` liest künftig den letzten DLS-Wert aus dem Cache
- `services/metadata.py` muss DLS nicht mehr selbst pollen

## ADR-002: Persistenter `radio_cli -D`-Prozess verworfen

### Status

Verworfen

### Kontext

Es wurde getestet, ob `radio_cli -D -z 999999` als dauerhafter DLS-Stream genutzt werden kann.

Der Prozess startet und gibt Initialisierungszeilen aus, liefert danach aber keine kontinuierlichen DLS-Zeilen.

### Ergebnis

Die Hypothese eines nutzbaren DLS-Streams über einen dauerhaft geöffneten `radio_cli`-Prozess wurde verworfen.

### Konsequenz

Der DLS-Abruf muss weiterhin über einzelne `radio_cli -D -z <waittime>`-Aufrufe erfolgen.

Statt blindem Polling wird ein kontrollierter Poller mit folgenden Eigenschaften entwickelt:

- nur ein DLS-Abfrageprozess gleichzeitig
- längere Wartezeit
- Backoff bei leeren Ergebnissen
- Pufferung des letzten gültigen Radiotexts
- separate Cache-Datei `cache/dls.json`
- klare Messbarkeit von Erfolgsrate und Latenz
