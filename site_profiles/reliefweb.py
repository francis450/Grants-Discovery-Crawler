"""
Site profile for ReliefWeb (reliefweb.int) — Playwright version.

ReliefWeb uses a React-based search interface.  Although it was never
successfully tested with the Crawl4AI path, it likely suffers from the same
JS-rendering issues as GlobalGiving (empty initial HTML).  This profile
waits for the search results to render before extraction.
"""

from typing import List, Optional
from playwright.async_api import Page

from config import PLAYWRIGHT_DEFAULT_TIMEOUT
from .base_playwright_profile import BasePlaywrightProfile


class ReliefWebProfile(BasePlaywrightProfile):
    """
    Playwright-based profile for ReliefWeb training/funding opportunities.
    """

    # Site metadata
    site_name = "ReliefWeb"
    site_url = "https://reliefweb.int"
    description = "UN humanitarian information with funding and training opportunities"

    # Scraping configuration
    base_urls = [
        "https://reliefweb.int/training?search=education+technology&country=Kenya",
        "https://reliefweb.int/training?search=digital+literacy&region=Eastern+Africa",
        "https://reliefweb.int/updates?search=grant+funding+education&country=Kenya&type=Funding",
    ]

    css_selector = (
        "article.rw-river-article, div.search-result, li.article-item, "
        "article[class*='river'], div[class*='search-result']"
    )
    pagination_type = "query"

    def get_page_url(self, base_url: str, page_number: int) -> str:
        if page_number == 1:
            return base_url
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}page={page_number - 1}"  # 0-indexed

    # ------------------------------------------------------------------
    # Playwright hooks
    # ------------------------------------------------------------------

    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """Navigate and wait for ReliefWeb's React search results to render."""
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=PLAYWRIGHT_DEFAULT_TIMEOUT,
            )

            if response and response.status >= 400:
                return None

            result_selectors = [
                "article.rw-river-article",
                "article[class*='river']",
                "div.search-result",
                "div[class*='search-result']",
                "li.article-item",
                "main",
            ]

            for selector in result_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=12000)
                    break
                except Exception:
                    continue

            # Let React finish
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            return await page.content()

        except Exception as e:
            from utils.logging_utils import logger
            logger.error(f"[ReliefWeb] fetch_page_content failed: {e}")
            return None

    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        """Check if React rendered any article/result elements."""
        selectors = [
            "article.rw-river-article",
            "article[class*='river']",
            "div.search-result",
            "div[class*='search-result']",
            "li.article-item",
        ]
        for sel in selectors:
            elements = await page.query_selector_all(sel)
            if elements:
                return False

        body_text = await page.inner_text("body")
        lower = body_text.lower()
        if any(phrase in lower for phrase in [
            "no results",
            "0 results",
            "nothing to show",
        ]):
            return True

        if len(body_text.strip()) < 300:
            return True

        return True  # No result elements found

    def get_site_info(self) -> dict:
        info = super().get_site_info()
        info.update({
            "rendering": "Playwright (React search interface)",
            "categories_crawled": [
                "Training - Education Technology (Kenya)",
                "Training - Digital Literacy (Eastern Africa)",
                "Funding Reports - Education (Kenya)",
            ],
            "pagination_format": "?page={N} (0-indexed)",
        })
        return info
