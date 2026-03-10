"""
Site profile for DevelopmentAid (developmentaid.org) — Playwright version.

DevelopmentAid is an Angular SPA that lists grants in ``da-search-card``
components.  Each card shows the grant title (linked to a detail page),
funding organisation, location, applicant type, deadline, budget, and status.

Because the data is already structured inside the cards, this profile parses
them directly (no LLM extraction needed for the listing page).  Relevance
scoring (Stage 2) still runs on each grant.

Pagination is URL-based via the ``pageNr`` query parameter.

Search strategy — multiple focused queries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Instead of one broad "Education + Africa" search (2,800+ results), we run
several targeted searches that combine sector filters with keyword searches
to surface grants most relevant to our mission (IT equipment refurbishment
for African schools).  Grants are deduplicated across searches by title.

Filter reference (URL params):
    locations=3         → Africa
    sectors=5           → Education, Training & Capacity Building
    sectors=13          → ICT & Telecommunications
    applicantTypes=1    → NGOs / Nonprofit Organisations
    sort=relevance.desc → Sort by relevance when using keywords
    searchedText=...    → Full-text keyword search
"""

from typing import List, Optional, Set, Tuple

from playwright.async_api import BrowserContext, Page

from config import (
    MAX_PAGES,
    MIN_RELEVANCE_SCORE,
    PLAYWRIGHT_DEFAULT_TIMEOUT,
)
from utils.data_utils import is_complete_grant, is_duplicate_grant
from utils.logging_utils import logger, MetricsLogger
from utils.playwright_utils import new_stealth_page
from utils.scraper_utils import is_deadline_valid

from .base_playwright_profile import BasePlaywrightProfile

metrics_logger = MetricsLogger()

# ---------------------------------------------------------------------------
# Focused search URLs — each targets a different angle of the mission.
# Results are deduplicated across searches.
# ---------------------------------------------------------------------------
_BASE = "https://www.developmentaid.org/grants/search?hiddenAdvancedFilters=0"
_AFRICA_NGO = "&locations=3&applicantTypes=1"

SEARCH_URLS: List[str] = [
    # 1. Education sector + keyword "ICT"  (~185 results, high precision)
    f"{_BASE}{_AFRICA_NGO}&sectors=5&sort=relevance.desc&searchedText=ICT",

    # 2. Education sector + keyword "digital"  (~604 results, digital literacy/tools)
    f"{_BASE}{_AFRICA_NGO}&sectors=5&sort=relevance.desc&searchedText=digital",

    # 3. Education sector + keyword "technology"  (~723 results, broader tech + education)
    f"{_BASE}{_AFRICA_NGO}&sectors=5&sort=relevance.desc&searchedText=technology",

    # 4. ICT sector + Africa + NGOs  (~107 results, pure ICT grants)
    f"{_BASE}{_AFRICA_NGO}&sectors=13&searchedFields=title",

    # 5. Keyword "ICT digital schools" without sector lock (~207 results)
    f"{_BASE}{_AFRICA_NGO}&sort=relevance.desc&searchedText=ICT%20digital%20schools",
]

CARDS_PER_PAGE = 50           # DevelopmentAid renders 50 cards per page
MAX_PAGES_PER_SEARCH = 5      # Cap per search URL (250 grants) to stay focused


