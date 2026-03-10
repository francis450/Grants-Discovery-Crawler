"""
Site profile for GlobalGiving (globalgiving.org) — Playwright version.

GlobalGiving is a React SPA.  The previous Crawl4AI profile falsely detected
"end of results" on every page because the initial HTML is nearly empty
(< 300 chars) before React hydrates.  This profile waits for the project
cards to render before extracting.
"""

import re
from typing import List, Optional
from playwright.async_api import Page

from config import PLAYWRIGHT_DEFAULT_TIMEOUT
from .base_playwright_profile import BasePlaywrightProfile


class GlobalGivingProfile(BasePlaywrightProfile):
    """
    Playwright-based profile for GlobalGiving project listings.
    """

    # Site metadata
    site_name = "GlobalGiving"
    site_url = "https://www.globalgiving.org"
    description = "Global crowdfunding and grants platform for nonprofits"

    # Scraping configuration
    base_urls = [
        "https://www.globalgiving.org/search/?size=25&nextPage=1&sortField=sortorder&selectedThemes=edu&selectedCountries=KE,TZ,UG,NG,GH,ZA,ET,RW,MW,SN",
        "https://www.globalgiving.org/search/?size=25&nextPage=1&sortField=sortorder&selectedThemes=tech&selectedCountries=KE,TZ,UG,NG,GH,ZA,ET,RW,MW,SN",
        "https://www.globalgiving.org/search/?size=25&nextPage=1&sortField=sortorder&selectedThemes=children&selectedCountries=KE,TZ,UG,NG,GH,ZA,ET,RW,MW,SN",
    ]

    css_selector = (
        "div.project-card, div.search-result-item, article.project-listing, "
        "div[class*='project-card'], div[class*='ProjectCard']"
    )
    pagination_type = "query"

    def get_page_url(self, base_url: str, page_number: int) -> str:
        if page_number == 1:
            return base_url
        if "nextPage=" in base_url:
            return re.sub(r"nextPage=\d+", f"nextPage={page_number}", base_url)
        return f"{base_url}&nextPage={page_number}"

    # ------------------------------------------------------------------
    # Playwright hooks
    # ------------------------------------------------------------------

    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """Navigate and wait for React project cards to hydrate."""
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PLAYWRIGHT_DEFAULT_TIMEOUT,
            )

            if response and response.status >= 400:
                return None

            # Wait for project cards to render
            card_selectors = [
                "div.project-card",
                "div[class*='project-card']",
                "div[class*='ProjectCard']",
                "div.search-result-item",
                "article.project-listing",
                "main",
            ]

            for selector in card_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=12000)
                    break
                except Exception:
                    continue

            # Wait for network to settle (React data fetching)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Scroll down to trigger lazy-loaded cards
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            return await page.content()

        except Exception as e:
            from utils.logging_utils import logger
            logger.error(f"[GlobalGiving] fetch_page_content failed: {e}")
            return None

    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        """Count rendered project cards — 0 means we're past the last page."""
        card_selectors = [
            "div.project-card",
            "div[class*='project-card']",
            "div[class*='ProjectCard']",
            "div.search-result-item",
        ]
        for sel in card_selectors:
            elements = await page.query_selector_all(sel)
            if elements:
                return False

        body_text = await page.inner_text("body")
        lower = body_text.lower()
        if any(phrase in lower for phrase in [
            "no projects found",
            "no results",
            "0 projects",
        ]):
            return True

        return True  # No cards rendered at all

    def get_site_info(self) -> dict:
        info = super().get_site_info()
        info.update({
            "rendering": "Playwright (React SPA)",
            "categories_crawled": [
                "Education (Africa)",
                "Technology (Africa)",
                "Children/Youth (Africa)",
            ],
            "target_countries": "KE, TZ, UG, NG, GH, ZA, ET, RW, MW, SN",
            "pagination_format": "?nextPage={N}",
        })
        return info
