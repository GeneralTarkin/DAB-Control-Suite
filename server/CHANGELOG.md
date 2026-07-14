# DAB-API 0.10.1 – stabilisierte Umschaltlogik

- Supervisor mit serieller Umschaltsteuerung: nur ein Senderwechsel gleichzeitig.
- Veraltete/parallel laufende Tune-Befehle werden abgewiesen statt wartend gestapelt.
- Metadaten- und Radio-Engine-Abfragen pausieren während des Tunings.
- Streaming-Supervisor bekommt Schonfrist während und direkt nach Senderwechsel.
- Harte Stream-Neustarts erst nach mehreren fehlgeschlagenen Healthchecks.
- Ziel: weniger schwankende Umschaltzeiten und keine `radio_cli ist gerade beschäftigt`-Kaskaden.
