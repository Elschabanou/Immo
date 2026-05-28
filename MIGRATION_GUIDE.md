# 🚀 SQLite zu PostgreSQL Migration - Render Deployment

## 📋 Schritte zur Migration

### Schritt 1: PostgreSQL-Migration durchführen

```bash
# Aktivieren Sie Ihre virtuelle Umgebung (falls noch nicht aktiv)
.venv\Scripts\activate

# Oder mit Python direkt
python migrate_to_render.py
```

Das Skript wird Sie auffordern:
1. Die **External Database URL** von Render eingeben (von Dashboard kopieren)
2. Die Verbindung testen
3. Das PostgreSQL-Schema erstellen
4. Daten von SQLite nach PostgreSQL migrieren

### Schritt 2: DATABASE_URL in .env.production speichern

Das Skript speichert die DATABASE_URL automatisch in `.env.production`. Diese Datei wird nicht versioniert (siehe .gitignore).

### Schritt 3: Änderungen zu GitHub pushen

```bash
git add .
git commit -m "Migration zu PostgreSQL und Render-Deployment"
git push origin master
```

### Schritt 4: Render-Umgebungsvariablen konfigurieren

1. Gehen Sie zu https://dashboard.render.com
2. Für jeden Service (Web + Cron Jobs):
   - Öffnen Sie den Service
   - Gehen Sie zu "Environment"
   - Fügen Sie eine neue Umgebungsvariable hinzu:
     - **Key:** `DATABASE_URL`
     - **Value:** [Kopieren Sie die External Database URL von der Immo-DB Seite]

   Oder: Verwenden Sie die **Internal Database URL** für Services auf Render (diese ist sicherer)

### Schritt 5: Services auf Render deployen

Option A: Über render.yaml Blueprint (empfohlen)
- Gehen Sie zu https://dashboard.render.com/blueprints
- Wählen Sie "New → Blueprint"
- Verbinden Sie Ihr GitHub-Repository
- Render erstellt alle Services automatisch

Option B: Services manuell erstellen
- Für jeden Service in `render.yaml`:
  - Web Service: `immo-web`
  - Cron Job 1: `immo-scraper`
  - Cron Job 2: `immo-mails`

## 🔍 Überprüfen der Migration

Nach dem Deployment können Sie überprüfen, ob alles funktioniert:

```bash
# Lokal testen (mit DATABASE_URL Umgebungsvariable gesetzt)
python app.py
```

Oder sehen Sie die Logs in der Render Dashboard:
- Web Service Logs: https://dashboard.render.com/services
- Cron Job Logs: https://dashboard.render.com/services (Cron Logs)

## 📚 Wichtige Dateien

- **setup_postgres.py** - Erstellt das PostgreSQL-Schema bei jedem Web Service Start
- **migrate_to_render.py** - Interaktives Migrations-Tool für lokale Daten
- **render.yaml** - Render-Deployment-Konfiguration
- **.env.production** - DATABASE_URL (lokal, nicht versioniert)

## 🆘 Häufige Probleme

### Problem: "DATABASE_URL ist nicht gesetzt"
**Lösung:** 
- Stellen Sie sicher, dass Sie `DATABASE_URL` in den Render Service-Umgebungsvariablen gesetzt haben
- Oder setzen Sie die Umgebungsvariable in `.env` lokal

### Problem: "Verbindung zu PostgreSQL fehlgeschlagen"
**Lösung:**
- Überprüfen Sie, dass die Datenbank auf Render noch aktiv ist
- Prüfen Sie, dass die DATABASE_URL korrekt ist
- Prüfen Sie IP-Allow-List: https://dashboard.render.com/databases (sollte 0.0.0.0/0 sein)

### Problem: "Migrationsskript schlägt fehl"
**Lösung:**
- Stellen Sie sicher, dass psycopg installiert ist: `pip install psycopg[binary]`
- Überprüfen Sie die Fehlermeldung im Skript
- Prüfen Sie, dass die SQLite-Datei vorhanden ist

## 🎯 Nächste Schritte nach dem Deployment

1. ✅ Überprüfen Sie die Web-Service URL
2. ✅ Testen Sie die Subscriptions API
3. ✅ Überwachen Sie die Cron-Jobs (Logs)
4. ✅ Stellen Sie sicher, dass E-Mails versendet werden

## 📖 Weitere Ressourcen

- Render Dokumentation: https://render.com/docs
- PostgreSQL Dokumentation: https://www.postgresql.org/docs/
- Flask mit PostgreSQL: https://flask.palletsprojects.com/
