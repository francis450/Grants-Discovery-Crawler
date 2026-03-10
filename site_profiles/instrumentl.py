"""
Site profile for Instrumentl (instrumentl.com) — Playwright-based card extraction.

Instrumentl is a grant discovery platform with a public browse interface at
``https://www.instrumentl.com/browse-grants/``.  Grant listings are server-
rendered HTML — each card is a ``div.featured-grant`` containing structured
elements for title, funder, amount, deadline, description, and thematic tags.

Because the data is already structured inside the cards, this profile parses
them directly (no LLM extraction needed for the listing page).  Relevance
scoring (Stage 2) still runs on each grant.

Publicly visible grants are capped (~26 of 34 on the Africa page); the rest
sit behind a sign-up wall.  To maximise coverage without authentication, this
profile crawls **multiple category pages** on Instrumentl that overlap with
the mission (IT equipment refurbishment for African schools).  Grants are
deduplicated across pages by URL slug.

Card DOM structure
~~~~~~~~~~~~~~~~~~
::

    div.featured-grant
      ├── div.deadline > span              → "Rolling deadline" / "Applications due Mar 2, 2026"
      ├── div.header
      │   ├── h3 > a[href*="/grants/"]     → grant title + detail link
      │   ├── h4.funder-name > a           → funder organisation name
      │   └── span.label.label-grey (×N)   → thematic area tags
      └── div.description
          ├── span.amount                  → "Up to US $300,000" / "Unspecified amount"
          └── div.body                     → paragraph description text
"""

from typing import Dict, List, Optional, Set, Tuple

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
# Browse-grants URLs — mission-aligned category pages for Africa
#
# Each URL surfaces a different slice of Instrumentl's grant database.
# Grants are deduplicated across URLs by their href slug.
# ---------------------------------------------------------------------------
_BASE = "https://www.instrumentl.com/browse-grants/africa"

BROWSE_URLS: List[Dict[str, str]] = [
    # =================================================================
    # TIER 1 — DIRECT MISSION MATCH (IT / digital / computers / STEM)
    # These surface grants specifically about technology and education
    # =================================================================
    # 26 cards, 26 unique — core technology grants for Africa
    {
        "url": f"{_BASE}/technology-grants",
        "label": "Africa – technology",
    },
    # 27 cards, 11 unique — IT hardware / computer equipment for nonprofits
    {
        "url": f"{_BASE}/grants-for-computers-for-nonprofits",
        "label": "Africa – computers for nonprofits",
    },
    # 27 cards, 3 unique — STEM / digital literacy education
    {
        "url": f"{_BASE}/stem-education-grants",
        "label": "Africa – STEM education",
    },

    # =================================================================
    # TIER 2 — STRONG MATCH (education / schools / youth in Africa)
    # =================================================================
    # Primary Africa page — 26 cards, broadest Africa coverage
    {
        "url": f"{_BASE}/",
        "label": "Africa – all grants",
    },
    # 26 cards, 3 unique — education-focused nonprofits
    {
        "url": f"{_BASE}/grants-for-education-nonprofits",
        "label": "Africa – education nonprofits",
    },
    # 26 cards — K-12 schools (overlaps heavily but critical category)
    {
        "url": f"{_BASE}/grants-for-k-12-schools",
        "label": "Africa – K-12 schools",
    },
    # 26 cards, 1 unique — youth-focused programs
    {
        "url": f"{_BASE}/grants-for-youth-programs",
        "label": "Africa – youth programs",
    },
    # 27 cards, 2 unique — after-school / extracurricular programs
    {
        "url": f"{_BASE}/grants-for-after-school-programs",
        "label": "Africa – after school programs",
    },

    # =================================================================
    # TIER 3 — GOOD MATCH (development / capacity building / infrastructure)
    # =================================================================
    # 26 cards, 3 unique — international development focus
    {
        "url": f"{_BASE}/grants-for-international-development",
        "label": "Africa – international development",
    },
    # 27 cards — capacity building for nonprofits
    {
        "url": f"{_BASE}/capacity-building-grants-for-nonprofits",
        "label": "Africa – capacity building",
    },
    # 26 cards, 2 unique — community development & employment
    {
        "url": f"{_BASE}/community-development-and-employment-grants",
        "label": "Africa – community development",
    },
    # 27 cards, 2 unique — community service projects
    {
        "url": f"{_BASE}/grants-for-community-service-projects",
        "label": "Africa – community service projects",
    },
    # 25 cards, 12 unique — sustainability (circular economy, e-waste angle)
    {
        "url": f"{_BASE}/sustainability-grants",
        "label": "Africa – sustainability",
    },
    # 27 cards, 1 unique — public infrastructure
    {
        "url": f"{_BASE}/public-infrastructure-grants",
        "label": "Africa – public infrastructure",
    },

    # =================================================================
    # TIER 4 — SUPPLEMENTARY (broader funding categories with unique grants)
    # =================================================================
    # 27 cards, 24 unique — corporate funders (many unique grants!)
    {
        "url": f"{_BASE}/corporate-grants-for-nonprofits",
        "label": "Africa – corporate grants",
    },
    # 27 cards, 8 unique — large grants (>$25k typically)
    {
        "url": f"{_BASE}/large-grants-for-nonprofit-organizations",
        "label": "Africa – large grants",
    },
    # 26 cards, 2 unique — 501(c)(3) eligible organisations
    {
        "url": f"{_BASE}/grants-for-501-c-3",
        "label": "Africa – 501(c)(3) grants",
    },
    # 27 cards — grassroots organisations
    {
        "url": f"{_BASE}/grants-for-grassroots-organizations",
        "label": "Africa – grassroots organisations",
    },
    # 27 cards — small nonprofits
    {
        "url": f"{_BASE}/grants-for-small-nonprofits",
        "label": "Africa – small nonprofits",
    },
    # 27 cards — seed/startup funding
    {
        "url": f"{_BASE}/seed-grants-for-nonprofits",
        "label": "Africa – seed grants",
    },
]


