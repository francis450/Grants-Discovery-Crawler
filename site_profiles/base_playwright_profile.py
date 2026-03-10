"""
Base profile for Playwright-based grant websites.

This module defines the abstract base class for sites that need direct Playwright
control — typically JS-heavy SPAs or sites with anti-bot measures that cause
Crawl4AI's default rendering to fail.

Mirrors the ``BaseAPIProfile`` pattern: Playwright profiles manage their own
browser interaction and return grant dicts, completely bypassing ``AsyncWebCrawler``.
"""

import json
from abc import abstractmethod
from typing import Any, Dict, List, Optional, Set, Tuple

from playwright.async_api import BrowserContext, Page

from config import MAX_PAGES, MIN_RELEVANCE_SCORE, RELEVANCE_PROVIDER, PLAYWRIGHT_DEFAULT_TIMEOUT
from models.grant import Grant
from utils.data_utils import is_complete_grant, is_duplicate_grant
from utils.logging_utils import logger, MetricsLogger
from utils.playwright_utils import new_stealth_page

from .base_profile import BaseSiteProfile

metrics_logger = MetricsLogger()


class BasePlaywrightProfile(BaseSiteProfile):
    """
    Abstract base for sites that require direct Playwright rendering.

    Subclasses MUST implement:
        ``fetch_page_content(page, url)``  – navigate, wait for JS, return HTML
        ``detect_end_of_results_pw(page, url)``  – check if pagination is exhausted

    Subclasses MAY override:
        ``configure_page(page)``  – set extra headers, cookies, intercept requests
        ``extract_css_content(page, url)``  – return only the CSS-selected subtree
    """

    # Flag checked by main.py to route to the Playwright branch
    use_playwright: bool = True

    # ------------------------------------------------------------------
    # Abstract methods – each site controls its own JS lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch_page_content(self, page: Page, url: str) -> Optional[str]:
        """
        Navigate to *url*, wait for the JS-rendered content to appear, and
        return the relevant portion of page HTML.

        Implementations should:
        - call ``page.goto(url, ...)``
        - wait for site-specific selectors (``page.wait_for_selector(...)``)
        - optionally scroll, dismiss cookie banners, etc.
        - return the HTML of the content area (or full ``page.content()``)

        Returns None if the page failed to load or rendered nothing useful.
        """
        pass

    @abstractmethod
    async def detect_end_of_results_pw(self, page: Page, url: str) -> bool:
        """
        Return True when there are no more results for the current URL
        (e.g. 0 cards rendered, "no results" banner visible, etc.).

        This replaces the Crawl4AI-based ``detect_end_of_results`` from
        ``BaseSiteProfile``.
        """
        pass

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    async def configure_page(self, page: Page) -> None:
        """
        Optional hook called once per page before any navigation.

        Use for things like:
        - ``await page.set_extra_http_headers({...})``
        - ``await page.route(...)`` to block analytics/ads
        - Any one-time cookie injection
        """
        pass

    async def extract_css_content(self, page: Page, url: str) -> Optional[str]:
        """
        Optionally return only the CSS-selected subtree instead of the full page.

        Default implementation returns all elements matching ``self.css_selector`` 
        concatenated as outer HTML. Override if you need finer control.
        """
        selector = self.get_css_selector()
        if not selector:
            return await page.content()

        # css_selector may be a comma-separated union — query all
        elements = await page.query_selector_all(selector)
        if not elements:
            return None

        parts = []
        for el in elements:
            html = await el.evaluate("el => el.outerHTML")
            parts.append(html)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Concrete orchestrator  (called from main.py)
    # ------------------------------------------------------------------

    async def run(
        self,
        context: BrowserContext,
        llm_strategy,
        required_keys: List[str],
        seen_titles: Set[str],
        relevance_analyzer,
    ) -> Tuple[List[dict], List[dict]]:
        """
        Full crawl loop for this site using the provided Playwright context.

        Args:
            context: A ``BrowserContext`` with stealth already configured.
            llm_strategy: The ``LLMExtractionStrategy`` for grant extraction.
            required_keys: Fields that must be present (e.g. ``["title", "description"]``).
            seen_titles: Mutable set for cross-site deduplication.
            relevance_analyzer: Async callable ``(grant_dict) -> Optional[dict]``
                                that returns relevance analysis (score, reasoning, …).

        Returns:
            (all_grants, new_grants):
                all_grants – every grant that passed the relevance threshold.
                new_grants – subset that wasn't already in ``seen_titles``.
        """
        from utils.playwright_utils import extract_grants_from_html

        all_grants: List[dict] = []

        for url_idx, base_url in enumerate(self.get_base_urls(), 1):
            logger.info(f"{'='*80}")
            logger.info(
                f"[Playwright] {self.site_name} — URL {url_idx}/{len(self.get_base_urls())}: {base_url}"
            )
            logger.info(f"{'='*80}")

            page = await new_stealth_page(context)
            await self.configure_page(page)

            page_number = 1
            consecutive_empty = 0

            try:
                while page_number <= MAX_PAGES:
                    url = self.get_page_url(base_url, page_number)
                    logger.info(f"[Playwright] Loading page {page_number}: {url}")

                    # --- Fetch & render ---
                    with metrics_logger.measure(
                        "pw_fetch_page", site=self.site_name, url=url
                    ) as ctx:
                        html = await self.fetch_page_content(page, url)
                        if html is None:
                            ctx.status = "ERROR"
                            ctx.error = "fetch_page_content returned None"

                    if html is None:
                        logger.warning(
                            f"[Playwright] Failed to load {url} — skipping."
                        )
                        break

                    # --- End-of-results check ---
                    end = await self.detect_end_of_results_pw(page, url)
                    if end:
                        logger.info(
                            f"[Playwright] End of results detected for {base_url}."
                        )
                        break

                    # --- CSS subtree extraction (optional) ---
                    css_html = await self.extract_css_content(page, url)
                    content_for_llm = css_html if css_html else html

                    # --- LLM extraction ---
                    with metrics_logger.measure(
                        "pw_extract_llm", site=self.site_name, url=url
                    ) as ex_ctx:
                        extracted = await extract_grants_from_html(
                            content_for_llm, llm_strategy, self.site_name
                        )
                        ex_ctx.items = len(extracted)

                    if not extracted:
                        logger.info(
                            f"[Playwright] No grants extracted from page {page_number}."
                        )
                        consecutive_empty += 1
                        if consecutive_empty >= 2:
                            logger.info(
                                f"[Playwright] 2 consecutive empty pages — moving on."
                            )
                            break
                        page_number += 1
                        continue

                    consecutive_empty = 0

                    # --- Post-processing (filter / dedup / relevance) ---
                    page_grants = await self._process_extracted_grants(
                        extracted,
                        required_keys,
                        seen_titles,
                        relevance_analyzer,
                    )

                    all_grants.extend(page_grants)
                    logger.info(
                        f"[Playwright] Page {page_number}: "
                        f"{len(page_grants)} grants passed filters. "
                        f"Total so far: {len(all_grants)}"
                    )

                    page_number += 1

                    # Polite delay
                    await page.wait_for_timeout(2000)

            finally:
                await page.close()

            logger.info(
                f"[Playwright] Completed {self.site_name} — {base_url} "
                f"({len(all_grants)} grants total)\n"
            )

        return all_grants

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _process_extracted_grants(
        self,
        extracted: List[dict],
        required_keys: List[str],
        seen_titles: Set[str],
        relevance_analyzer,
    ) -> List[dict]:
        """Filter, dedup, and score a batch of extracted grant dicts."""
        complete_grants = []

        for grant in extracted:
            # Remove false-positive error key
            if grant.get("error") is False:
                grant.pop("error", None)

            if not is_complete_grant(grant, required_keys):
                continue

            if is_duplicate_grant(grant.get("title"), seen_titles):
                logger.debug(f"Duplicate: {grant.get('title')} — skipping.")
                continue

            # Preliminary relevance gate
            if grant.get("is_relevant_preliminary") is False:
                logger.debug(
                    f"Skipping '{grant.get('title')}': not relevant (preliminary)."
                )
                continue

            # Deep relevance analysis
            logger.info(
                f"  Analyzing relevance: {grant.get('title', 'Unknown')} …"
            )
            analysis = await relevance_analyzer(grant)

            if analysis:
                # Normalize field names (xAI returns score/reasoning, model expects relevance_score/relevance_reasoning)
                if "score" in analysis and "relevance_score" not in analysis:
                    analysis["relevance_score"] = int(analysis.pop("score", 0))
                if "reasoning" in analysis and "relevance_reasoning" not in analysis:
                    analysis["relevance_reasoning"] = analysis.pop("reasoning", "")

                grant.update(analysis)
                score = grant.get("relevance_score", grant.get("score", 0))
                if score >= MIN_RELEVANCE_SCORE:
                    logger.info(
                        f"  ✓ Relevant ({score}/100): {grant.get('title')}"
                    )
                    grant["source_website"] = self.site_name
                    seen_titles.add(grant["title"])
                    complete_grants.append(grant)
                else:
                    logger.info(
                        f"  ✗ Low score ({score}): {grant.get('title')}"
                    )
            else:
                logger.warning(
                    f"  Could not analyze relevance for '{grant.get('title')}'."
                )

        return complete_grants

    # ------------------------------------------------------------------
    # BaseSiteProfile compatibility stubs (unused by the Playwright path
    # but required because BaseSiteProfile declares them abstract)
    # ------------------------------------------------------------------

    async def detect_end_of_results(self, crawler, url: str, session_id: str) -> bool:
        """Not used — Playwright profiles use ``detect_end_of_results_pw`` instead."""
        return False

