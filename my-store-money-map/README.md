# MoneyMap

Lokaler Personal Finance Manager fuer Umbrel.

## Funktionen

- CSV-Import fuer Sparkasse, N26 und PayPal
- Automatische Deduplizierung
- Abgleich interner Transfers anhand von Gegenbuchungen
- Keyword- und RegEx-Regeln fuer Kategorien
- Trennung von Fixkosten, variablen Kosten und Einnahmen
- Monatsdashboard und installierbare PWA

## Lokal starten

```bash
DATA_DIR=/tmp/money-map-data python3 app/server.py
```

Danach `http://localhost:8080` oeffnen.

Das Umbrel-Paket verwendet ein offizielles Python-Alpine-Image. Beim ersten
Start wird der zur App-Version passende Quellcode aus dem Git-Tag
`money-map-v0.1.0` in das persistente App-Verzeichnis geladen. Weitere
Container-Neustarts funktionieren aus dieser lokalen Kopie.
