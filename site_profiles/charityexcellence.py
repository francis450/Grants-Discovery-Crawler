"""
Site profile for Charity Excellence (charityexcellence.co.uk).

Charity Excellence provides a free funding finder for charities and NGOs.
Their international grants section is particularly relevant.
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class CharityExcellenceProfile(BaseSiteProfile):
    """
    Profile for crawling Charity Excellence funding finder.

    Site characteristics:
    - URL structure: Funding finder directory pages with category IDs
    - Pagination: Offset-based (/0, /20, /40, ...)
    - CSS selector: Funder listing items
    - End detection: Empty results or no funder items found
    """

    # Site metadata
    site_name = "Charity Excellence"
    site_url = "https://www.charityexcellence.co.uk"
    description = "Free funding finder for charities, including international grants"

    # Scraping configuration
    base_urls = [
        # International funders directory
        "https://www.charityexcellence.co.uk/FundingFinders/GrantFunders/FundersInternational/20",
        # Education funders
        "https://www.charityexcellence.co.uk/FundingFinders/GrantFunders/FundersEducation/20",
        # Technology/digital funders
        "https://www.charityexcellence.co.uk/FundingFinders/GrantFunders/FundersTechnology/20",
    ]

    css_selector = "div.funder-item, div.funding-item, tr.funder-row, div.card"
    pagination_type = "query"

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        Charity Excellence uses offset-based pagination in the URL path.
        Base URL ends with /20 (offset 20); each page shows ~20 items.

        Args:
            base_url: The funding finder URL
            page_number: Page number (1-indexed)

        Returns:
            str: Full URL for the specified page
        """
        if page_number == 1:
            return base_url
        base = base_url.rsplit("/", 1)[0]
        offset = (page_number - 1) * 20
        return f"{base}/{offset}"

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
                if "no funders found" in html.lower():
                    return True
                if "no results" in html.lower():
                    return True
                if len(html.strip()) < 200:
                    return True
            else:
                print(f"Error fetching Charity Excellence page: {result.error_message}")
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
                "International Funders",
                "Education Funders",
                "Technology Funders",
            ],
            "pagination_format": "Offset-based (/0, /20, /40, ...)",
            "end_detection_method": "Text search for 'no funders found' or empty results",
        })
        return info
