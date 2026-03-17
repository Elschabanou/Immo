# Kleinanzeigen Immobilien-Scraper (Stuttgart, Eigentumswohnungen)

Dieses Skript crawlt Kleinanzeigen-Listings für Eigentumswohnungen in Stuttgart (max. 180.000 €, Umkreis 50 km) über die Suchseiten-Pagination und speichert die Daten in SQLite.

## Installation

```bash
pip install -r requirements.txt
```

## Ausführen

```bash
python kleinanzeigen_scraper.py
```

Optionale Parameter:

- `--db <pfad>`: SQLite-Datei (Standard: `kleinanzeigen_listings.db`)
- `--max-pages <n>`: maximale Seitenzahl
- `--delay <sekunden>`: Pause zwischen Seitenabrufen (Standard: `1.0`)
- `--base-url <url>`: alternative Such-URL

## Gespeicherte Felder

Tabelle `listings`:

- `listing_id` (Primary Key)
- `title`
- `price_eur`
- `area_sqm`
- `rooms`
- `location`
- `url`
- `description`
- `created_at`

## Pagination-Logik

- Seite 1: Basis-URL ohne `seite:n`
- Seite n (n ≥ 2): Einfügen von `seite:n` vor dem letzten Segment (`c196l9280r50`)
- Crawl stoppt, wenn eine Seite leer ist oder keine neuen Anzeigen mehr gespeichert werden.
