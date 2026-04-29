from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "kleinanzeigen_listings.db"
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FREQUENCY_DAYS = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}

app = Flask(__name__)


def get_db_path() -> Path:
    configured = os.getenv("DB_PATH", str(DEFAULT_DB_PATH))
    return Path(configured).expanduser()


def db_connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def listings_table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='listings'"
    ).fetchone()
    return row is not None


def initialize_user_subscription_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            frequency TEXT NOT NULL DEFAULT 'weekly',
            max_price_eur INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_sent_at TEXT,
            next_send_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_subscriptions_next_send ON user_subscriptions(next_send_at)"
    )
    connection.commit()


def is_valid_email(email: str) -> bool:
    return EMAIL_PATTERN.match(email.strip()) is not None


def next_send_timestamp(frequency: str) -> str:
    days = FREQUENCY_DAYS.get(frequency, 7)
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/subscriptions/manage")
def subscriptions_manage() -> str:
    return render_template("subscriptions.html")


@app.route("/api/meta", methods=["GET"])
def api_meta():
    db_path = get_db_path()
    if not db_path.exists():
        return jsonify({"error": f"Datenbank nicht gefunden: {db_path}"}), 404

    with db_connect(db_path) as connection:
        initialize_user_subscription_table(connection)

        listings_count = 0
        avg_price = None
        min_price = None
        max_price = None
        latest = None

        if listings_table_exists(connection):
            listings_count = connection.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
            price_row = connection.execute(
                "SELECT AVG(price_eur) AS avg_price, MIN(price_eur) AS min_price, MAX(price_eur) AS max_price FROM listings"
            ).fetchone()
            latest = connection.execute("SELECT MAX(created_at) AS latest FROM listings").fetchone()["latest"]
            avg_price = price_row["avg_price"]
            min_price = price_row["min_price"]
            max_price = price_row["max_price"]

        stats_rows = connection.execute(
            """
            SELECT frequency, COUNT(*) AS cnt
            FROM user_subscriptions
            WHERE is_active = 1
            GROUP BY frequency
            """
        ).fetchall()

    stats = {row["frequency"]: int(row["cnt"]) for row in stats_rows}
    return jsonify(
        {
            "dbPath": str(db_path),
            "listingsCount": int(listings_count),
            "avgPrice": int(avg_price) if avg_price else None,
            "minPrice": int(min_price) if min_price else None,
            "maxPrice": int(max_price) if max_price else None,
            "latestCrawl": latest,
            "subscriptionStats": stats,
        }
    )


