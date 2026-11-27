# data/

Nichts hier wird in `main` eingecheckt (`.gitignore`): der Inhalt gehoert in einen anderen
Branch, ist abgeleitet oder darf den Rechner nicht verlassen.

| Ordner | Inhalt |
|---|---|
| `warehouse/` | Worktree des Branch `data`: die gesammelten Staende als Parquet-Dateien |
| `state/` | die rohe Momentaufnahme des letzten Laufs, nur bis zum naechsten |
| `local/` | Abzuege von ForeverDB und die lokale DuckDB-Datei - verlassen diesen Rechner nicht |
| `raw/` | rohe Antworten der API, wie `verify` und `publish` sie holen |
| `verify/` | die Berichte von `python -m collector verify` |
