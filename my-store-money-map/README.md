# MoneyMap

Lokaler Personal Finance Manager fuer Umbrel.

## Funktionen

- CSV-Import fuer Sparkasse, N26 und PayPal
- Automatische Deduplizierung
- Abgleich interner Transfers anhand von Gegenbuchungen
- Keyword- und RegEx-Regeln fuer Kategorien
- Trennung von Fixkosten, variablen Kosten und Einnahmen
- Eigene Investment-Ansicht fuer MSCI World, Bitcoin, Aktien und Langzeitkonto
- Quellenfilter fuer Sparkasse, N26 und PayPal
- Auslagen-Abgleich sowie Kategorie Bargeld
- Kategorienuebersicht nach Nutzung mit Aufraeumfunktion
- Persoenliche Kostenansicht mit Verrechnung von WG-Einnahmen
- Eigene WG-Auswertung fuer Wohnen und Haushalt mit frei waehlbarem Zeitraum
- Interaktives Sankey-Diagramm mit Zeitraum-, Konto-, Fluss- und Kategorienfiltern
- Drill-down von Kategorien ueber Gegenparteien bis zu einzelnen Buchungen
- Zoom, Verschieben, Suche und vollstaendige Saldodarstellung im Geldfluss
- Monatsdashboard und installierbare PWA

## Lokal starten

```bash
DATA_DIR=/tmp/money-map-data python3 app/server.py
```

Danach `http://localhost:8080` oeffnen.

Das Umbrel-Paket verwendet ein offizielles Python-Alpine-Image. Beim ersten
Start wird der zur App-Version passende Quellcode aus dem Git-Tag
`money-map-v0.5.1` in das persistente App-Verzeichnis geladen. Weitere
Container-Neustarts funktionieren aus dieser lokalen Kopie.
