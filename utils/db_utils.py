"""
Database utilities for persistent grant storage and cross-run deduplication.
Uses SQLite (built-in, no external dependencies).
"""

import json
import sqlite3
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set

from config import DB_PATH, DEDUP_SIMILARITY_THRESHOLD


def init_db(db_path: str = DB_PATH) -> None:
    """
    Initialize the SQLite database and create the grants table if it doesn't exist.

    Args:
        db_path: Path to the SQLite database file.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            funding_organization TEXT,
            grant_amount TEXT,
            deadline TEXT,
            geographic_focus TEXT,
            thematic_areas TEXT,
            eligibility_criteria TEXT,
            description TEXT,
            application_url TEXT,
            date_posted TEXT,
            category TEXT,
            source_website TEXT,
            relevance_score INTEGER,
            relevance_reasoning TEXT,
            how_it_helps TEXT,
            matching_themes TEXT,
            is_relevant_preliminary INTEGER,
            run_id TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # Index for fast deduplication lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_grants_title ON grants(title)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_grants_application_url ON grants(application_url)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_grants_run_id ON grants(run_id)
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")


def _serialize_list(value) -> Optional[str]:
    """Convert a list to a JSON string for storage, or return the value as-is."""
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def _deserialize_list(value: Optional[str]) -> Optional[list]:
    """Convert a JSON string back to a list, or return None."""
    if value is None:
        return None
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def load_existing_titles(db_path: str = DB_PATH) -> Set[str]:
    """
    Load all existing grant titles from the database for in-memory dedup.

    Returns:
        Set of grant titles already in the database.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM grants WHERE title IS NOT NULL")
    titles = {row[0] for row in cursor.fetchall()}
    conn.close()
    return titles


def load_existing_urls(db_path: str = DB_PATH) -> Set[str]:
    """
    Load all existing application URLs from the database.

    Returns:
        Set of application URLs already in the database.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT application_url FROM grants WHERE application_url IS NOT NULL")
    urls = {row[0] for row in cursor.fetchall()}
    conn.close()
    return urls


def grant_exists(
    title: Optional[str],
    application_url: Optional[str],
    existing_titles: Set[str],
    existing_urls: Set[str],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
) -> bool:
    """
    Check if a grant already exists using fuzzy title matching + exact URL matching.

    Args:
        title: Grant title to check.
        application_url: Grant URL to check.
        existing_titles: Set of known titles from the database.
        existing_urls: Set of known URLs from the database.
        threshold: Minimum similarity ratio for fuzzy title matching.

    Returns:
        True if the grant is considered a duplicate.
    """
    # Exact URL match — same URL = same grant regardless of title
    if application_url and application_url in existing_urls:
        return True

    # Fuzzy title match
    if title:
        title_lower = title.lower().strip()
        for existing_title in existing_titles:
            existing_lower = existing_title.lower().strip()
            # Exact match (fast path)
            if title_lower == existing_lower:
                return True
            # Fuzzy match
            ratio = SequenceMatcher(None, title_lower, existing_lower).ratio()
            if ratio >= threshold:
                return True

    return False


def insert_grant(grant: dict, run_id: str, db_path: str = DB_PATH) -> bool:
    """
    Insert a grant into the database.

    Args:
        grant: Grant dictionary with field values.
        run_id: Identifier for the current crawl run.
        db_path: Path to the SQLite database file.

    Returns:
        True if the grant was inserted, False if it failed.
    """
    now = datetime.now().isoformat()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO grants (
                title, funding_organization, grant_amount, deadline,
                geographic_focus, thematic_areas, eligibility_criteria,
                description, application_url, date_posted, category,
                source_website, relevance_score, relevance_reasoning,
                how_it_helps, matching_themes, is_relevant_preliminary,
                run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            grant.get("title"),
            grant.get("funding_organization"),
            grant.get("grant_amount"),
            grant.get("deadline"),
            grant.get("geographic_focus"),
            _serialize_list(grant.get("thematic_areas")),
            grant.get("eligibility_criteria"),
            grant.get("description"),
            grant.get("application_url"),
            grant.get("date_posted"),
            grant.get("category"),
            grant.get("source_website"),
            grant.get("relevance_score"),
            grant.get("relevance_reasoning"),
            grant.get("how_it_helps"),
            _serialize_list(grant.get("matching_themes")),
            1 if grant.get("is_relevant_preliminary") else 0,
            run_id,
            now,
            now,
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"  ⚠ Error inserting grant into database: {e}")
        return False
    finally:
        conn.close()


def get_all_grants(db_path: str = DB_PATH) -> List[Dict]:
    """
    Retrieve all grants from the database.

    Returns:
        List of grant dictionaries.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM grants ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()

    grants = []
    for row in rows:
        grant = dict(row)
        # Deserialize list fields
        grant["thematic_areas"] = _deserialize_list(grant.get("thematic_areas"))
        grant["matching_themes"] = _deserialize_list(grant.get("matching_themes"))
        grant["is_relevant_preliminary"] = bool(grant.get("is_relevant_preliminary"))
        grants.append(grant)

    return grants


def get_grants_by_run(run_id: str, db_path: str = DB_PATH) -> List[Dict]:
    """
    Retrieve grants from a specific crawl run.

    Args:
        run_id: The run identifier to filter by.

    Returns:
        List of grant dictionaries from that run.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM grants WHERE run_id = ? ORDER BY created_at DESC",
        (run_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    grants = []
    for row in rows:
        grant = dict(row)
        grant["thematic_areas"] = _deserialize_list(grant.get("thematic_areas"))
        grant["matching_themes"] = _deserialize_list(grant.get("matching_themes"))
        grant["is_relevant_preliminary"] = bool(grant.get("is_relevant_preliminary"))
        grants.append(grant)

    return grants


def get_grant_count(db_path: str = DB_PATH) -> int:
    """Return the total number of grants in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM grants")
    count = cursor.fetchone()[0]
    conn.close()
    return count
