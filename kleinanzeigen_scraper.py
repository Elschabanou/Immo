from __future__ import annotations

import argparse
import json
import html
import hashlib
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.kleinanzeigen.de/s-wohnung-kaufen/stuttgart/preis::180000/c196l9280r50"
BASE_DOMAIN = "https://www.kleinanzeigen.de"
BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / ".env"
OPENROUTER_BATCH_SIZE = 1

PRICE_PATTERN = re.compile(r"(\d[\d.\s]*)\s*€")
AREA_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*m²", re.IGNORECASE)
ROOMS_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:Zi\.?|Zimmer)", re.IGNORECASE)
DISTANCE_PATTERN = re.compile(r"\(\s*(?:ca\.\s*)?\d+\s*km\s*\)", re.IGNORECASE)
ZERO_WIDTH_PATTERN = re.compile(r"[\u200b\u200c\u200d\ufeff]")
PLZ_PATTERN = re.compile(r"\b(\d{5})\b")

# Heuristische, lokal anpassbare Modellparameter für Stuttgart.
# Diese Werte sind keine amtlichen Mietspiegelwerte, sondern eine technische Näherung.
STUTTGART_PLZ_LAGE = {
    "A": {
        "70173",
        "70174",
        "70176",
        "70178",
        "70180",
        "70182",
        "70184",
        "70186",
        "70190",
        "70191",
        "70192",
        "70193",
        "70195",
        "70197",
        "70199",
    },
    "B": {
        "70372",
        "70374",
        "70376",
        "70378",
        "70435",
        "70437",
        "70439",
        "70469",
        "70499",
        "70563",
        "70565",
        "70567",
        "70569",
    },
    "C": {
        "70327",
        "70329",
        "70457",
        "70465",
        "70471",
        "70597",
        "70619",
        "70629",
    },
}

LAGE_BASE_RENT_PER_SQM = {
    "A": 15.50,
    "B": 13.30,
    "C": 11.80,
    "UNK": 10.80,
}

AREA_ADJUSTMENTS = [
    (0.0, 40.0, 1.00),
    (40.0, 60.0, 0.45),
    (60.0, 90.0, 0.00),
    (90.0, 130.0, -0.60),
    (130.0, 9999.0, -1.10),
]

ROOMS_ADJUSTMENTS = [
    (0.0, 1.5, 0.40),
    (1.5, 2.5, 0.20),
    (2.5, 4.0, 0.00),
    (4.0, 9999.0, -0.30),
]

POSITIVE_KEYWORDS = {
    "erstbezug",
    "neubau",
    "modernisiert",
    "kernsaniert",
    "renoviert",
    "energetisch",
}

NEGATIVE_KEYWORDS = {
    "sanierungsbedürftig",
    "renovierungsbedürftig",
    "renovierungsbeduerftig",
    "saniert werden",
    "renovierungsstau",
}


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def get_openrouter_config() -> Optional[dict[str, str]]:
    api_key = os.getenv("API_KEY", "").strip()
    api_url = os.getenv("OPENROUTER_API_URL", "").strip()
    model_name = os.getenv("MODEL_NAME", "").strip()

    if not api_key or not api_url or not model_name:
        return None

    return {
        "api_key": api_key,
        "api_url": api_url,
        "model_name": model_name,
    }


def clamp_score(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, score)), 2)


