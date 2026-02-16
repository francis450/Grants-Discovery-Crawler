"""
Site profile for Funds for NGOs (fundsforngos.org).

This profile implements the crawling logic specific to the fundsforngos.org website,
including its URL structure, pagination format, and end-of-results detection.
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class FundsForNGOsProfile(BaseSiteProfile):
    """
    Profile for crawling Funds for NGOs website.

    Site characteristics:
    - URL structure: Category and tag pages
    - Pagination: Path-based (/page/2/, /page/3/, etc.)
    - CSS selector: article.post, article.entry
    - End detection: "No Results Found" text in HTML
    """

    # Site metadata
    site_name = "Funds for NGOs"
    site_url = "https://www2.fundsforngos.org"
    description = "Comprehensive database of funding opportunities for NGOs worldwide"

    # Scraping configuration
    base_urls = [
        "https://www2.fundsforngos.org/category/children/",
        "https://www2.fundsforngos.org/category/education/",
        "https://www2.fundsforngos.org/tag/funding-opportunities-and-resources-in-kenya/",
        "https://www2.fundsforngos.org/category/information-technology/",
        "https://www2.fundsforngos.org/category/science-and-technology/",
        "https://www2.fundsforngos.org/category/youth-adolescents/",
        # Companies-focused URLs (some allow nonprofits/social enterprises):
        "https://fundsforcompanies.fundsforngos.org/area/latest-grants-and-resources-for-education/",
        "https://fundsforcompanies.fundsforngos.org/area/latest-grants-and-resources-for-environment-and-conservation-and-climate-change/",
        "https://fundsforcompanies.fundsforngos.org/area/latest-grants-and-resources-for-information-technology-for-development/",
    ]

    css_selector = "article.post, article.entry"
    pagination_type = "path"  # Uses /page/N/ format

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        FundsForNGOs uses path-based pagination:
        - Page 1: https://www2.fundsforngos.org/category/children/
        - Page 2: https://www2.fundsforngos.org/category/children/page/2/
        - Page 3: https://www2.fundsforngos.org/category/children/page/3/

        Args:
            base_url: The category or tag URL
            page_number: Page number (1-indexed)

        Returns:
            str: Full URL for the specified page
        """
        if page_number == 1:
            return base_url
        return f"{base_url}/page/{page_number}/" if not base_url.endswith('/') else f"{base_url}page/{page_number}/"

    async def detect_end_of_results(self, crawler: AsyncWebCrawler, url: str, session_id: str) -> bool:
        """
        Detect if we've reached the end of results.

        FundsForNGOs displays a "No Results Found" message when there are no more grants.

        Args:
            crawler: The web crawler instance
            url: The URL to check
            session_id: Session identifier

        Returns:
            bool: True if "No Results Found" message is found, False otherwise
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
                "Children",
                "Education",
                "Kenya (geographic focus)",
                "Information Technology",
                "Science and Technology",
                "Youth and Adolescents",
            ],
            "pagination_format": "/page/{N}/",
            "end_detection_method": "Text search for 'No Results Found'",
        })
        return info
