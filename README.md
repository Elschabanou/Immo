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

## Benutzer-Frontend (Flask + Material UI)

Ein echtes Web-Frontend mit Flask-Backend und Material UI (MUI) fuer andere Nutzer:

- E-Mail eintragen
- Versandfrequenz waehlen (Default: 1x pro Woche)
- Preisfilter einstellen (nur Preis ist anpassbar)

Die Einstellungen werden in der SQLite-Datenbank in `user_subscriptions` gespeichert.

Start:

```bash
python app.py
```

Danach im Browser öffnen:

```text
http://127.0.0.1:5000
```

Optional kann der DB-Pfad über die Umgebungsvariable `DB_PATH` gesetzt werden.

Hinweis: Das Frontend speichert die Abo-Konfiguration. Der eigentliche Mailversand sollte ueber einen separaten Job/Worker ausgefuehrt werden.

## Abo-Mails automatisch versenden

Neues Skript: `send_subscription_emails.py`

Das Skript holt alle faelligen Abos aus `user_subscriptions` (`next_send_at <= jetzt`), sendet eine E-Mail und setzt danach den naechsten Versandzeitpunkt entsprechend der Frequenz (`daily`, `weekly`, `biweekly`, `monthly`).

Pro Empfaenger werden die 10 besten passenden Listings aus `listings` geladen, nach OpenRouter-Bewertung sortiert und als HTML-Newsletter verschickt. Als Tie-Breaker dient der vorhandene `listing_quality_index`.

Wenn keine passenden Listings vorhanden sind, wird trotzdem eine Mail mit einem kurzen Hinweis erzeugt.

Die SMTP-Zugangsdaten werden lokal aus einer Datei namens `.env` geladen. Dort gehoeren nur einfache `KEY=VALUE`-Zeilen hinein, zum Beispiel:

```text
SMTP_USER=porschehousing@gmail.com
SMTP_PASSWORD=DEIN_GMAIL_APP_PASSWORT
```

Die Datei wird nicht in Git eingecheckt.

Optional:

- `SMTP_HOST` (Default: `smtp.gmail.com`)
- `SMTP_PORT` (Default: `587`)
- `FROM_EMAIL` (Default: Wert von `SMTP_USER`)
- `MAIL_SUBJECT` (Default: `Abo Update`)
- `MAIL_BODY` (Default: Ein kurzer Newsletter-Introtext)

Testlauf ohne echten Versand:

```bash
python send_subscription_emails.py --dry-run
```

Echter Versand:

```bash
python send_subscription_emails.py
```

Fuer automatischen Versand in der gewuenschten Frequenz das Skript regelmaessig (z. B. alle 15 oder 30 Minuten) ueber die Windows Aufgabenplanung starten.

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

Zusätzliche Felder der Mietspiegel-Bewertung:

- `valuation_model`
- `valuation_run_at`
- `est_cold_rent_sqm`
- `est_cold_rent_monthly`
- `est_cold_rent_min_monthly`
- `est_cold_rent_max_monthly`
- `gross_yield_pct`
- `price_to_rent_factor`
- `valuation_confidence`
- `valuation_note`
- `listing_quality_index`
- `listing_quality_grade`
- `listing_quality_note`

Zusaetzliche Felder der OpenRouter-Bewertung:

- `ai_rating_model`
- `ai_rating_run_at`
- `ai_rating_score`
- `ai_rating_reason`
- `ai_rating_error`

## Pagination-Logik

- Seite 1: Basis-URL ohne `seite:n`
- Seite n (n ≥ 2): Einfügen von `seite:n` vor dem letzten Segment (`c196l9280r50`)
- Crawl stoppt, wenn eine Seite leer ist oder keine neuen Anzeigen mehr gespeichert werden.

## Mietspiegel-Bewertung

Nach dem Crawl wird automatisch eine Mietspiegel-basierte Bewertung für alle gespeicherten Anzeigen berechnet.

- Das Modell ist `stuttgart_mietspiegel_heuristic_v1`.
- Es nutzt verfügbare Listing-Merkmale wie Lage (PLZ/Ort), Wohnfläche, Zimmer und Textmerkmale.
- Die Ausgabe enthält geschätzte monatliche Nettokaltmiete (Mittelwert und Bandbreite), Bruttorendite und Kaufpreisfaktor.

Hinweis: Diese Bewertung ist eine technische Näherung zur Vorselektion und ersetzt keine amtliche Auskunft oder rechtliche Mietspiegelberechnung.

## OpenRouter-Bewertung

Nach dem Crawl werden neue Listings automatisch mit einem OpenRouter-Modell bewertet.

- Bewertet werden nur Listings, die noch keinen erfolgreichen AI-Zeitstempel besitzen.
- Die Konfiguration kommt aus `.env` ueber `API_KEY`, `OPENROUTER_API_URL` und `MODEL_NAME`.
- Das Ergebnis wird im Datensatz gespeichert und spaeter fuer das Newsletter-Ranking verwendet.

## Qualitätsindex pro Inserat

Zusätzlich wird pro Inserat ein Qualitätsindex im Bereich 0 bis 100 berechnet:

- `listing_quality_index`: numerischer Gesamtscore
- `listing_quality_grade`: Klasse `A` bis `E`
- `listing_quality_note`: kompakte Diagnose der Teilfaktoren

Der Score kombiniert Datenvollständigkeit, Plausibilität, geschätzte Rendite, Kaufpreisfaktor sowie Modell-Confidence.
