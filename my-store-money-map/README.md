# MoneyMap

Lokaler Personal Finance Manager fuer Umbrel.

## Funktionen

- CSV-Import fuer Sparkasse, N26 und PayPal
- Automatische Deduplizierung
- Abgleich interner Transfers anhand von Gegenbuchungen
- Keyword- und RegEx-Regeln fuer Kategorien
- Trennung von Fixkosten, variablen Kosten und Einnahmen
- Eigene Investment-Ansicht fuer MSCI World, Bitcoin, Aktien und Langzeitkonto
- Live-Schaetzung fuer MSCI World und Bitcoin aus Buchungstags- und aktuellen Kursen
- Quellenfilter fuer Sparkasse, N26 und PayPal
- Auslagen-Abgleich sowie Kategorie Bargeld
- Kategorienuebersicht nach Nutzung mit Aufraeumfunktion
- Persoenliche Kostenansicht mit Verrechnung von WG-Einnahmen
- Eigene WG-Auswertung fuer Wohnen und Haushalt mit frei waehlbarem Zeitraum
- Einstellbare prozentuale Aufteilung der WG-Einnahmen auf Wohnen und Haushalt
- Interaktives Sankey-Diagramm mit Zeitraum-, Konto-, Fluss- und Kategorienfiltern
- Konto-zu-Konto-Darstellung interner Transfers zwischen Sparkasse, N26 und PayPal
- Klickfixierte Detailansicht bis zu einzelnen Buchungen, Suche und vollstaendige Saldodarstellung
- Umschaltbare Betrags- oder Prozentanzeige im Geldfluss
- Monats- und Jahresansicht fuer Dashboard und Buchungen
- Installierbare PWA

## Datenschutz

- Kontoauszuege und Auswertungen liegen ausschliesslich im lokalen
  Umbrel-App-Datenverzeichnis und gehoeren nicht zum Git-Repository.
- Der Datenserver ist nur mit dem authentifizierten Umbrel-App-Proxy ueber ein
  privates internes Docker-Netz verbunden. Ein separates Ausgangsnetz dient
  ausschliesslich dem Abruf oeffentlicher Kursdaten. Andere App-Container
  koennen die API nicht direkt erreichen.

## Lokal starten

```bash
DATA_DIR=/tmp/money-map-data python3 app/server.py
```

Danach `http://localhost:8080` oeffnen.

Das Umbrel-Paket verwendet ein offizielles Python-Alpine-Image. Beim ersten
Start wird der zur App-Version passende Quellcode aus dem Git-Tag
`money-map-v0.5.6` in das persistente App-Verzeichnis geladen. Weitere
Container-Neustarts funktionieren aus dieser lokalen Kopie.
