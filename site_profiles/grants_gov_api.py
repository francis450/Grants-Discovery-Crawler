import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import aiohttp

from site_profiles.base_api_profile import BaseAPIProfile
from config import MIN_DEADLINE_DAYS, MIN_RELEVANCE_SCORE
from utils.data_utils import is_complete_grant
from utils.db_utils import load_existing_urls

logger = logging.getLogger("grant_crawler")

class GrantsGovAPIProfile(BaseAPIProfile):
    site_name = "Grants.gov API"
    site_url = "https://www.grants.gov"
    description = "Official US Government Grants API"

    SEARCH_ENDPOINT = "https://api.grants.gov/v1/api/search2"
    FETCH_ENDPOINT = "https://api.grants.gov/v1/api/fetchOpportunity"

    # Eligibility code reference:
    #   12 = Nonprofits 501(c)(3), 13 = Nonprofits non-501(c)(3),
    #   25 = Others (see text), 99 = Unrestricted
    DEFAULT_ELIG = "12|13|25|99"

    # High-priority search queries — broadened to catch more internationally-eligible grants
    SEARCH_QUERIES = [
        # --- Africa / developing-country explicit ---
        {"keyword": "technology education Africa", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "STEM education developing countries digital literacy", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "computer lab school Africa equipment", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "electronic waste recycling circular economy", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "digital divide technology access underserved", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "East Africa education technology infrastructure", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        # --- International development / broader ---
        {"keyword": "international development information technology", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "education technology international nonprofit", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "digital literacy youth international", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "IT equipment refurbishment donation nonprofit", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "renewable energy sustainable technology Africa", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "ICT education capacity building developing", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "e-waste management technology Africa Kenya", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
        {"keyword": "school computer lab infrastructure developing countries", "oppStatuses": "posted|forecasted", "eligibilityCodes": DEFAULT_ELIG},
    ]

    # Filtering Criteria (Strict)
    AFRICAN_KEYWORDS = [
        'africa', 'african', 'kenya', 'kenyan', 'tanzania', 'uganda', 'rwanda',
        'ethiopia', 'ghana', 'nigeria', 'senegal', 'east africa', 'sub-saharan',
        'developing countries', 'developing nations', 'emerging markets',
        'low-income countries', 'middle-income countries', 'lmic',
        'global south', 'international development', 'worldwide',
        'any country', 'all countries', 'multi-country', 'cross-border'
    ]

    # Signal-category approach: a grant must match words in at least 2 of these categories
    # to pass the pre-filter. This is intentionally loose — the LLM does the real scoring.
    # Words are chosen to be SPECIFIC enough to avoid matching generic government grants.
    SIGNAL_CATEGORIES = {
        'education_youth': [
            'education', 'educational', 'school', 'schools',
            'student', 'students', 'youth', 'children', 'child',
            'learning', 'literacy', 'curriculum', 'classroom',
            'teacher', 'teaching', 'k-12', 'k12',
        ],
        'technology_digital': [
            'digital', 'computer', 'computers', 'computing',
            'software', 'hardware', 'cyber', 'ict',
            'e-waste', 'ewaste', 'electronic waste', 'refurbish',
            'internet access', 'broadband', 'connectivity',
            'information technology', 'it infrastructure',
            'digital skills', 'coding', 'programming',
        ],
        'international_dev': [
            'international development', 'international education',
            'international assistance', 'foreign assistance', 'foreign affairs',
            'developing countries', 'developing nations',
            'africa', 'african', 'kenya', 'sub-saharan', 'worldwide',
            'usaid', 'global south', 'low-income countries',
            'emerging market', 'capacity building',
        ],
        'environment_circular': [
            'e-waste', 'electronic waste', 'recycling electronics',
            'circular economy', 'refurbishment', 'repurpose',
            'green technology', 'renewable energy',
        ],
    }

    # High-confidence exact phrases that auto-pass mission filter (any one = pass)
    MISSION_EXACT_PHRASES = [
        'digital literacy', 'computer lab', 'technology education',
        'stem education', 'e-waste', 'electronic waste', 'circular economy',
        'digital divide', 'digital inclusion', 'ict for development', 'ict4d',
        'computer donation', 'equipment donation', 'refurbished computer',
        'school infrastructure', 'education equipment',
    ]

    # Exclusion: only truly off-topic sectors.
    # Removed 'healthcare'/'medical' — digital-health-for-schools grants are valid.
    EXCLUSION_KEYWORDS = [
        'coal mining', 'fossil fuel extraction', 'oil drilling', 'gas pipeline construction', 'petroleum refining',
        'boating safety', 'maritime navigation', 'vessel inspection', 'waterway dredging',
        'hiv/aids treatment', 'drug assistance program', 'substance abuse treatment',
        'housing voucher', 'homelessness shelter',
        'livestock breeding', 'crop insurance',
        'performing arts touring', 'museum conservation',
    ]

    # Agencies that primarily fund domestic or off-mission work.
    # Grants from these agencies are rejected UNLESS there's an explicit
    # international/Africa signal (checked via SIGNAL_CATEGORIES['international_dev']).
    # Agencies NOT listed (DOS, USAID, ED, NSF, NASA, EPA, etc.) pass through
    # to the keyword-based cross-axis filter.
    DOMESTIC_AGENCY_PREFIXES = [
        'HHS',   # Health & Human Services (NIH, HRSA, ACL, CDC, SAMHSA…)
        'DOD',   # Department of Defense (Army, Navy, Air Force, DARPA…)
        'VA',    # Veterans Affairs
        'DOI',   # Interior (conservation, parks, fire, land mgmt)
        'DOL',   # Labor (employment, training, veterans employment)
        'AC',    # AmeriCorps (domestic volunteering)
        'NEA',   # National Endowment for the Arts
        'NEH',   # National Endowment for the Humanities
        'DOJ',   # Justice (law enforcement, corrections)
        'DHS',   # Homeland Security
        'HUD',   # Housing and Urban Development
        'DOT',   # Transportation
        'SSA',   # Social Security Administration
        'SBA',   # Small Business Administration (domestic)
        'USDA',  # Agriculture (FAS intl programs handled by intl override)
    ]

    US_ONLY_STRICT = [
        'united states applicants only',
        'us organizations only',
        'domestic applicants only',
        'usa only',
        'us-based organizations only'
    ]

    MIN_AWARD = 5000
    MAX_AWARD = 10000000  # Federal grants can be very large; LLM scoring handles fit

    async def fetch_grants(self) -> List[Dict[str, Any]]:
        """Orchestrate the API fetch"""
        all_grants = []
        seen_ids = set()
        stats = {"total_hits": 0, "deduped": 0, "fetch_failed": 0, "filtered": 0, "passed": 0}
        
        # Load existing URLs to avoid duplicate fetches
        existing_urls = load_existing_urls()

        async with aiohttp.ClientSession() as session:
            # 1. Search
            logger.info(f"Checking {len(self.SEARCH_QUERIES)} targeted search queries against Grants.gov API...")
            
            for qi, query in enumerate(self.SEARCH_QUERIES, 1):
                try:
                    results = await self._search_api(session, query)
                    logger.info(f"[{qi}/{len(self.SEARCH_QUERIES)}] Query '{query['keyword'][:40]}' → {len(results)} hits")
                    stats["total_hits"] += len(results)
                    
                    for hit in results:
                        opp_id = hit.get('id')
                        opp_num = hit.get('number')
                        
                        if not opp_id or opp_id in seen_ids:
                            stats["deduped"] += 1
                            continue
                        
                        # Use URL for DB deduplication check
                        opp_url = f"https://www.grants.gov/search-results-detail/{opp_num}"
                        if opp_url in existing_urls:
                            logger.debug(f"Skipping duplicate grant: {opp_num}")
                            seen_ids.add(opp_id)
                            stats["deduped"] += 1
                            continue

                        # 2. Fetch Details (with rate-limit delay)
                        await asyncio.sleep(0.3)
                        details = await self._fetch_details(session, opp_id)
                        if not details:
                            logger.debug(f"  Could not fetch details for {opp_num}")
                            stats["fetch_failed"] += 1
                            continue

                        # 3. Apply Filters (with diagnostics)
                        passed, reason = self._passes_filters(details)
                        if not passed:
                            title = details.get('opportunityTitle', opp_num)
                            logger.debug(f"  Filtered out '{title[:60]}': {reason}")
                            seen_ids.add(opp_id)
                            stats["filtered"] += 1
                            continue
                        
                        # 4. Map to Schema
                        grant = self._map_to_schema(details)
                        if grant:
                            all_grants.append(grant)
                            seen_ids.add(opp_id)
                            stats["passed"] += 1
                            logger.info(f"✅ Found relevant API grant: {grant['title']}")
                
                except Exception as e:
                    logger.error(f"Error processing query {query}: {e}")
                    continue

        # Summary
        logger.info(f"{'='*60}")
        logger.info(f"Grants.gov API fetch summary:")
        logger.info(f"  Total search hits:  {stats['total_hits']}")
        logger.info(f"  Deduplicated:       {stats['deduped']}")
        logger.info(f"  Fetch failed:       {stats['fetch_failed']}")
        logger.info(f"  Filtered out:       {stats['filtered']}")
        logger.info(f"  Passed to LLM:      {stats['passed']}")
        logger.info(f"{'='*60}")

        # Expose stats so RunTracker in main.py can read them
        self._last_stats = stats

        return all_grants

    async def _search_api(self, session: aiohttp.ClientSession, query_params: Dict) -> List[Dict]:
        """Call the search endpoint"""
        payload = {
            "keyword": query_params["keyword"],
            "oppStatuses": query_params["oppStatuses"],
            "eligibilityCodes": query_params["eligibilityCodes"],
            "sortBy": "openDate|desc",
            "rows": 50
        }
        
        try:
            async with session.post(self.SEARCH_ENDPOINT, json=payload) as response:
                if response.status != 200:
                    logger.warning(f"Search API returned {response.status}")
                    return []
                
                response_json = await response.json()
                
                # Check for nested 'data' object (standard API v2 format)
                if response_json and 'data' in response_json:
                    search_data = response_json['data']
                    if 'oppHits' in search_data:
                        return search_data['oppHits']
                
                # Fallback for old structure
                if response_json and 'oppHits' in response_json:
                    return response_json['oppHits']

                return []
        except Exception as e:
            logger.error(f"Search API error: {e}")
            return []

    async def _fetch_details(self, session: aiohttp.ClientSession, opp_id: str) -> Optional[Dict]:
        """Fetch full details for an opportunity ID"""
        try:
            async with session.post(self.FETCH_ENDPOINT, json={"opportunityId": opp_id}) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                # Handle potential 'data' wrapper (common in some API responses)
                if 'data' in data and isinstance(data['data'], dict):
                     # Validate it has expected fields before unwrapping
                     if 'opportunityTitle' in data['data'] or 'synopsis' in data['data']:
                          return data['data']
                return data
        except Exception as e:
            logger.error(f"Details API error for {opp_id}: {e}")
            return None

    @staticmethod
    def _extract_text_from_field(field_value) -> str:
        """Extract readable text from an API field that may be a string, list-of-dicts, or list."""
        if isinstance(field_value, str):
            return field_value
        if isinstance(field_value, list):
            parts = []
            for item in field_value:
                if isinstance(item, dict):
                    parts.append(item.get('description', item.get('name', str(item))))
                else:
                    parts.append(str(item))
            return ' '.join(parts)
        return str(field_value) if field_value else ''

    def _passes_filters(self, data: Dict):
        """Apply relevance filtering logic. Returns (passed: bool, reason: str)."""
        synopsis = data.get('synopsis', {}) or {}
        title = data.get('opportunityTitle', '') or synopsis.get('opportunityTitle', '')
        desc = synopsis.get('synopsisDesc', '') or ''
        eligibility_desc = synopsis.get('applicantEligibilityDesc', '') or ''
        categories_text = self._extract_text_from_field(synopsis.get('fundingActivityCategories', ''))
        applicant_text = self._extract_text_from_field(synopsis.get('applicantTypes', ''))
        
        # Build searchable text blob
        searchable_text = f"{title} {desc} {eligibility_desc} {categories_text} {applicant_text}".lower()

        # FILTER 1: EXCLUSION CHECK
        for kw in self.EXCLUSION_KEYWORDS:
            if kw in searchable_text:
                return False, f"exclusion keyword '{kw}'"

        # Pre-compute international signal (used by multiple filters)
        intl_words = self.SIGNAL_CATEGORIES.get('international_dev', [])
        has_intl_signal = any(w in searchable_text for w in intl_words)

        # FILTER 2: AGENCY PREFIX CHECK
        # Most federal agencies fund domestic/off-mission work. Only pass if
        # the grant has an explicit international/Africa signal.
        agency_code = (data.get('agencyCode', '') or '').upper()
        if not agency_code:
            # Try synopsis as fallback
            agency_code = (synopsis.get('agencyCode', '') or '').upper()
        for prefix in self.DOMESTIC_AGENCY_PREFIXES:
            if agency_code.startswith(prefix):
                if not has_intl_signal:
                    return False, f"domestic-focus agency ({agency_code}) without international signal"
                break

        # FILTER 3: SIGNAL-CATEGORY MATCHING (cross-axis)
        # Axis A: WHO/WHERE — education/youth audience OR international development scope
        # Axis B: WHAT — technology/digital OR environment/circular economy sector
        # Must match at least one from each axis, OR match an exact high-confidence phrase.
        axis_a = set()  # audience/geography
        axis_b = set()  # sector/topic
        for cat_name, words in self.SIGNAL_CATEGORIES.items():
            if any(w in searchable_text for w in words):
                if cat_name in ('education_youth', 'international_dev'):
                    axis_a.add(cat_name)
                else:
                    axis_b.add(cat_name)

        # High-confidence exact phrase match — auto-pass
        has_exact_phrase = any(phrase in searchable_text for phrase in self.MISSION_EXACT_PHRASES)

        if has_exact_phrase:
            pass  # Auto-pass mission filter
        elif not axis_a or not axis_b:
            missing = []
            if not axis_a:
                missing.append("no audience/geography signal (education_youth or international_dev)")
            if not axis_b:
                missing.append("no sector signal (technology_digital or environment_circular)")
            return False, "; ".join(missing)

        # FILTER 4: GEOGRAPHIC RELEVANCE
        has_africa = 'international_dev' in axis_a
        is_strict_us = any(phrase in searchable_text for phrase in self.US_ONLY_STRICT)
        
        if is_strict_us and not has_africa:
            return False, "US-only strict, no international/Africa signal"

        # FILTER 5: AWARD AMOUNT (Loose — allow unknown or within range)
        try:
            ceiling = int(float(synopsis.get('awardCeiling', 0) or 0))
            floor = int(float(synopsis.get('awardFloor', 0) or 0))
            if ceiling > 0:
                if ceiling < self.MIN_AWARD:
                    return False, f"award ceiling ${ceiling:,} < min ${self.MIN_AWARD:,}"
                if floor > self.MAX_AWARD:
                    return False, f"award floor ${floor:,} > max ${self.MAX_AWARD:,}"
        except ValueError:
            pass

        # FILTER 6: DEADLINE
        close_date_str = synopsis.get('responseDate', '')
        if close_date_str:
            try:
                deadline = self._parse_api_date(close_date_str)
                if deadline:
                    days_until = (deadline - datetime.now()).days
                    if days_until < 0:
                        return False, f"deadline already passed ({close_date_str})"
                    if days_until < MIN_DEADLINE_DAYS:
                        return False, f"deadline too soon ({days_until} days)"
            except Exception:
                pass

        return True, "passed"

    def _map_to_schema(self, data: Dict) -> Dict:
        """Map API response to Grant schema dict"""
        synopsis = data.get('synopsis', {}) or {}
        # Agency name: try nested agencyDetails first, then synopsis-level
        agency = (
            (data.get('agencyDetails') or {}).get('agencyName', '')
            or (synopsis.get('agencyDetails') or {}).get('agencyName', '')
            or synopsis.get('agencyName', '')
        )
        
        # Format amounts
        try:
            ceiling = int(float(synopsis.get('awardCeiling', 0) or 0))
            floor = int(float(synopsis.get('awardFloor', 0) or 0))
            if ceiling > 0 and floor > 0:
                amount_str = f"${floor:,} - ${ceiling:,}"
            elif ceiling > 0:
                amount_str = f"Up to ${ceiling:,}"
            else:
                amount_str = "See opportunity"
        except (ValueError, TypeError):
            amount_str = "See opportunity"

        # Extract readable category names
        categories_raw = synopsis.get('fundingActivityCategories', [])
        categories_list = []
        if isinstance(categories_raw, list):
            for cat in categories_raw:
                if isinstance(cat, dict):
                    categories_list.append(cat.get('description', cat.get('id', 'General')))
                else:
                    categories_list.append(str(cat))
        elif isinstance(categories_raw, str) and categories_raw:
            categories_list.append(categories_raw)
        if not categories_list:
            categories_list = ['General']

        # Extract readable eligibility text
        elig_desc = synopsis.get('applicantEligibilityDesc', '') or ''
        applicant_types_raw = synopsis.get('applicantTypes', [])
        if not elig_desc and isinstance(applicant_types_raw, list):
            elig_parts = [t.get('description', '') for t in applicant_types_raw if isinstance(t, dict)]
            elig_desc = '; '.join(filter(None, elig_parts))
        elif not elig_desc:
            elig_desc = str(applicant_types_raw) if applicant_types_raw else ''

        grant = {
            "title": data.get('opportunityTitle', '') or synopsis.get('opportunityTitle', 'Unknown Grant'),
            "funding_organization": agency,
            "grant_amount": amount_str,
            "deadline": self._format_date(synopsis.get('responseDate', '')),
            "geographic_focus": "International/Africa" if self._check_international(data) else "Check Eligibility",
            "thematic_areas": categories_list,
            "eligibility_criteria": elig_desc[:2000],
            "description": (synopsis.get('synopsisDesc', '') or '')[:5000],
            "application_url": f"https://www.grants.gov/search-results-detail/{data.get('opportunityNumber')}",
            "date_posted": self._format_date(synopsis.get('postingDate', '')),
            "category": "Government Grant",
            "source_website": "Grants.gov API",
            "is_relevant_preliminary": True  # Already filtered by strict logic
        }
        return grant

    def _check_international(self, data: Dict) -> bool:
        """Helper to check if international scope is detected — searches synopsis text."""
        synopsis = data.get('synopsis', {}) or {}
        desc = (synopsis.get('synopsisDesc', '') or '').lower()
        elig = (synopsis.get('applicantEligibilityDesc', '') or '').lower()
        title = (data.get('opportunityTitle', '') or '').lower()
        text = f"{title} {desc} {elig}"
        return any(k in text for k in self.AFRICAN_KEYWORDS)

    def _parse_api_date(self, date_str: str) -> Optional[datetime]:
        """Parse Grants.gov date — handles multiple formats returned by the API."""
        if not date_str:
            return None

        # Strip timezone suffix (e.g. " EDT", " EST", " PST") — not parsed by strptime
        import re
        cleaned = re.sub(r'\s+[A-Z]{2,4}$', '', date_str.strip())

        formats = [
            "%b %d, %Y %I:%M:%S %p",   # "Apr 03, 2026 12:00:00 AM"
            "%B %d, %Y %I:%M:%S %p",   # "April 03, 2026 12:00:00 AM"
            "%b %d, %Y",               # "Apr 03, 2026"
            "%B %d, %Y",               # "April 03, 2026"
            "%m/%d/%Y",                # "04/03/2026"
            "%m%d%Y",                  # "04032026"
            "%Y-%m-%d",                # "2026-04-03"
            "%Y-%m-%dT%H:%M:%S",       # ISO
        ]
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
        logger.debug(f"Could not parse date: '{date_str}'")
        return None

    def _format_date(self, date_str: str) -> str:
        """Format to 'YYYY-MM-DD' string or return original."""
        dt = self._parse_api_date(date_str)
        if dt:
            return dt.strftime("%Y-%m-%d")
        return date_str or ''
