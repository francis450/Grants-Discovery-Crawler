"""
Site profile for DevEx Funding (devex.com/funding).

DevEx is a media platform for the global development community.
Their funding section lists grants, tenders, and RFPs from major
development organizations (USAID, World Bank, UN agencies, etc.).
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class DevExProfile(BaseSiteProfile):
    """
    Profile for crawling DevEx funding opportunities.

    Site characteristics:
    - URL structure: Funding search with sector/region filters
    - Pagination: Query-based (?page=N)
    - CSS selector: Funding listing items
    - End detection: No funding items or "no results" message
    """

    # Site metadata
    site_name = "DevEx Funding"
    site_url = "https://www.devex.com"
    description = "Development sector funding opportunities from major donors"

    # Scraping configuration
    base_urls = [
        # Education sector funding
        "https://www.devex.com/funding/search?query%5B%5D=education&query%5B%5D=technology",
        # Africa region funding
        "https://www.devex.com/funding/search?query%5B%5D=africa&query%5B%5D=education",
        # ICT / Digital development
        "https://www.devex.com/funding/search?query%5B%5D=digital+literacy&query%5B%5D=africa",
    ]

    css_selector = "div.funding-item, article.search-result, div.listing-item, div.result-card"
    pagination_type = "query"  # Uses ?page=N

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        DevEx uses query-based pagination.

        Args:
            base_url: The search URL with filters
            page_number: Page number (1-indexed)

        Returns:
            str: Full URL for the specified page
        """
        if page_number == 1:
            return base_url
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}page={page_number}"

    async def detect_end_of_results(self, crawler: AsyncWebCrawler, url: str, session_id: str) -> bool:
        """
        Detect if we've reached the end of results.

        Args:
            crawler: The web crawler instance
            url: The URL to check
            session_id: Session identifier

        Returns:
            bool: True if no more results are available
        """
        try:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    session_id=session_id,
                ),
            )

            if result.success:
                html = result.cleaned_html
                if "no results found" in html.lower():
                    return True
                if "no funding opportunities" in html.lower():
                    return True
                if "0 results" in html.lower():
                    return True
                if len(html.strip()) < 300:
                    return True
            else:
                print(f"Error fetching DevEx page: {result.error_message}")
                return True

            return False

        except Exception as e:
            print(f"Error in detect_end_of_results: {str(e)}")
            return False

    def get_site_info(self) -> dict:
        """Get detailed information about this site profile."""
        info = super().get_site_info()
        info.update({
            "categories_crawled": [
                "Education + Technology",
                "Africa + Education",
                "Digital Literacy + Africa",
            ],
            "pagination_format": "?page={N}",
            "end_detection_method": "Text search for 'no results found' or empty content",
        })
        return info
