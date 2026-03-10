"""
Playwright utilities for JS-heavy grant websites.

Provides a stealth browser launcher, HTML extraction helpers, and a standalone
page fetcher that the BasePlaywrightProfile (and analyze_grant_relevance) can use
when Crawl4AI's default rendering fails.
"""

import json
import os
from typing import Dict, List, Optional, Tuple

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from utils.logging_utils import logger
from config import PLAYWRIGHT_HEADLESS, PLAYWRIGHT_DEFAULT_TIMEOUT, PLAYWRIGHT_STEALTH

# ---------------------------------------------------------------------------
# Stealth browser helpers
# ---------------------------------------------------------------------------

async def create_stealth_context(
    playwright_instance,
    headless: bool = PLAYWRIGHT_HEADLESS,
) -> Tuple[Browser, BrowserContext]:
    """
    Launch Chromium and return a (browser, context) pair with stealth settings.

    The context has a realistic user-agent, viewport, locale, and – when the
    ``playwright-stealth`` package is installed – patches to hide the
    ``navigator.webdriver`` flag and other automation tells.

    Returns:
        (browser, context) tuple.  Caller is responsible for closing both.
    """
    browser = await playwright_instance.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        java_script_enabled=True,
    )

    # Apply playwright-stealth patches if available and enabled
    if PLAYWRIGHT_STEALTH:
        try:
            from playwright_stealth import stealth_async
            # stealth_async patches a single page; we create a temp page,
            # apply stealth, then close it — the context retains the patches
            # for all subsequent pages.
            page_for_stealth = await context.new_page()
            await stealth_async(page_for_stealth)
            await page_for_stealth.close()
            logger.debug("Playwright-stealth patches applied to context.")
        except ImportError:
            logger.warning(
                "playwright-stealth not installed – running without stealth patches. "
                "Install with: pip install playwright-stealth"
            )

    context.set_default_timeout(PLAYWRIGHT_DEFAULT_TIMEOUT)
    return browser, context


async def new_stealth_page(context: BrowserContext) -> Page:
    """Create a new page with stealth patches already baked in via the context."""
    page = await context.new_page()

    # Extra JS-level patches (belt-and-suspenders)
    await page.add_init_script("""
        // Hide webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // Chrome runtime stub
        window.chrome = { runtime: {} };
        // Fake plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });
        // Fake languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });
    """)
    return page


# ---------------------------------------------------------------------------
# HTML → grants extraction  (reuses the project's LLM pipeline)
# ---------------------------------------------------------------------------

async def extract_grants_from_html(
    html: str,
    llm_strategy,
    site_name: str = "Unknown",
) -> List[dict]:
    """
    Feed raw HTML into the existing LLM extraction pipeline and return grant dicts.

    This mirrors what ``fetch_and_process_page`` does after ``crawler.arun()``
    returns ``result.extracted_content``, but works with HTML obtained from a
    direct Playwright fetch.

    For Groq (manual chunked extraction) it delegates to
    ``extract_grants_from_html_groq``.  For every other provider the html is
    passed through the ``LLMExtractionStrategy`` directly via its internal
    ``run`` / ``extract`` method.

    Args:
        html: The full page HTML (or the CSS-selected subset).
        llm_strategy: An ``LLMExtractionStrategy`` instance.
        site_name: Used only for logging.

    Returns:
        List of grant dicts (may be empty).
    """
    provider = getattr(llm_strategy, "provider", "")

    # Groq manual path – reuse existing chunked helper
    if "groq" in str(provider).lower():
        from utils.groq_utils import extract_grants_from_html_groq
        logger.info(f"[{site_name}] Extracting grants via manual Groq pipeline …")
        return await extract_grants_from_html_groq(html)

    # Standard path – call the strategy's extract method with markdown conversion
    try:
        # Convert HTML to markdown for cleaner LLM input
        try:
            from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
            md_gen = DefaultMarkdownGenerator()
            md_result = md_gen.generate_markdown(html)
            # md_result may be a MarkdownGenerationResult or dict
            if hasattr(md_result, 'raw_markdown'):
                content = md_result.raw_markdown
            elif isinstance(md_result, dict):
                content = md_result.get('raw_markdown', md_result.get('markdown', html))
            else:
                content = str(md_result) if md_result else html
        except Exception:
            # Fallback: strip tags with simple regex
            import re
            content = re.sub(r'<[^>]+>', ' ', html)
            content = re.sub(r'\s+', ' ', content).strip()

        result = llm_strategy.extract(url="", ix=0, html=content)
        if result:
            data = json.loads(result)
            if isinstance(data, list):
                return data
            return [data]

    except Exception as e:
        logger.error(f"[{site_name}] LLM extraction failed: {e}")

    return []


# ---------------------------------------------------------------------------
# Standalone full-page fetch (for Stage-2 relevance analysis)
# ---------------------------------------------------------------------------

async def fetch_full_page_playwright(
    url: str,
    wait_selector: Optional[str] = None,
    js_code: Optional[str] = None,
    timeout: int = PLAYWRIGHT_DEFAULT_TIMEOUT,
) -> Optional[str]:
    """
    Fetch a single URL with direct Playwright and return the rendered HTML.

    Useful as a fallback inside ``analyze_grant_relevance()`` when Crawl4AI's
    normal fetch returns empty content for JS-heavy grant detail pages.

    Args:
        url: The URL to fetch.
        wait_selector: Optional CSS selector to wait for before capturing HTML.
        js_code: Optional JavaScript to execute after page load (e.g. scroll).
        timeout: Navigation timeout in ms.

    Returns:
        The page's outer HTML string, or None on failure.
    """
    try:
        async with async_playwright() as pw:
            browser, context = await create_stealth_context(pw)
            page = await new_stealth_page(context)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=timeout)
                    except Exception:
                        # Selector didn't appear – still grab whatever rendered
                        logger.debug(f"wait_for_selector('{wait_selector}') timed out for {url}")

                # Let any remaining JS settle
                await page.wait_for_load_state("networkidle", timeout=15000)

                if js_code:
                    await page.evaluate(js_code)
                    await page.wait_for_timeout(2000)

                html = await page.content()
                return html

            finally:
                await context.close()
                await browser.close()

    except Exception as e:
        logger.error(f"Playwright full-page fetch failed for {url}: {e}")
        return None
