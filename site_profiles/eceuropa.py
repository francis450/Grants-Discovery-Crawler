"""
EC Europa Funding & Tenders Portal — API-based site profile.

Uses the public SEDIA Search API that powers
https://ec.europa.eu/info/funding-tenders/opportunities/portal/
No browser or Playwright needed — structured JSON over REST.

Endpoint (POST):
    https://api.tech.ec.europa.eu/search-api/prod/rest/search
    ?apiKey=SEDIA&text=<keywords>&pageSize=<n>&pageNumber=<p>

Body (filter for Open + Forthcoming calls):
    {"bool": {"must": [{"terms": {"sortStatus": ["31094502","31094501"]}}]}}

Each result carries rich metadata:
    metadata.title, metadata.deadlineDate, metadata.identifier,
    metadata.frameworkProgramme, metadata.typesOfAction,
    metadata.keywords, metadata.descriptionByte, metadata.budgetOverview,
    metadata.crossCuttingPriorities, metadata.callIdentifier, metadata.callTitle
"""

import re
import html
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

import aiohttp

from site_profiles.base_api_profile import BaseAPIProfile
from config import MIN_DEADLINE_DAYS, MAX_PAGES
from utils.db_utils import load_existing_urls

logger = logging.getLogger("grant_crawler")


class ECEuropaProfile(BaseAPIProfile):
    site_name = "EC Europa Funding & Tenders"
    site_url = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
    description = "EU Funding & Tenders Portal — public SEDIA Search API"

    # ── API configuration ────────────────────────────────────────────────
    API_BASE = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
    API_KEY = "SEDIA"
    PAGE_SIZE = 50  # max supported by the API

    # Status codes used in the sortStatus facet
    STATUS_OPEN = "31094502"
    STATUS_FORTHCOMING = "31094501"

    # POST body filters: only Open + Forthcoming calls
    QUERY_BODY: Dict[str, Any] = {
        "bool": {
            "must": [
                {"terms": {"sortStatus": [STATUS_OPEN, STATUS_FORTHCOMING]}}
            ]
        }
    }

    # ── Search queries ───────────────────────────────────────────────────
    # Each keyword string is sent as a separate paginated search.
    # Queries are mission-aligned: IT refurbishment, education, digital
    # inclusion, capacity building for Africa / developing countries.
    SEARCH_QUERIES: List[str] = [
        # Direct mission matches
        "education digital Africa",
        "ICT capacity building developing countries",
        "digital literacy schools Africa",
        "technology education youth developing",
        "STEM education infrastructure developing countries",
        # Equipment / circular economy
        "IT equipment refurbishment circular economy",
        "electronic waste recycling developing countries",
        "digital infrastructure schools",
        # Broader international development
        "digital inclusion underserved communities",
        "education technology international cooperation",
        "digital skills training youth Africa",
        "connectivity schools developing countries",
        "NGO capacity building digital",
    ]

    # Maximum pages to crawl per keyword query
    MAX_PAGES_PER_QUERY = 5  # 5 pages × 50 results = 250 per query max

    # ── Pre-filter keywords ──────────────────────────────────────────────
    # A grant must contain at least one AUDIENCE keyword and one SECTOR keyword
    # to pass the lightweight pre-filter (LLM does the real scoring later).
    AUDIENCE_KEYWORDS = [
        "education", "school", "schools", "youth", "children", "students",
        "teacher", "learning", "literacy", "training", "capacity building",
        "developing countries", "developing nations", "africa", "african",
        "sub-saharan", "low-income", "lmic", "global south",
        "international cooperation", "international development",
    ]

    SECTOR_KEYWORDS = [
        "digital", "ict", "technology", "computer", "internet",
        "e-waste", "ewaste", "electronic waste", "refurbish", "circular economy",
        "stem", "infrastructure", "connectivity", "broadband",
        "software", "hardware", "equipment", "recycling",
        "innovation", "smart", "data",
    ]

    # High-confidence phrases that auto-pass the pre-filter
    AUTO_PASS_PHRASES = [
        "digital literacy", "digital inclusion", "digital divide",
        "ict for development", "ict4d", "e-waste", "electronic waste",
        "circular economy", "computer lab", "stem education",
        "technology education", "digital skills", "capacity building",
        "it infrastructure", "school connectivity", "education technology",
    ]

    # ── Public interface ─────────────────────────────────────────────────
    async def fetch_grants(self) -> List[Dict[str, Any]]:
        """Run all search queries, deduplicate, pre-filter, and return grant dicts."""
        all_grants: List[Dict[str, Any]] = []
        seen_ids: set = set()
        existing_urls = load_existing_urls()

        stats = {
            "total_hits": 0,
            "deduped": 0,
            "filtered_prefilter": 0,
            "filtered_deadline": 0,
            "passed": 0,
        }

        async with aiohttp.ClientSession() as session:
            for qi, keyword in enumerate(self.SEARCH_QUERIES, 1):
                logger.info(
                    f"[{qi}/{len(self.SEARCH_QUERIES)}] Searching EU portal: "
                    f"'{keyword}' ..."
                )
                try:
                    grants_from_query = await self._search_paginated(
                        session, keyword, seen_ids, existing_urls, stats
                    )
                    all_grants.extend(grants_from_query)
                except Exception as exc:
                    logger.error(f"Error on query '{keyword}': {exc}")
                    continue

        # Summary
        logger.info(f"{'=' * 60}")
        logger.info("EC Europa API fetch summary:")
        logger.info(f"  Total search hits:     {stats['total_hits']}")
        logger.info(f"  Deduplicated:          {stats['deduped']}")
        logger.info(f"  Pre-filter removed:    {stats['filtered_prefilter']}")
        logger.info(f"  Deadline removed:      {stats['filtered_deadline']}")
        logger.info(f"  Passed to LLM scoring: {stats['passed']}")
        logger.info(f"{'=' * 60}")

        # Expose stats so RunTracker in main.py can read them
        self._last_stats = stats

        return all_grants

    # ── Private helpers ──────────────────────────────────────────────────
    async def _search_paginated(
        self,
        session: aiohttp.ClientSession,
        keyword: str,
        seen_ids: set,
        existing_urls: set,
        stats: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        """Fetch pages for one keyword query until results are exhausted."""
        grants: List[Dict[str, Any]] = []

        for page in range(1, self.MAX_PAGES_PER_QUERY + 1):
            url = (
                f"{self.API_BASE}"
                f"?apiKey={self.API_KEY}"
                f"&text={keyword.replace(' ', '+')}"
                f"&pageSize={self.PAGE_SIZE}"
                f"&pageNumber={page}"
            )

            try:
                async with session.post(
                    url,
                    json=self.QUERY_BODY,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            f"EU API returned {resp.status} for '{keyword}' page {page}"
                        )
                        break
                    data = await resp.json()
            except Exception as exc:
                logger.error(f"EU API request failed: {exc}")
                break

            results = data.get("results", [])
            total = data.get("totalResults", 0)

            if page == 1:
                logger.info(f"  → {total} total results for '{keyword}'")

            if not results:
                break

            stats["total_hits"] += len(results)

            for item in results:
                grant = self._process_result(item, seen_ids, existing_urls, stats)
                if grant:
                    grants.append(grant)

            # Stop if we've fetched all results
            if page * self.PAGE_SIZE >= total:
                break

            # Small delay between pages to be polite
            await asyncio.sleep(0.2)

        return grants

    def _process_result(
        self,
        item: Dict[str, Any],
        seen_ids: set,
        existing_urls: set,
        stats: Dict[str, int],
    ) -> Optional[Dict[str, Any]]:
        """Validate, deduplicate, pre-filter, and map a single API result."""
        meta = item.get("metadata", {})

        # Unique identifier
        identifier = self._first(meta.get("identifier"))
        if not identifier:
            identifier = item.get("reference", "")
        if not identifier:
            return None

        if identifier in seen_ids:
            stats["deduped"] += 1
            return None

        # Build application URL
        app_url = item.get("url") or (
            f"https://ec.europa.eu/info/funding-tenders/opportunities/"
            f"portal/screen/opportunities/topic-details/{identifier}"
        )

        if app_url in existing_urls:
            seen_ids.add(identifier)
            stats["deduped"] += 1
            return None

        # Extract fields
        title = self._first(meta.get("title")) or item.get("title") or ""
        description_html = self._first(meta.get("descriptionByte")) or item.get("summary") or ""
        description = self._strip_html(description_html)[:5000]
        deadline_raw = self._first(meta.get("deadlineDate")) or ""
        programme = self._first(meta.get("frameworkProgramme")) or ""
        type_of_action = self._first(meta.get("typesOfAction")) or ""
        budget = self._first(meta.get("budgetOverview")) or ""
        call_title = self._first(meta.get("callTitle")) or ""
        call_id = self._first(meta.get("callIdentifier")) or ""
        keywords_list = meta.get("keywords") or []
        priorities = meta.get("crossCuttingPriorities") or []
        status_list = meta.get("status") or []

        if not title:
            seen_ids.add(identifier)
            return None

        # ── Deadline filter ──────────────────────────────────────────
        deadline_str = self._parse_deadline(deadline_raw)
        if deadline_str:
            try:
                dt = datetime.strptime(deadline_str, "%Y-%m-%d")
                days_left = (dt - datetime.now()).days
                if days_left < 0:
                    seen_ids.add(identifier)
                    stats["filtered_deadline"] += 1
                    return None
                if days_left < MIN_DEADLINE_DAYS:
                    seen_ids.add(identifier)
                    stats["filtered_deadline"] += 1
                    return None
            except ValueError:
                pass  # Keep grants with unparseable deadlines

        # ── Lightweight pre-filter ───────────────────────────────────
        searchable = f"{title} {description} {call_title} {' '.join(keywords_list)} {' '.join(priorities)} {type_of_action}".lower()

        if not self._passes_prefilter(searchable):
            seen_ids.add(identifier)
            stats["filtered_prefilter"] += 1
            return None

        # ── Map to grant schema ──────────────────────────────────────
        # Build thematic areas from keywords + cross-cutting priorities
        thematic = []
        if keywords_list:
            thematic.extend(keywords_list[:10])
        if priorities:
            thematic.extend(priorities[:5])
        if type_of_action:
            thematic.append(type_of_action)

        # Build eligibility string from available metadata
        eligibility_parts = []
        if programme:
            eligibility_parts.append(f"Programme: {programme}")
        if call_id:
            eligibility_parts.append(f"Call: {call_id}")
        if status_list:
            status_str = ", ".join(status_list) if isinstance(status_list, list) else str(status_list)
            eligibility_parts.append(f"Status: {status_str}")

        # Clean budget HTML if present
        budget_clean = self._strip_html(budget) if budget else "See opportunity"

        grant: Dict[str, Any] = {
            "title": title,
            "funding_organization": programme or "European Commission",
            "grant_amount": budget_clean[:500] if budget_clean else "See opportunity",
            "deadline": deadline_str or "",
            "geographic_focus": "EU / International",
            "thematic_areas": thematic if thematic else ["EU Funding"],
            "eligibility_criteria": " | ".join(eligibility_parts) if eligibility_parts else "",
            "description": description or call_title or "",
            "application_url": app_url,
            "date_posted": "",
            "category": "EU Grant",
            "source_website": "EC Europa Funding & Tenders",
            "is_relevant_preliminary": True,
        }

        seen_ids.add(identifier)
        stats["passed"] += 1
        logger.info(f"  ✅ Pre-filter pass: {title[:80]}")
        return grant

    def _passes_prefilter(self, text: str) -> bool:
        """
        Lightweight keyword pre-filter.
        Pass if:
          1. Any auto-pass phrase is present, OR
          2. At least one AUDIENCE keyword AND one SECTOR keyword match.
        """
        # Auto-pass on high-confidence phrases
        for phrase in self.AUTO_PASS_PHRASES:
            if phrase in text:
                return True

        has_audience = any(kw in text for kw in self.AUDIENCE_KEYWORDS)
        has_sector = any(kw in text for kw in self.SECTOR_KEYWORDS)
        return has_audience and has_sector

    # ── Utility methods ──────────────────────────────────────────────────
    @staticmethod
    def _first(value) -> str:
        """Extract the first element from a metadata array, or return the string as-is."""
        if isinstance(value, list):
            return value[0] if value else ""
        if isinstance(value, str):
            return value
        return str(value) if value is not None else ""

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags and decode entities."""
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _parse_deadline(self, raw: str) -> str:
        """Parse EU API deadline into YYYY-MM-DD."""
        if not raw:
            return ""
        # ISO format: 2026-04-08T00:00:00.000+0000
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d %B %Y",
            "%d %b %Y",
        ):
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # Fallback: extract date portion if it looks like ISO
        m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
        if m:
            return m.group(1)
        return raw