def extract_json_block(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    json_start = stripped.find("[")
    if json_start == -1:
        json_start = stripped.find("{")
    json_end = max(stripped.rfind("]"), stripped.rfind("}"))
    if json_start != -1 and json_end != -1 and json_end > json_start:
        return stripped[json_start : json_end + 1]
    return stripped


def load_first_json_value(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    start_index = min(
        [index for index in (stripped.find("{"), stripped.find("[")) if index != -1],
        default=-1,
    )
    if start_index == -1:
        raise ValueError("OpenRouter response does not contain JSON")

    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(stripped[start_index:])
    return parsed


def build_openrouter_messages(listings: list[dict[str, Any]]) -> list[dict[str, str]]:
    prompt_listings = [
        {
            "listing_id": listing["listing_id"],
            "title": listing.get("title"),
            "price_eur": listing.get("price_eur"),
            "area_sqm": listing.get("area_sqm"),
            "rooms": listing.get("rooms"),
            "location": listing.get("location"),
        }
        for listing in listings
    ]

    system_prompt = (
        "Du bewertest Immobilien-Listings. Antworte ausschliesslich als JSON-Objekt mit dem Key results. "
        "results muss ein Array sein. Jedes Element muss listing_id, score und reason enthalten. "
        "score ist eine Zahl von 0 bis 100. Hohe Werte bedeuten bessere Listing-Qualitaet und hoehere Attraktivitaet fuer einen Kaufinteressenten. "
        "Die Antwort darf keinen sonstigen Text enthalten."
    )
    user_prompt = (
        "Bewerte die folgenden Listings fuer eine Kaufentscheidung. Beruecksichtige Preis, Lage, Groesse, "
        "Zimmerzahl, Textsignale und offensichtliche Qualitaet. Gib fuer jedes Listing eine kurze Begruendung.\n\n"
        f"Listings:\n{json.dumps(prompt_listings, ensure_ascii=False, indent=2)}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def extract_openrouter_content(choice: dict[str, Any]) -> str:
    message = choice.get("message") or {}
    content = message.get("content")

    if isinstance(content, str) and content.strip():
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str) and part.strip():
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        if parts:
            return "".join(parts)

    for key in ("reasoning_content", "output_text", "text"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value

    fallback_text = choice.get("text")
    if isinstance(fallback_text, str) and fallback_text.strip():
        return fallback_text

    return ""


def call_openrouter(listings: list[dict[str, Any]], config: dict[str, str]) -> list[dict[str, Any]]:
    payload = {
        "model": config["model_name"],
        "messages": build_openrouter_messages(listings),
        "temperature": 0,
        "max_tokens": 3000,
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Immo Listing Rating",
    }

    response = requests.post(config["api_url"], headers=headers, json=payload, timeout=90)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter response has no choices")

    content = extract_openrouter_content(choices[0])
    if not content:
        raise ValueError(f"OpenRouter response has no content: {json.dumps(choices[0], ensure_ascii=False)[:500]}")

    parsed = load_first_json_value(str(content))
    if isinstance(parsed, dict):
        parsed = parsed.get("results") or parsed.get("ratings") or parsed.get("items") or []
    if not isinstance(parsed, list):
        raise ValueError("OpenRouter response is not a JSON array")

    results_by_id: dict[str, dict[str, Any]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        listing_id = str(item.get("listing_id") or item.get("id") or "").strip()
        if not listing_id:
            continue
        score = clamp_score(item.get("score"))
        if score is None:
            raise ValueError(f"OpenRouter rating for listing {listing_id} has no valid score")
        results_by_id[listing_id] = {
            "score": score,
            "reason": str(item.get("reason") or item.get("justification") or "").strip(),
        }

    ordered_results: list[dict[str, Any]] = []
    for listing in listings:
        listing_id = str(listing["listing_id"])
        result = results_by_id.get(listing_id)
        if result is None:
            raise ValueError(f"Missing OpenRouter rating for listing {listing_id}")
        ordered_results.append({"listing_id": listing_id, **result})

    return ordered_results


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

        # Anzeigen ohne Titel oder Preis werden konsequent verworfen.
        if not title or price_eur is None:
            continue

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
    ensure_listing_columns(connection)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price_eur)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_listings_location ON listings(location)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS crawler_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def ensure_listing_columns(connection: sqlite3.Connection) -> None:
    expected_columns: dict[str, str] = {
        "valuation_model": "TEXT",
        "valuation_run_at": "TEXT",
        "est_cold_rent_sqm": "REAL",
        "est_cold_rent_monthly": "REAL",
        "est_cold_rent_min_monthly": "REAL",
        "est_cold_rent_max_monthly": "REAL",
        "gross_yield_pct": "REAL",
        "price_to_rent_factor": "REAL",
        "valuation_confidence": "REAL",
        "valuation_note": "TEXT",
        "listing_quality_index": "REAL",
        "listing_quality_grade": "TEXT",
        "listing_quality_note": "TEXT",
        "ai_rating_model": "TEXT",
        "ai_rating_run_at": "TEXT",
        "ai_rating_score": "REAL",
        "ai_rating_reason": "TEXT",
        "ai_rating_error": "TEXT",
    }

    existing = {
        row[1]
        for row in connection.execute("PRAGMA table_info(listings)").fetchall()
    }

    for column_name, column_type in expected_columns.items():
        if column_name not in existing:
            connection.execute(f"ALTER TABLE listings ADD COLUMN {column_name} {column_type}")


def get_crawler_state(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM crawler_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return row[0]


def set_crawler_state(connection: sqlite3.Connection, key: str, value: str) -> None:
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO crawler_state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, updated_at),
    )


def extract_plz(location: Optional[str]) -> Optional[str]:
    if not location:
        return None
    match = PLZ_PATTERN.search(location)
    return match.group(1) if match else None


def detect_lageklasse(plz: Optional[str], location: Optional[str]) -> str:
    if plz:
        for lageklasse, plz_set in STUTTGART_PLZ_LAGE.items():
            if plz in plz_set:
                return lageklasse

    text = (location or "").lower()
    if "stuttgart" in text:
        return "B"
    return "UNK"


def range_adjustment(value: Optional[float], ranges: list[tuple[float, float, float]]) -> float:
    if value is None:
        return 0.0
    for min_val, max_val, adjustment in ranges:
        if min_val <= value < max_val:
            return adjustment
    return 0.0


def keyword_adjustment(title: Optional[str], description: Optional[str]) -> float:
    text = f"{title or ''} {description or ''}".lower()
    adjustment = 0.0

    if any(keyword in text for keyword in POSITIVE_KEYWORDS):
        adjustment += 0.70
    if any(keyword in text for keyword in NEGATIVE_KEYWORDS):
        adjustment -= 1.10
    return adjustment


def estimate_cold_rent_sqm(listing: dict[str, Any]) -> tuple[Optional[float], str]:
    area_sqm = listing.get("area_sqm")
    rooms = listing.get("rooms")
    location = listing.get("location")
    title = listing.get("title")
    description = listing.get("description")

    plz = extract_plz(location)
    lageklasse = detect_lageklasse(plz, location)
    base = LAGE_BASE_RENT_PER_SQM[lageklasse]

    est = base
    est += range_adjustment(area_sqm, AREA_ADJUSTMENTS)
    est += range_adjustment(rooms, ROOMS_ADJUSTMENTS)
    est += keyword_adjustment(title, description)

    est = max(6.50, min(22.00, est))
    note = f"lage={lageklasse};plz={plz or 'unknown'}"
    return round(est, 2), note


def valuation_confidence(listing: dict[str, Any], lageklasse: str) -> float:
    score = 0.30
    if listing.get("area_sqm"):
        score += 0.30
    if listing.get("rooms"):
        score += 0.15
    if lageklasse != "UNK":
        score += 0.20
    if listing.get("description"):
        score += 0.05
    return round(min(1.0, score), 2)


def quality_grade(index_value: float) -> str:
    if index_value >= 85:
        return "A"
    if index_value >= 70:
        return "B"
    if index_value >= 55:
        return "C"
    if index_value >= 40:
        return "D"
    return "E"


def compute_listing_quality_index(
    listing: dict[str, Any],
    est_cold_rent_monthly: Optional[float],
    gross_yield_pct: Optional[float],
    price_to_rent_factor: Optional[float],
    confidence: float,
) -> tuple[float, str, str]:
    score = 0.0

    completeness_fields = [
        "title",
        "price_eur",
        "area_sqm",
        "rooms",
        "location",
        "description",
    ]
    completeness_ratio = sum(1 for field in completeness_fields if listing.get(field) not in (None, "")) / len(
        completeness_fields
    )
    score += completeness_ratio * 25.0

    score += max(0.0, min(1.0, confidence)) * 10.0

    area_sqm = listing.get("area_sqm")
    if area_sqm is not None:
        if 20 <= area_sqm <= 180:
            score += 8.0
        elif 12 <= area_sqm <= 250:
            score += 4.0
        else:
            score += 1.0
    else:
        score -= 8.0

    rooms = listing.get("rooms")
    if rooms is None:
        score -= 4.0
    elif 1 <= rooms <= 5:
        score += 3.0

    if gross_yield_pct is None:
        score += 3.0
    elif gross_yield_pct < 2.0:
        score += 5.0
    elif gross_yield_pct < 3.5:
        score += 10.0
    elif gross_yield_pct < 5.0:
        score += 18.0
    elif gross_yield_pct < 7.0:
        score += 28.0
    elif gross_yield_pct <= 12.0:
        score += 35.0
    else:
        score += 20.0

    if price_to_rent_factor is None:
        score += 2.0
    elif price_to_rent_factor <= 18:
        score += 20.0
    elif price_to_rent_factor <= 22:
        score += 16.0
    elif price_to_rent_factor <= 26:
        score += 12.0
    elif price_to_rent_factor <= 32:
        score += 8.0
    else:
        score += 4.0

    price_eur = listing.get("price_eur")
    if price_eur and area_sqm and area_sqm > 0:
        price_per_sqm = price_eur / area_sqm
        if price_per_sqm < 1000 or price_per_sqm > 9000:
            score -= 10.0

    text = f"{listing.get('title') or ''} {listing.get('description') or ''}".lower()
    if any(keyword in text for keyword in NEGATIVE_KEYWORDS):
        score -= 8.0
    if any(keyword in text for keyword in POSITIVE_KEYWORDS):
        score += 2.0

    if est_cold_rent_monthly is None:
        score -= 5.0

    index_value = round(max(0.0, min(100.0, score)), 2)
    grade = quality_grade(index_value)
    note = (
        f"completeness={round(completeness_ratio, 2)};"
        f"confidence={confidence};"
        f"yield={round(gross_yield_pct, 2) if gross_yield_pct is not None else 'na'};"
        f"factor={round(price_to_rent_factor, 2) if price_to_rent_factor is not None else 'na'}"
    )
    return index_value, grade, note


def apply_mietspiegel_valuation(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        """
        SELECT
            listing_id,
            title,
            price_eur,
            area_sqm,
            rooms,
            location,
            description
        FROM listings
        """
    ).fetchall()

    updated = 0
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for row in rows:
        listing = {
            "listing_id": row[0],
            "title": row[1],
            "price_eur": row[2],
            "area_sqm": row[3],
            "rooms": row[4],
            "location": row[5],
            "description": row[6],
        }

        area_sqm = listing["area_sqm"]
        price_eur = listing["price_eur"]
        location = listing["location"]

        if not area_sqm or area_sqm <= 0:
            quality_index, quality_grade_value, quality_note = compute_listing_quality_index(
                listing,
                None,
                None,
                None,
                0.10,
            )
            connection.execute(
                """
                UPDATE listings
                SET
                    valuation_model = ?,
                    valuation_run_at = ?,
                    est_cold_rent_sqm = NULL,
                    est_cold_rent_monthly = NULL,
                    est_cold_rent_min_monthly = NULL,
                    est_cold_rent_max_monthly = NULL,
                    gross_yield_pct = NULL,
                    price_to_rent_factor = NULL,
                    valuation_confidence = 0.10,
                    valuation_note = ?,
                    listing_quality_index = ?,
                    listing_quality_grade = ?,
                    listing_quality_note = ?
                WHERE listing_id = ?
                """,
                (
                    "stuttgart_mietspiegel_heuristic_v1",
                    run_at,
                    "no_area",
                    quality_index,
                    quality_grade_value,
                    quality_note,
                    listing["listing_id"],
                ),
            )
            updated += 1
            continue

        rent_sqm, note = estimate_cold_rent_sqm(listing)
        lageklasse = detect_lageklasse(extract_plz(location), location)

        monthly = rent_sqm * area_sqm
        min_monthly = monthly * 0.85
        max_monthly = monthly * 1.15

        gross_yield_pct = None
        price_to_rent_factor = None
        if price_eur and price_eur > 0:
            annual = monthly * 12.0
            gross_yield_pct = (annual / price_eur) * 100.0
            if annual > 0:
                price_to_rent_factor = price_eur / annual

        confidence = valuation_confidence(listing, lageklasse)
        quality_index, quality_grade_value, quality_note = compute_listing_quality_index(
            listing,
            monthly,
            gross_yield_pct,
            price_to_rent_factor,
            confidence,
        )

        connection.execute(
            """
            UPDATE listings
            SET
                valuation_model = ?,
                valuation_run_at = ?,
                est_cold_rent_sqm = ?,
                est_cold_rent_monthly = ?,
                est_cold_rent_min_monthly = ?,
                est_cold_rent_max_monthly = ?,
                gross_yield_pct = ?,
                price_to_rent_factor = ?,
                valuation_confidence = ?,
                valuation_note = ?,
                listing_quality_index = ?,
                listing_quality_grade = ?,
                listing_quality_note = ?
            WHERE listing_id = ?
            """,
            (
                "stuttgart_mietspiegel_heuristic_v1",
                run_at,
                round(rent_sqm, 2),
                round(monthly, 2),
                round(min_monthly, 2),
                round(max_monthly, 2),
                round(gross_yield_pct, 2) if gross_yield_pct is not None else None,
                round(price_to_rent_factor, 2) if price_to_rent_factor is not None else None,
                confidence,
                note,
                quality_index,
                quality_grade_value,
                quality_note,
                listing["listing_id"],
            ),
        )
        updated += 1

    connection.commit()
    return updated


def apply_openrouter_valuation(connection: sqlite3.Connection) -> int:
    config = get_openrouter_config()
    if config is None:
        print("OpenRouter-Konfiguration unvollständig, AI-Bewertung wird übersprungen.")
        return 0

    updated = 0
    while True:
        rows = connection.execute(
            """
            SELECT
                listing_id,
                title,
                price_eur,
                area_sqm,
                rooms,
                location,
                url,
                description,
                listing_quality_index,
                listing_quality_grade
            FROM listings
            WHERE ai_rating_run_at IS NULL
            ORDER BY created_at DESC, listing_id DESC
            LIMIT ?
            """,
            (OPENROUTER_BATCH_SIZE,),
        ).fetchall()

        if not rows:
            break

        listings = [
            {
                "listing_id": row[0],
                "title": row[1],
                "price_eur": row[2],
                "area_sqm": row[3],
                "rooms": row[4],
                "location": row[5],
                "url": row[6],
                "description": row[7],
                "listing_quality_index": row[8],
                "listing_quality_grade": row[9],
            }
            for row in rows
        ]

        try:
            ratings = call_openrouter(listings, config)
        except Exception as exc:
            error_message = str(exc)
            print(f"OpenRouter-Bewertung fehlgeschlagen: {error_message}")
            connection.execute(
                """
                UPDATE listings
                SET ai_rating_error = ?
                WHERE listing_id = ?
                """,
                (error_message[:500], listings[0]["listing_id"]),
            )
            connection.commit()
            break

        run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for rating in ratings:
            connection.execute(
                """
                UPDATE listings
                SET ai_rating_model = ?,
                    ai_rating_run_at = ?,
                    ai_rating_score = ?,
                    ai_rating_reason = ?,
                    ai_rating_error = NULL
                WHERE listing_id = ?
                """,
                (
                    config["model_name"],
                    run_at,
                    rating["score"],
                    rating["reason"],
                    rating["listing_id"],
                ),
            )
            updated += 1

        connection.commit()

    return updated


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


def purge_invalid_listings(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        """
        DELETE FROM listings
        WHERE title IS NULL
           OR TRIM(title) = ''
           OR price_eur IS NULL
        """
    )
    return cursor.rowcount


def crawl(base_url: str, database_path: str, max_pages: Optional[int], delay_seconds: float) -> None:
    load_dotenv_file(DOTENV_PATH)

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
        previous_marker = get_crawler_state(connection, "last_seen_listing_id")
        if previous_marker:
            print(f"Inkrementeller Crawl aktiv, bekannter Marker: {previous_marker}")
        else:
            print("Kein Marker vorhanden, starte vollständigen Initial-Crawl.")

        page = 1
        total_found = 0
        total_new = 0
        marker_for_next_run: Optional[str] = None
        marker_reached = False

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

            if page == 1 and listings:
                marker_for_next_run = listings[0]["listing_id"]

            page_new = 0
            for listing in listings:
                if previous_marker and listing["listing_id"] == previous_marker:
                    marker_reached = True
                    print(
                        f"Bekannten Marker auf Seite {page} erreicht ({previous_marker}). "
                        "Ältere Seiten werden nicht erneut gecrawlt."
                    )
                    break

                if insert_listing(connection, listing):
                    page_new += 1

            connection.commit()

            total_found += len(listings)
            total_new += page_new

            print(f"Seite {page}: {len(listings)} Listings gefunden, {page_new} neu gespeichert.")

            if marker_reached:
                break

            if page_new == 0:
                print("Keine neuen Anzeigen auf dieser Seite. Crawl wird beendet.")
                break

            page += 1
            if delay_seconds > 0:
                time.sleep(delay_seconds)

        if marker_for_next_run:
            set_crawler_state(connection, "last_seen_listing_id", marker_for_next_run)
            connection.commit()

        removed_invalid = purge_invalid_listings(connection)
        if removed_invalid > 0:
            connection.commit()
            print(f"Ungültige Anzeigen gelöscht (fehlender Titel/Preis): {removed_invalid}")

        valued_rows = apply_mietspiegel_valuation(connection)
        print(f"Mietspiegel-Bewertung aktualisiert für {valued_rows} Anzeigen.")

        ai_valued_rows = apply_openrouter_valuation(connection)
        print(f"OpenRouter-Bewertung aktualisiert für {ai_valued_rows} Anzeigen.")

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