class InstrumentlProfile(BasePlaywrightProfile):
    """
    Playwright profile for Instrumentl's public grant browse pages.

    Overrides ``run()`` entirely because grants are extracted from structured
    ``div.featured-grant`` card elements rather than free-form HTML.
    """

    # -- Site metadata --------------------------------------------------------
    site_name = "Instrumentl"
    site_url = "https://www.instrumentl.com"
    description = (
        "Grant discovery platform — 20 Africa category pages targeting "
        "technology, computers, STEM, education, youth, development, and more"
    )

    base_urls = [entry["url"] for entry in BROWSE_URLS]
    css_selector = "div.featured-grant"
    pagination_type = "none"  # No traditional pagination; one page per category URL

    # -- BaseSiteProfile / BasePlaywrightProfile stubs -----------------------

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """No pagination — always return the base URL."""
        return base_url

    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """Not used — card parsing happens in ``_parse_cards``."""
        return None

    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        """Not used — each category URL is a single page."""
        return True

    # =========================================================================
    # Custom run() — navigate → parse cards → relevance score
    # =========================================================================

    async def run(
        self,
        context: BrowserContext,
        llm_strategy,          # unused — extraction is card-based
        required_keys: List[str],
        seen_titles: Set[str],
        relevance_analyzer,
    ) -> List[dict]:
        """
        Crawl all configured Instrumentl browse-grants category pages,
        extract grant cards, deduplicate, and run relevance scoring.

        Returns:
            List of grant dicts that passed the relevance threshold.
        """
        page = await new_stealth_page(context)
        all_grants: List[dict] = []
        seen_slugs: Set[str] = set()  # Deduplicate across category pages by URL slug

        try:
            for idx, entry in enumerate(BROWSE_URLS, 1):
                url = entry["url"]
                label = entry["label"]

                logger.info(f"{'=' * 70}")
                logger.info(
                    f"[Instrumentl] Category {idx}/{len(BROWSE_URLS)}: {label}"
                )
                logger.info(f"  URL: {url}")
                logger.info(f"{'=' * 70}")

                # --- Navigate ---
                try:
                    resp = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=PLAYWRIGHT_DEFAULT_TIMEOUT,
                    )
                    if resp and resp.status == 404:
                        logger.warning(
                            f"[Instrumentl] 404 for {label} — skipping."
                        )
                        continue
                except Exception as exc:
                    logger.error(
                        f"[Instrumentl] Failed to load {label}: {exc}"
                    )
                    continue

                # Wait for grant cards to render
                await self._wait_for_cards(page)

                # --- Parse cards ---
                with metrics_logger.measure(
                    "instrumentl_parse_cards", site=self.site_name, url=url
                ) as ctx:
                    rows = await self._parse_cards(page)
                    ctx.items = len(rows)

                # Count how many are new (unseen slug)
                new_rows = [
                    r for r in rows if r.get("_slug") not in seen_slugs
                ]
                logger.info(
                    f"[Instrumentl] Parsed {len(rows)} cards, "
                    f"{len(new_rows)} new (not seen in earlier categories)."
                )

                # --- Filter / dedup / relevance ---
                for grant in new_rows:
                    slug = grant.pop("_slug", "")
                    if slug:
                        seen_slugs.add(slug)

                    if not is_complete_grant(grant, required_keys):
                        continue

                    if is_duplicate_grant(grant.get("title"), seen_titles):
                        logger.debug(
                            f"  Duplicate title: {grant.get('title')} — skip."
                        )
                        continue

                    # Deadline check
                    dl = grant.get("deadline", "")
                    if dl and dl != "Rolling deadline" and not is_deadline_valid(dl):
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
                        # Normalize field names
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
                    f"[Instrumentl] Category {idx} done — "
                    f"{len(all_grants)} grants total so far."
                )

                # Polite delay between category pages
                await page.wait_for_timeout(2000)

        except Exception as exc:
            logger.error(
                f"[Instrumentl] run() failed: {exc}", exc_info=True
            )
        finally:
            await page.close()

        logger.info(
            f"[Instrumentl] Finished all {len(BROWSE_URLS)} categories — "
            f"{len(all_grants)} grants passed relevance threshold."
        )
        return all_grants

    # =========================================================================
    # Private helpers
    # =========================================================================

    async def _wait_for_cards(self, page: Page) -> None:
        """Wait for at least one ``div.featured-grant`` card to render."""
        try:
            await page.wait_for_selector(
                "div.featured-grant", timeout=10000
            )
        except Exception:
            logger.warning(
                "[Instrumentl] Timed out waiting for div.featured-grant cards."
            )
        # Extra buffer for any lazy-loaded content
        await page.wait_for_timeout(1500)

    async def _parse_cards(self, page: Page) -> List[dict]:
        """
        Extract structured grant dicts from all ``div.featured-grant`` elements
        currently rendered on the page.

        Each dict includes a ``_slug`` key (the URL path component) used for
        cross-category deduplication.  The caller should pop it before storing.
        """
        raw = await page.evaluate("""
            () => {
                const cards = document.querySelectorAll('div.featured-grant');
                return Array.from(cards).map(card => {
                    // Title and detail link
                    const titleEl = card.querySelector('h3 a[href*="/grants/"]');
                    const title = titleEl ? titleEl.textContent.trim() : '';
                    const href  = titleEl ? (titleEl.getAttribute('href') || '') : '';

                    // Funder organisation
                    const funderEl = card.querySelector('h4.funder-name a')
                                  || card.querySelector('h4.funder-name');
                    const funder = funderEl ? funderEl.textContent.trim() : '';

                    // Thematic area tags
                    const tagEls = card.querySelectorAll('span.label.label-grey');
                    const tags = Array.from(tagEls).map(el => el.textContent.trim());

                    // Grant amount
                    const amountEl = card.querySelector('span.amount');
                    const amount = amountEl ? amountEl.textContent.trim() : '';

                    // Deadline
                    const deadlineEl = card.querySelector('div.deadline span');
                    const deadline = deadlineEl ? deadlineEl.textContent.trim() : '';

                    // Description body
                    const bodyEl = card.querySelector('div.description div.body');
                    const description = bodyEl ? bodyEl.textContent.trim() : '';

                    return { title, href, funder, tags, amount, deadline, description };
                });
            }
        """)

        grants: List[dict] = []
        for r in raw:
            title = (r.get("title") or "").strip()
            if not title or len(title) < 3:
                continue

            href = r.get("href", "")
            # Build absolute URL and extract slug for dedup
            if href.startswith("/"):
                application_url = f"https://www.instrumentl.com{href}"
                slug = href
            elif href.startswith("http"):
                application_url = href
                slug = href.split("instrumentl.com")[-1] if "instrumentl.com" in href else href
            else:
                application_url = href
                slug = href

            # Clean deadline text — remove redundant prefixes
            raw_deadline = (r.get("deadline") or "").strip()
            deadline = self._normalize_deadline(raw_deadline)

            # Clean amount text
            amount = (r.get("amount") or "").strip()
            if amount.lower() in ("unspecified amount",):
                amount = ""

            tags = r.get("tags", [])
            description = (r.get("description") or "").strip()
            funder = (r.get("funder") or "").strip()

            grant: dict = {
                "title": title,
                "description": description if description else title,
                "application_url": application_url,
                "funding_organization": funder,
                "grant_amount": amount,
                "deadline": deadline,
                "thematic_areas": tags if tags else [],
                "geographic_focus": "Africa",
                "source_website": self.site_name,
                "_slug": slug,  # Used for cross-category dedup; caller pops this
            }
            grants.append(grant)

        return grants

    @staticmethod
    def _normalize_deadline(raw: str) -> str:
        """
        Normalise deadline text from Instrumentl cards.

        Examples:
            "Rolling deadline"              → "Rolling deadline"
            "Applications due"              → "" (date not shown publicly)
            "Applications dueFeb 28, 2026"  → "Feb 28, 2026"
            "Letter of inquiry dueJun 9, 2026" → "Jun 9, 2026"
            "Pre proposal dueOct 1, 2026"   → "Oct 1, 2026"
        """
        if not raw:
            return ""
        if raw.lower() == "rolling deadline":
            return "Rolling deadline"

        # Strip common prefixes to extract the actual date
        import re
        prefixes = [
            r"Applications\s*due\s*",
            r"Letter of inquiry\s*due\s*",
            r"Pre\s*proposal\s*due\s*",
        ]
        cleaned = raw
        for prefix in prefixes:
            cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE).strip()

        return cleaned if cleaned else ""

    # -- Info -----------------------------------------------------------------

    def get_site_info(self) -> dict:
        info = super().get_site_info()
        info.update(
            {
                "rendering": "Playwright (server-rendered HTML — card-based extraction)",
                "requires_auth": False,
                "browse_strategy": (
                    f"{len(BROWSE_URLS)} category pages across 4 tiers: "
                    "direct (IT/computers/STEM), education (K-12/youth), "
                    "development (capacity/infrastructure), supplementary (corporate/large/seed)"
                ),
                "grants_per_page": "~26 publicly visible (sign-up wall hides remainder)",
                "deduplication": "By URL slug across categories",
            }
        )
        return info