@app.route("/api/preview", methods=["GET"])
def api_preview():
    db_path = get_db_path()
    if not db_path.exists():
        return jsonify({"error": f"Datenbank nicht gefunden: {db_path}"}), 404

    max_price = request.args.get("max_price", type=int)
    limit = request.args.get("limit", default=20, type=int)

    if max_price is None or max_price <= 0:
        return jsonify({"error": "max_price muss als positive Zahl gesetzt werden."}), 400

    with db_connect(db_path) as connection:
        if not listings_table_exists(connection):
            return jsonify({"rows": []})

        rows = connection.execute(
            """
            SELECT listing_id, title, price_eur, location, created_at, url
            FROM listings
            WHERE price_eur <= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max_price, max(1, min(limit, 100))),
        ).fetchall()

    data = [dict(row) for row in rows]
    return jsonify({"rows": data})


@app.route("/api/subscription", methods=["POST"])
def api_subscription_upsert():
    db_path = get_db_path()
    if not db_path.exists():
        return jsonify({"error": f"Datenbank nicht gefunden: {db_path}"}), 404

    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    frequency = str(payload.get("frequency", "weekly")).strip().lower()
    max_price = payload.get("maxPriceEur")

    if not is_valid_email(email):
        return jsonify({"error": "Bitte gueltige E-Mail-Adresse angeben."}), 400
    if frequency not in FREQUENCY_DAYS:
        return jsonify({"error": "Ungueltige Frequenz."}), 400
    if not isinstance(max_price, int) or max_price < 50000:
        return jsonify({"error": "maxPriceEur muss eine ganze Zahl >= 50000 sein."}), 400

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    next_send_at = next_send_timestamp(frequency)

    with db_connect(db_path) as connection:
        initialize_user_subscription_table(connection)
        connection.execute(
            """
            INSERT INTO user_subscriptions (
                email,
                frequency,
                max_price_eur,
                is_active,
                created_at,
                updated_at,
                next_send_at
            )
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                frequency = excluded.frequency,
                max_price_eur = excluded.max_price_eur,
                is_active = 1,
                updated_at = excluded.updated_at,
                next_send_at = excluded.next_send_at
            """,
            (email, frequency, max_price, timestamp, timestamp, next_send_at),
        )
        connection.commit()

    return jsonify(
        {
            "message": "Abo gespeichert.",
            "subscription": {
                "email": email,
                "frequency": frequency,
                "maxPriceEur": max_price,
                "nextSendAt": next_send_at,
            },
        }
    )


@app.route("/api/subscription", methods=["GET"])
def api_subscription_get():
    db_path = get_db_path()
    if not db_path.exists():
        return jsonify({"error": f"Datenbank nicht gefunden: {db_path}"}), 404

    email = request.args.get("email", default="", type=str).strip().lower()
    if not is_valid_email(email):
        return jsonify({"error": "Bitte gueltige E-Mail-Adresse angeben."}), 400

    with db_connect(db_path) as connection:
        initialize_user_subscription_table(connection)
        row = connection.execute(
            """
            SELECT email, frequency, max_price_eur, updated_at, next_send_at
            FROM user_subscriptions
            WHERE email = ? AND is_active = 1
            """,
            (email,),
        ).fetchone()

    if row is None:
        return jsonify({"subscription": None})

    return jsonify(
        {
            "subscription": {
                "email": row["email"],
                "frequency": row["frequency"],
                "maxPriceEur": row["max_price_eur"],
                "updatedAt": row["updated_at"],
                "nextSendAt": row["next_send_at"],
            }
        }
    )


@app.route("/api/subscriptions", methods=["GET"])
def api_subscriptions_list():
    db_path = get_db_path()
    if not db_path.exists():
        return jsonify({"error": f"Datenbank nicht gefunden: {db_path}"}), 404

    with db_connect(db_path) as connection:
        initialize_user_subscription_table(connection)
        rows = connection.execute(
            """
            SELECT subscription_id, email, frequency, max_price_eur, updated_at, next_send_at
            FROM user_subscriptions
            WHERE is_active = 1
            ORDER BY updated_at DESC
            """
        ).fetchall()

    return jsonify(
        {
            "subscriptions": [
                {
                    "subscriptionId": row["subscription_id"],
                    "email": row["email"],
                    "frequency": row["frequency"],
                    "maxPriceEur": row["max_price_eur"],
                    "updatedAt": row["updated_at"],
                    "nextSendAt": row["next_send_at"],
                }
                for row in rows
            ]
        }
    )


@app.route("/api/subscription", methods=["DELETE"])
def api_subscription_delete():
    db_path = get_db_path()
    if not db_path.exists():
        return jsonify({"error": f"Datenbank nicht gefunden: {db_path}"}), 404

    email = request.args.get("email", default="", type=str).strip().lower()
    if not is_valid_email(email):
        return jsonify({"error": "Bitte gueltige E-Mail-Adresse angeben."}), 400

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with db_connect(db_path) as connection:
        initialize_user_subscription_table(connection)
        result = connection.execute(
            """
            UPDATE user_subscriptions
            SET is_active = 0,
                updated_at = ?
            WHERE email = ?
              AND is_active = 1
            """,
            (timestamp, email),
        )
        connection.commit()

    if result.rowcount == 0:
        return jsonify({"error": "Kein aktives Abo gefunden."}), 404

    return jsonify({"message": "Abo deaktiviert.", "email": email})


if __name__ == "__main__":
    app.run(debug=True)
