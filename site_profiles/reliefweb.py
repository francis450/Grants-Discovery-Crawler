"""
Site profile for ReliefWeb (reliefweb.int).

ReliefWeb is a humanitarian information service provided by the UN Office
for the Coordination of Humanitarian Affairs (OCHA). Their jobs/training section
and reports often list funding opportunities from UN agencies, INGOs, and governments.
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class ReliefWebProfile(BaseSiteProfile):
    """
    Profile for crawling ReliefWeb funding/training opportunities.

    Site characteristics:
    - URL structure: Search pages with filters for type, country, theme
    - Pagination: Query-based (page parameter in URL)
    - CSS selector: Article/result listing items
    - End detection: No results or empty listing
    """

    # Site metadata
    site_name = "ReliefWeb"
    site_url = "https://reliefweb.int"
    description = "UN humanitarian information with funding and training opportunities"

    # Scraping configuration — target training/funding opportunities in Africa
    base_urls = [
        # Training opportunities in Kenya (education/capacity building)
        "https://reliefweb.int/training?search=education+technology&country=Kenya",
        # Training in Africa - digital/technology focus
        "https://reliefweb.int/training?search=digital+literacy&region=Eastern+Africa",
        # Funding reports/opportunities for Africa
        "https://reliefweb.int/updates?search=grant+funding+education&country=Kenya&type=Funding",
    ]

    css_selector = "article.rw-river-article, div.search-result, li.article-item"
    pagination_type = "query"  # Uses &page=N

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        ReliefWeb uses query-based pagination.

        Args:
            base_url: The search URL with filters
            page_number: Page number (1-indexed)

        Returns:
            str: Full URL for the specified page
        """
        if page_number == 1:
            return base_url
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}page={page_number - 1}"  # ReliefWeb is 0-indexed

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
                if "no results" in html.lower():
                    return True
                if "0 results" in html.lower():
                    return True
                if "nothing to show" in html.lower():
                    return True
                if len(html.strip()) < 300:
                    return True
            else:
                print(f"Error fetching ReliefWeb page: {result.error_message}")
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
                "Training - Education Technology (Kenya)",
                "Training - Digital Literacy (Eastern Africa)",
                "Funding Reports - Education (Kenya)",
            ],
            "pagination_format": "?page={N} (0-indexed)",
            "end_detection_method": "Text search for 'no results' or empty content",
        })
        return info