class DevelopmentAidProfile(BasePlaywrightProfile):
    """
    Playwright profile for DevelopmentAid grant search.

    Overrides ``run()`` entirely because grants are extracted from structured
    Angular ``da-search-card`` components rather than free-form HTML.
    """

    # -- Site metadata --------------------------------------------------------
    site_name = "DevelopmentAid"
    site_url = "https://www.developmentaid.org"
    description = (
        "International development grants database — "
        "multi-query search targeting ICT / Education / Digital for Africa"
    )

    base_urls = SEARCH_URLS
    css_selector = "da-search-card"
    pagination_type = "query"

    # -- BaseSiteProfile compatibility stubs ----------------------------------

    def get_page_url(self, base_url: str, page_number: int) -> str:
        if page_number <= 1:
            return base_url
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}pageNr={page_number}"

    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """Not used — card parsing happens in ``_parse_cards``."""
        return None

    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        """Not used — end-of-results is handled inside ``run()``."""
        return True

    # =========================================================================
    # Custom run()  —  navigate → parse Angular cards → relevance score
    # =========================================================================

    async def run(
        self,
        context: BrowserContext,
        llm_strategy,          # unused — extraction is card-based
        required_keys: List[str],
        seen_titles: Set[str],
        relevance_analyzer,
    ) -> List[dict]:
        page = await new_stealth_page(context)
        all_grants: List[dict] = []
        cookie_dismissed = False

        try:
            for search_idx, search_url in enumerate(SEARCH_URLS, 1):
                logger.info(f"{'='*70}")
                logger.info(
                    f"[DevelopmentAid] Search {search_idx}/{len(SEARCH_URLS)}: "
                    f"{search_url[:120]}…"
                )
                logger.info(f"{'='*70}")

                # ------ Navigate to search URL ------
                await page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=PLAYWRIGHT_DEFAULT_TIMEOUT,
                )

                if not cookie_dismissed:
                    await self._dismiss_cookie_banner(page)
                    cookie_dismissed = True

                await self._wait_for_cards(page)

                # Read total result count
                total = await self._get_total_results(page)
                logger.info(f"[DevelopmentAid] Search {search_idx} returned {total} results.")

                if total == 0:
                    logger.info("[DevelopmentAid] No results — skipping to next search.")
                    continue

                max_pages = min(
                    (total // CARDS_PER_PAGE) + (1 if total % CARDS_PER_PAGE else 0),
                    MAX_PAGES_PER_SEARCH,
                )

                # ------ Paginate and parse ------
                page_number = 1
                consecutive_empty = 0

                while page_number <= max_pages:
                    url = self.get_page_url(search_url, page_number)
                    logger.info(
                        f"[DevelopmentAid] Search {search_idx}, page "
                        f"{page_number}/{max_pages}"
                    )

                    # Navigate if not the first page of this search
                    if page_number > 1:
                        await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=PLAYWRIGHT_DEFAULT_TIMEOUT,
                        )
                        await self._wait_for_cards(page)

                    # Parse cards
                    with metrics_logger.measure(
                        "devaid_parse_cards", site=self.site_name, url=url
                    ) as ctx:
                        rows = await self._parse_cards(page)
                        ctx.items = len(rows)

                    if not rows:
                        logger.info(
                            f"[DevelopmentAid] No cards on page {page_number}."
                        )
                        consecutive_empty += 1
                        if consecutive_empty >= 2:
                            logger.info(
                                "[DevelopmentAid] 2 consecutive empty pages — "
                                "moving to next search."
                            )
                            break
                        page_number += 1
                        continue

                    consecutive_empty = 0

                    # --- Filter / dedup / relevance ---
                    for grant in rows:
                        if not is_complete_grant(grant, required_keys):
                            continue
                        if is_duplicate_grant(grant.get("title"), seen_titles):
                            logger.debug(
                                f"  Duplicate: {grant.get('title')} — skip."
                            )
                            continue

                        # Deadline check — skip past/expiring grants before LLM call
                        dl = grant.get("deadline", "")
                        if dl and not is_deadline_valid(dl):
                            logger.debug(
                                f"  Skipping '{grant.get('title')}': "
                                f"deadline '{dl}' is past or too soon."
                            )
                            continue

                        logger.info(
                            f"  Analyzing relevance: {grant.get('title', '?')} …"
                        )
                        analysis = await relevance_analyzer(grant)

                        if analysis:
                            if "score" in analysis and "relevance_score" not in analysis:
                                analysis["relevance_score"] = int(
                                    analysis.pop("score", 0)
                                )
                            if (
                                "reasoning" in analysis
                                and "relevance_reasoning" not in analysis
                            ):
                                analysis["relevance_reasoning"] = analysis.pop(
                                    "reasoning", ""
                                )
                            grant.update(analysis)
                            score = grant.get(
                                "relevance_score", grant.get("score", 0)
                            )
                            if score >= MIN_RELEVANCE_SCORE:
                                logger.info(
                                    f"  ✓ Relevant ({score}/100): {grant['title']}"
                                )
                                grant["source_website"] = self.site_name
                                seen_titles.add(grant["title"])
                                all_grants.append(grant)
                            else:
                                logger.info(
                                    f"  ✗ Low score ({score}): {grant['title']}"
                                )
                        else:
                            logger.warning(
                                f"  Could not score: {grant.get('title', '?')}"
                            )

                    logger.info(
                        f"[DevelopmentAid] Search {search_idx}, page {page_number} done — "
                        f"{len(all_grants)} grants total so far."
                    )

                    page_number += 1
                    await page.wait_for_timeout(2000)

                logger.info(
                    f"[DevelopmentAid] Search {search_idx} complete — "
                    f"{len(all_grants)} grants so far across all searches."
                )

        except Exception as exc:
            logger.error(
                f"[DevelopmentAid] run() failed: {exc}", exc_info=True
            )
        finally:
            await page.close()

        logger.info(
            f"[DevelopmentAid] Finished all {len(SEARCH_URLS)} searches — "
            f"{len(all_grants)} grants passed relevance threshold."
        )
        return all_grants

    # =========================================================================
    # Private helpers
    # =========================================================================

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        """Click the cookie-accept button if visible."""
        try:
            btn = await page.query_selector(
                "button:has-text('I Accept'), button:has-text('Accept')"
            )
            if btn:
                await btn.click()
                logger.debug("[DevelopmentAid] Cookie banner dismissed.")
                await page.wait_for_timeout(500)
        except Exception:
            pass

    async def _wait_for_cards(self, page: Page) -> None:
        """Wait for Angular to render at least one ``da-search-card``."""
        try:
            await page.wait_for_selector(
                "da-search-card", timeout=15000
            )
        except Exception:
            logger.warning(
                "[DevelopmentAid] Timed out waiting for da-search-card."
            )
        # Extra buffer for Angular digest
        await page.wait_for_timeout(2000)

    async def _get_total_results(self, page: Page) -> int:
        """Read the '2,883 results' counter."""
        try:
            text = await page.evaluate("""
                () => {
                    const el = document.querySelector('.search-total-items');
                    if (el) return el.textContent.trim();
                    const mob = document.querySelector('.mobile-search-counter');
                    if (mob) return mob.textContent.trim();
                    return '';
                }
            """)
            # Parse "2,883\\nresults" or "2,883 results"
            digits = text.replace(",", "").split()[0] if text else "0"
            return int(digits)
        except (ValueError, IndexError):
            return 0

    async def _parse_cards(self, page: Page) -> List[dict]:
        """
        Extract structured grant dicts from all ``da-search-card`` elements
        currently rendered on the page.
        """
        raw = await page.evaluate("""
            () => {
                const cards = document.querySelectorAll('da-search-card');
                return Array.from(cards).map(card => {
                    // Title and detail link
                    const titleEl = card.querySelector('a.search-card__title')
                                 || card.querySelector('a.search-card__title-mobile');
                    const title = titleEl ? titleEl.textContent.trim() : '';
                    const href  = titleEl ? titleEl.getAttribute('href') : '';

                    // Funding organisation (from the avatar image alt text)
                    const orgImg = card.querySelector('.search-card__avatar img');
                    const org = orgImg ? (orgImg.getAttribute('alt') || '').trim() : '';

                    // Label-value pairs from detail sections
                    const details = {};
                    const detailDivs = card.querySelectorAll('.details-container > div');
                    detailDivs.forEach(div => {
                        const spans = div.querySelectorAll('span');
                        if (spans.length >= 2) {
                            const key = spans[0].textContent.trim().replace(':', '');
                            const val = spans[1].textContent.trim();
                            if (key && val) details[key] = val;
                        }
                    });

                    // Deadline (in the funding-md-column area)
                    let deadline = details['Application deadline'] || '';
                    if (!deadline) {
                        const dlArea = card.querySelector('.search-card__funding-md-column');
                        if (dlArea) {
                            const spans = dlArea.querySelectorAll('span');
                            spans.forEach(s => {
                                const t = s.textContent.trim();
                                if (t.match(/\\w{3}\\s+\\d{1,2},\\s+\\d{4}/)) deadline = t;
                            });
                        }
                    }

                    return { title, href, org, details, deadline };
                });
            }
        """)

        grants: List[dict] = []
        for r in raw:
            title = (r.get("title") or "").strip()
            if not title or len(title) < 3:
                continue

            href = r.get("href", "")
            application_url = (
                f"https://www.developmentaid.org{href}" if href.startswith("/") else href
            )

            details = r.get("details", {})
            deadline = r.get("deadline", "") or details.get("Application deadline", "")

            grant: dict = {
                "title": title,
                "description": self._build_description(r),
                "application_url": application_url,
                "funding_organization": r.get("org", "") or details.get("Funding agency", ""),
                "geographic_focus": details.get("Location", ""),
                "eligibility_criteria": details.get("Applicants", ""),
                "grant_amount": details.get("Budget", ""),
                "deadline": deadline,
                "thematic_areas": details.get("Sector", "Education"),
                "date_posted": details.get("Posted", ""),
                "source_website": self.site_name,
            }
            grants.append(grant)

        return grants

    @staticmethod
    def _build_description(row: dict) -> str:
        """
        Assemble a useful description from the card's metadata.

        Detail pages are partially paywalled, so we build the best description
        we can from the listing-page card data.
        """
        parts: List[str] = []
        title = row.get("title", "")
        org = row.get("org", "")
        details = row.get("details", {})

        if org and org != title:
            parts.append(f"Funded by {org}.")

        location = details.get("Location", "")
        if location:
            parts.append(f"Location: {location}.")

        applicants = details.get("Applicants", "")
        if applicants:
            parts.append(f"Eligible applicants: {applicants}.")

        budget = details.get("Budget", "")
        if budget and budget != "N/A":
            parts.append(f"Budget: {budget}.")

        citizenships = details.get("Citizenships", "")
        if citizenships:
            parts.append(f"Citizenships: {citizenships}.")

        status = details.get("Status", "")
        if status:
            parts.append(f"Status: {status}.")

        agency = details.get("Funding agency", "")
        if agency:
            parts.append(f"Funding agency type: {agency}.")

        return " ".join(parts) if parts else title

    # -- Info -----------------------------------------------------------------

    def get_site_info(self) -> dict:
        info = super().get_site_info()
        info.update(
            {
                "rendering": "Playwright (Angular SPA — card-based extraction)",
                "requires_auth": False,
                "search_strategy": f"{len(SEARCH_URLS)} focused queries (ICT/digital/technology × Education × Africa)",
                "max_pages_per_search": MAX_PAGES_PER_SEARCH,
                "results_per_page": CARDS_PER_PAGE,
            }
        )
        return info
