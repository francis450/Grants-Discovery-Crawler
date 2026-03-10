"""
Site profile for DevEx Funding (devex.com/funding) — Playwright version.

DevEx is a React SPA that actively blocks headless browsers.  This profile
uses direct Playwright with stealth to wait for the JS-rendered funding
cards, dismiss cookie banners, and handle anti-bot redirects.
"""

from typing import List, Optional
from playwright.async_api import Page

from config import PLAYWRIGHT_DEFAULT_TIMEOUT
from .base_playwright_profile import BasePlaywrightProfile


class DevExProfile(BasePlaywrightProfile):
    """
    Playwright-based profile for DevEx funding opportunities.

    Previous Crawl4AI attempts returned ``ERR_ABORTED`` / 0 grants because:
    - Content is rendered client-side via React
    - The site detects headless browsers and aborts navigation
    """

    # Site metadata
    site_name = "DevEx Funding"
    site_url = "https://www.devex.com"
    description = "Development sector funding opportunities from major donors"

    # Scraping configuration
    base_urls = [
        # Education sector funding
        "https://www.devex.com/funding/r?report=tender-849820&filter%5Bnews_topics%5D%5B%5D=Careers%20%26%20Education&filter%5Bplaces%5D%5B%5D=Eastern%20Africa&filter%5Btype%5D%5B%5D=funding_info&filter%5Btype%5D%5B%5D=tender&filter%5Btype%5D%5B%5D=grant&filter%5Btype%5D%5B%5D=open_opportunity&filter%5Bstatuses%5D%5B%5D=forecast&filter%5Bstatuses%5D%5B%5D=open&sorting%5Border%5D=desc&sorting%5Bfield%5D=updated_at",
    ]

    css_selector = "div.tender, article.tender, div[class*='tender'], div[class*='Tender']"
    pagination_type = "query"

    def get_page_url(self, base_url: str, page_number: int) -> str:
        if page_number == 1:
            return base_url
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}page={page_number}"

    # ------------------------------------------------------------------
    # Playwright hooks
    # ------------------------------------------------------------------

    async def configure_page(self, page: Page) -> None:
        """Block heavy assets to speed up loads and reduce detection surface."""
        await page.route(
            "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf}",
            lambda route: route.abort(),
        )

    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """Navigate to DevEx, wait for React-rendered funding cards."""
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PLAYWRIGHT_DEFAULT_TIMEOUT,
            )

            if response and response.status >= 400:
                return None

            # Wait for JS content — try several possible selectors
            content_selectors = [
                "div.tender",
                "article.tender",
                "div[class*='tender']",
                "div[class*='Tender']",
                "div[class*='funding']",
                "div[class*='Funding']",
                "table tbody tr",
                "main",
            ]

            for selector in content_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=10000)
                    break
                except Exception:
                    continue

            # Let remaining XHR calls settle
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Dismiss cookie consent if present
            for consent_sel in [
                "button[id*='cookie']",
                "button[class*='cookie']",
                "button[class*='consent']",
                "button:has-text('Accept')",
                "button:has-text('I agree')",
            ]:
                try:
                    btn = await page.query_selector(consent_sel)
                    if btn:
                        await btn.click()
                        await page.wait_for_timeout(500)
                        break
                except Exception:
                    continue

            return await page.content()

        except Exception as e:
            from utils.logging_utils import logger
            logger.error(f"[DevEx] fetch_page_content failed: {e}")
            return None

    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        """Check rendered DOM for tender cards."""
        selectors = [
            "div.tender",
            "article.tender",
            "div[class*='tender']",
            "div[class*='Tender']",
        ]
        for sel in selectors:
            elements = await page.query_selector_all(sel)
            if elements:
                return False

        # Check for explicit "no results" messages
        body_text = await page.inner_text("body")
        lower = body_text.lower()
        if any(phrase in lower for phrase in [
            "no results found",
            "no funding opportunities",
            "0 results",
        ]):
            return True

        # Very short body → likely empty/broken render
        if len(body_text.strip()) < 200:
            return True

        return True  # No cards found by any selector

    def get_site_info(self) -> dict:
        info = super().get_site_info()
        info.update({
            "rendering": "Playwright (React SPA + anti-bot)",
            "categories_crawled": [
                "Education + Technology",
                "Africa + Education",
                "Digital Literacy + Africa",
            ],
            "pagination_format": "?page={N}",
        })
        return info
