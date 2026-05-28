#!/usr/bin/env python
"""
🚀 Quick-Start für PostgreSQL Migration und Render Deployment
Dieses Skript führt Sie durch alle Schritte
"""
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """Führt ein Shell-Kommando aus"""
    print(f"\n▶️  {description}")
    print(f"   Befehl: {cmd}")
    print("   " + "=" * 70)
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"❌ Fehler beim Ausführen des Befehls")
        return False
    return True


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                  🚀 SQLite → PostgreSQL → Render Deployment                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

    print("""
📋 SCHRITT-FÜR-SCHRITT ANLEITUNG:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣  DATABASE_URL VON RENDER BESORGEN
   • Gehen Sie zu https://dashboard.render.com
   • Klicken Sie auf "Databases" → "Immo-DB"
   • Kopieren Sie die "External Database URL"
   
2️⃣  DATEN MIGRIEREN
   • Führen Sie: python migrate_to_render.py
   • Geben Sie die DATABASE_URL ein
   • Das Skript migriert alle Daten
   
3️⃣  CHANGES ZU GITHUB PUSHEN
   • git add .
   • git commit -m "Migration zu PostgreSQL"
   • git push origin master
   
4️⃣  AUF RENDER DEPLOYEN
   • https://dashboard.render.com/blueprints
   • "New" → "Blueprint" → Verbinden Sie Ihr GitHub-Repo
   • Render erstellt alle Services automatisch
   
5️⃣  DATABASE_URL ZU SERVICES HINZUFÜGEN
   • Für jede Service in Render Dashboard:
   • Environment → DATABASE_URL hinzufügen
   • Wert: [External Database URL kopieren]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

    # Frage den Benutzer, ob er beginnen möchte
    response = input("▶️  Möchten Sie jetzt mit der Migration starten? (ja/nein): ").lower().strip()

    if response not in ("ja", "yes", "j", "y"):
        print("\n❌ Abgebrochen. Sie können später `python migrate_to_render.py` ausführen.")
        sys.exit(0)

    # Führe die Migration durch
    print("\n" + "=" * 80)
    print("MIGRATION WIRD GESTARTET")
    print("=" * 80)

    if not run_command("python migrate_to_render.py", "Starte PostgreSQL Migration"):
        sys.exit(1)

    print("\n" + "=" * 80)
    print("✅ MIGRATION ABGESCHLOSSEN")
    print("=" * 80)

    print("""
📝 NÄCHSTE SCHRITTE:

1. Geben Sie diese Befehle ein:
   git add .
   git commit -m "Migration zu PostgreSQL"
   git push origin master

2. Gehen Sie zu https://dashboard.render.com/blueprints

3. Klicken Sie "New" → "Blueprint"

4. Verbinden Sie Ihr GitHub-Repository (Immo-Projekt)

5. Render wird die Services automatisch erstellen!

6. Nach dem Deployment: Setzen Sie DATABASE_URL in jeder Service:
   • Web Service → Environment → DATABASE_URL = [External Database URL]
   • Cron Job 1 → Environment → DATABASE_URL = [External Database URL]  
   • Cron Job 2 → Environment → DATABASE_URL = [External Database URL]

✨ Das war es! Ihre App läuft jetzt auf Render mit PostgreSQL!

📚 Für Fragen: Schauen Sie in MIGRATION_GUIDE.md
""")


if __name__ == "__main__":
    main()
