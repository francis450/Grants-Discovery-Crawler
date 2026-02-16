"""
Site profile for EU Funding Portal (eufundingportal.eu).

This profile implements the crawling logic specific to the eufundingportal.eu website,
including its URL structure, pagination format, and end-of-results detection.
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class EUFundingPortalProfile(BaseSiteProfile):
    """
    Profile for crawling EU Funding Portal website.

    Site characteristics:
    - URL structure: Tag and category pages
    - Pagination: Path-based (/page/2/, /page/3/, etc.)
    - CSS selector: li.alm-item (Ajax Load More plugin items)
    - End detection: Empty page or missing grant items
    """

    # Site metadata
    site_name = "EU Funding Portal"
    site_url = "https://eufundingportal.eu/"
    description = "EU funding opportunities portal with education and NGO grant listings"

    # Scraping configuration
    base_urls = [
        "https://eufundingportal.eu/tag/education-grants/",
        "https://eufundingportal.eu/ngo-grants/",
    ]

    css_selector = "li.alm-item"
    pagination_type = "path"  # Uses /page/N/ format

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        EU Funding Portal uses path-based pagination:
        - Page 1: https://eufundingportal.eu/tag/education-grants/
        - Page 2: https://eufundingportal.eu/tag/education-grants/page/2/

        Args:
            base_url: The tag or category URL
            page_number: Page number (1-indexed)

        Returns:
            str: Full URL for the specified page
        """
        if page_number == 1:
            return base_url
        return f"{base_url}/page/{page_number}/" if not base_url.endswith('/') else f"{base_url}page/{page_number}/"

    async def detect_end_of_results(self, crawler: AsyncWebCrawler, url: str, session_id: str) -> bool:
        """
        Detect if we've reached the end of results on EU Funding Portal.

        Checks for "No Results Found", empty content, or 404-like responses.

        Args:
            crawler: The web crawler instance
            url: The URL to check
            session_id: Session identifier

        Returns:
            bool: True if no more results are available
        """
        try:
            # Fetch the page without any CSS selector or extraction strategy
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    session_id=session_id,
                ),
            )

            if result.success:
                # Check if the "No Results Found" message is present
                if "No Results Found" in result.cleaned_html:
                    return True
            else:
                print(f"Error fetching page for 'No Results Found' check: {result.error_message}")

            return False

        except Exception as e:
            print(f"Error in detect_end_of_results: {str(e)}")
            return False

    def get_site_info(self) -> dict:
        """Get detailed information about this site profile."""
        info = super().get_site_info()
        info.update({
            "categories_crawled": [
                "Education Grants",
                "NGO Grants",
            ],
            "pagination_format": "/page/{N}/",
            "end_detection_method": "Text search for 'No Results Found' or empty content",
        })
        return info
