"""
Site profile for GlobalGiving (globalgiving.org).

GlobalGiving connects nonprofits, donors, and companies in nearly every country.
Their projects page lists fundraising and grant opportunities relevant to education
and technology in developing countries.
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class GlobalGivingProfile(BaseSiteProfile):
    """
    Profile for crawling GlobalGiving project listings.

    Site characteristics:
    - URL structure: Search/browse pages with theme and country filters
    - Pagination: Query-based (?page=N) or nextPage parameter
    - CSS selector: Project card elements
    - End detection: No project cards found or "no results" message
    """

    # Site metadata
    site_name = "GlobalGiving"
    site_url = "https://www.globalgiving.org"
    description = "Global crowdfunding and grants platform for nonprofits"

    # Scraping configuration — filter by themes and regions relevant to the mission
    base_urls = [
        # Education projects in Africa
        "https://www.globalgiving.org/search/?size=25&nextPage=1&sortField=sortorder&selectedThemes=edu&selectedCountries=KE,TZ,UG,NG,GH,ZA,ET,RW,MW,SN",
        # Technology projects in Africa
        "https://www.globalgiving.org/search/?size=25&nextPage=1&sortField=sortorder&selectedThemes=tech&selectedCountries=KE,TZ,UG,NG,GH,ZA,ET,RW,MW,SN",
        # Children/youth projects in Africa
        "https://www.globalgiving.org/search/?size=25&nextPage=1&sortField=sortorder&selectedThemes=children&selectedCountries=KE,TZ,UG,NG,GH,ZA,ET,RW,MW,SN",
    ]

    css_selector = "div.project-card, div.search-result-item, article.project-listing"
    pagination_type = "query"  # Uses nextPage=N parameter

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        GlobalGiving uses nextPage query parameter for pagination.

        Args:
            base_url: The search URL with filters
            page_number: Page number (1-indexed)

        Returns:
            str: Full URL for the specified page
        """
        if page_number == 1:
            return base_url
        # Replace nextPage=1 with the correct page number
        if "nextPage=" in base_url:
            import re
            return re.sub(r"nextPage=\d+", f"nextPage={page_number}", base_url)
        return f"{base_url}&nextPage={page_number}"

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
                if "no projects found" in html.lower():
                    return True
                if "no results" in html.lower():
                    return True
                if "0 projects" in html.lower():
                    return True
                # Very short page likely means no content
                if len(html.strip()) < 300:
                    return True
            else:
                print(f"Error fetching GlobalGiving page: {result.error_message}")
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
                "Education (Africa)",
                "Technology (Africa)",
                "Children/Youth (Africa)",
            ],
            "target_countries": "KE, TZ, UG, NG, GH, ZA, ET, RW, MW, SN",
            "pagination_format": "?nextPage={N}",
            "end_detection_method": "Text search for 'no projects found' or empty results",
        })
        return info
