from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional dependency in local sqlite mode
    psycopg = None
    dict_row = None


class DatabaseConfigurationError(RuntimeError):
    pass


BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue

            os.environ[key] = value.strip().strip('"').strip("'")


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    for candidate in (BASE_DIR / ".env", BASE_DIR / ".env.production"):
        load_env_file(candidate)
        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url:
            return database_url

    return ""


def db_connect(default_sqlite_path: Path, sqlite_override: str | None = None):
    database_url = get_database_url()
    if database_url:
        if psycopg is None:
            raise DatabaseConfigurationError(
                "DATABASE_URL ist gesetzt, aber psycopg ist nicht installiert. Bitte requirements installieren."
            )
        return psycopg.connect(database_url, row_factory=dict_row)

    configured_path = sqlite_override or os.getenv("DB_PATH", str(default_sqlite_path))
    sqlite_path = Path(configured_path).expanduser()
    connection = sqlite3.connect(str(sqlite_path))
    connection.row_factory = sqlite3.Row
    return connection


def is_sqlite_connection(connection: Any) -> bool:
    return isinstance(connection, sqlite3.Connection)


def db_execute(connection: Any, query: str, params: tuple[Any, ...] | list[Any] = ()):
    if is_sqlite_connection(connection):
        query = query.replace("%s", "?")
    return connection.execute(query, params)


def fetch_value(row: Any, key: str, index: int = 0):
    if row is None:
        return None

    if isinstance(row, dict):
        return row.get(key)

    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def listings_table_exists(connection: Any) -> bool:
    if is_sqlite_connection(connection):
        row = db_execute(
            connection,
            "SELECT name FROM sqlite_master WHERE type='table' AND name='listings'",
        ).fetchone()
    else:
        row = db_execute(
            connection,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'listings'
            """,
        ).fetchone()

    return row is not None
