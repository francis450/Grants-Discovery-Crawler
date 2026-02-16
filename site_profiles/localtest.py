"""
Site profile for local test HTML file.

This profile is used for testing the grant filtering system with a known dataset
of grants (5 should pass, 5 should fail) to validate that the relevance scoring
and filtering logic is working correctly.
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class LocalTestProfile(BaseSiteProfile):
    """
    Profile for crawling a local test HTML file.

    Site characteristics:
    - URL structure: Single local file
    - Pagination: None (single page only)
    - CSS selector: article.grant-item
    - End detection: Always ends after page 1
    """

    # Site metadata
    site_name = "Local Test"
    site_url = "file://C:/Users/Francis/Desktop/DSG/deepseek-ai-web-crawler/test_grants_page.html"
    description = "Test page with 10 known grants (5 pass, 5 fail) for validation"

    # Scraping configuration
    base_urls = [
        "file://C:/Users/Francis/Desktop/DSG/deepseek-ai-web-crawler/test_grants_page.html"
    ]

    css_selector = "article.grant-item"
    pagination_type = "none"  # Single page only

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        Since this is a local test file, we only have one page.

        Args:
            base_url: The local file path
            page_number: Page number (1-indexed)

        Returns:
            str: The local file URL (same for all page numbers)
        """
        # Always return the same URL since we only have one page
        return base_url

    async def detect_end_of_results(self, crawler: AsyncWebCrawler, url: str, session_id: str) -> bool:
        """
        Detect if we've reached the end of results.

        For local test file, we always return False on the first check
        since we want to process the single page.

        Args:
            crawler: The web crawler instance
            url: The URL to check
            session_id: Session identifier

        Returns:
            bool: Always False (let the scraper process the page once)
        """
        # For a single-page test file, we never need to stop early
        # The pagination logic will handle stopping after page 1
        return False

    def get_site_info(self) -> dict:
        """Get detailed information about this site profile."""
        info = super().get_site_info()
        info.update({
            "test_grants": [
                "5 grants designed to PASS (relevant, nonprofit, children in Africa, digital gap)",
                "5 grants designed to FAIL (competition, for-profit, wrong geography, expired deadline, wrong focus)",
            ],
            "pagination_format": "None (single page)",
            "end_detection_method": "Always returns False (single page test)",
            "expected_results": "Exactly 5 grants should be saved to output file",
        })
        return info
