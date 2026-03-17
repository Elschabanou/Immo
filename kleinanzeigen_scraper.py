from __future__ import annotations

import argparse
import html
import hashlib
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.kleinanzeigen.de/s-wohnung-kaufen/stuttgart/preis::180000/c196l9280r50"
BASE_DOMAIN = "https://www.kleinanzeigen.de"

PRICE_PATTERN = re.compile(r"(\d[\d.\s]*)\s*€")
AREA_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*m²", re.IGNORECASE)
ROOMS_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:Zi\.?|Zimmer)", re.IGNORECASE)
DISTANCE_PATTERN = re.compile(r"\(\s*(?:ca\.\s*)?\d+\s*km\s*\)", re.IGNORECASE)
ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")


def build_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url

    parsed = urlparse(base_url)
    parts = [part for part in parsed.path.split("/") if part]
    parts = [part for part in parts if not part.startswith("seite:")]
    if not parts:
        raise ValueError("Basis-URL enthält keinen gültigen Pfad.")

    parts.insert(len(parts) - 1, f"seite:{page}")
    path = "/" + "/".join(parts)
    return urlunparse(parsed._replace(path=path))


def clean_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = html.unescape(value)
    text = ZERO_WIDTH_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def to_float(value: str) -> Optional[float]:
    normalized = value.replace(".", "").replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def extract_price_eur(text: Optional[str]) -> Optional[int]:
    if not text:
        return None

    match = PRICE_PATTERN.search(text)
    if match:
        digits = re.sub(r"\D", "", match.group(1))
        return int(digits) if digits else None

    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def extract_area_sqm(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = AREA_PATTERN.search(text)
    if not match:
        return None
    return to_float(match.group(1))


def extract_rooms(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = ROOMS_PATTERN.search(text)
    if not match:
        return None
    return to_float(match.group(1))


def extract_listing_id(url: Optional[str]) -> Optional[str]:
    if not url:
        return None

    parsed = urlparse(url)
    last_segment = parsed.path.rstrip("/").split("/")[-1]
    if last_segment:
        first_chunk = last_segment.split("-")[0]
        if first_chunk.isdigit():
            return first_chunk

    fallback_match = re.search(r"/(\d{6,})(?:-|/|$)", parsed.path)
    if fallback_match:
        return fallback_match.group(1)
    return None


def parse_listings(html: str, crawl_timestamp: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("#srchrslt-adtable article.aditem, article.aditem[data-adid]")

    seen_ids: set[str] = set()
    records: list[dict[str, Any]] = []

    for card in cards:
        title_link = card.select_one("h2 a.ellipsis, h2 a")
        href = None
        if title_link and title_link.get("href"):
            href = title_link.get("href")
        elif card.get("data-href"):
            href = card.get("data-href")
        else:
            fallback_link = card.select_one("a[href*='/s-anzeige/']")
            href = fallback_link.get("href") if fallback_link else None

        url = urljoin(BASE_DOMAIN, href) if href else None
        listing_id = clean_text(card.get("data-adid")) or extract_listing_id(url)
        if not listing_id and url:
            listing_id = f"urlhash-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"

        if not listing_id or listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        title = clean_text(title_link.get_text(" ", strip=True)) if title_link else None

        price_node = card.select_one(
            "p.aditem-main--middle--price-shipping--price, .aditem-main--middle--price-shipping"
        )
        price_text = clean_text(price_node.get_text(" ", strip=True)) if price_node else None
        price_eur = extract_price_eur(price_text)

        tags_text = " ".join(
            clean_text(node.get_text(" ", strip=True)) or ""
            for node in card.select("p.aditem-main--middle--tags, .aditem-main--middle--attr span, .simpletag")
        ).strip()
        if not tags_text:
            tags_text = clean_text(card.get_text(" ", strip=True)) or ""

        area_sqm = extract_area_sqm(tags_text)
        rooms = extract_rooms(tags_text)

        location_node = card.select_one(".aditem-main--top--left")
        location = clean_text(location_node.get_text(" ", strip=True)) if location_node else None
        if location:
            location = clean_text(DISTANCE_PATTERN.sub("", location))

        description_node = card.select_one("p.aditem-main--middle--description")
        description = clean_text(description_node.get_text(" ", strip=True)) if description_node else None

        records.append(
            {
                "listing_id": listing_id,
                "title": title,
                "price_eur": price_eur,
                "area_sqm": area_sqm,
                "rooms": rooms,
                "location": location,
                "url": url,
                "description": description,
                "created_at": crawl_timestamp,
            }
        )

    return records


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            listing_id TEXT PRIMARY KEY,
            title TEXT,
            price_eur INTEGER,
            area_sqm REAL,
            rooms REAL,
            location TEXT,
            url TEXT,
            description TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price_eur)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_listings_location ON listings(location)")
    connection.commit()


def insert_listing(connection: sqlite3.Connection, listing: dict[str, Any]) -> bool:
    cursor = connection.execute(
        """
        INSERT INTO listings (
            listing_id,
            title,
            price_eur,
            area_sqm,
            rooms,
            location,
            url,
            description,
            created_at
        )
        VALUES (
            :listing_id,
            :title,
            :price_eur,
            :area_sqm,
            :rooms,
            :location,
            :url,
            :description,
            :created_at
        )
        ON CONFLICT(listing_id) DO NOTHING
        """,
        listing,
    )
    return cursor.rowcount == 1


def crawl(base_url: str, database_path: str, max_pages: Optional[int], delay_seconds: float) -> None:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }
    )

    with sqlite3.connect(database_path) as connection:
        initialize_database(connection)

        page = 1
        total_found = 0
        total_new = 0

        while True:
            if max_pages is not None and page > max_pages:
                print(f"Maximale Seitenzahl erreicht: {max_pages}")
                break

            page_url = build_page_url(base_url, page)
            print(f"Rufe Seite {page} ab: {page_url}")

            try:
                response = session.get(page_url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as exc:
                print(f"HTTP-Fehler auf Seite {page}: {exc}")
                break

            crawl_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            listings = parse_listings(response.text, crawl_timestamp)

            if not listings:
                print(f"Seite {page} enthält keine Listings. Crawl wird beendet.")
                break

            page_new = 0
            for listing in listings:
                if insert_listing(connection, listing):
                    page_new += 1

            connection.commit()

            total_found += len(listings)
            total_new += page_new

            print(f"Seite {page}: {len(listings)} Listings gefunden, {page_new} neu gespeichert.")

            if page_new == 0:
                print("Keine neuen Anzeigen auf dieser Seite. Crawl wird beendet.")
                break

            page += 1
            if delay_seconds > 0:
                time.sleep(delay_seconds)

    print(f"Fertig. Insgesamt gefunden: {total_found}, neu gespeichert: {total_new}.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kleinanzeigen-Listings (Wohnung kaufen) crawlen und in SQLite speichern"
    )
    parser.add_argument("--base-url", default=BASE_URL, help="Basis-URL der Suche")
    parser.add_argument("--db", default="kleinanzeigen_listings.db", help="SQLite-Dateipfad")
    parser.add_argument("--max-pages", type=int, default=None, help="Optionale Begrenzung der Seitenzahl")
    parser.add_argument("--delay", type=float, default=1.0, help="Pause zwischen Seitenabrufen in Sekunden")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    crawl(args.base_url, args.db, args.max_pages, args.delay)


if __name__ == "__main__":
    main()