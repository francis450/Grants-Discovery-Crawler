"""
Base profile for grant websites.

This module defines the abstract base class that all site-specific profiles must implement.
Each profile encapsulates the unique characteristics of a grant website.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from crawl4ai import CrawlerRunConfig


class BaseSiteProfile(ABC):
    """
    Abstract base class for grant website profiles.

    Each grant website has unique characteristics (URL structure, pagination format,
    CSS selectors, etc.). Site profiles encapsulate these differences, making it
    easy to add support for new grant websites.
    """

    # Site metadata (must be defined by subclasses)
    site_name: str = "Unknown"
    site_url: str = ""
    description: str = ""

    # Scraping configuration
    base_urls: List[str] = []
    css_selector: str = ""
    pagination_type: str = "none"  # "path", "query", "none"

    @abstractmethod
    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct the URL for a specific page number.

        Args:
            base_url: The base URL to paginate from
            page_number: The page number (1-indexed)

        Returns:
            str: The full URL for the specified page

        Example:
            For fundsforngos.org:
            - Page 1: https://www2.fundsforngos.org/category/children/
            - Page 2: https://www2.fundsforngos.org/category/children/page/2/
        """
        pass

    @abstractmethod
    async def detect_end_of_results(self, crawler, url: str, session_id: str) -> bool:
        """
        Detect if we've reached the end of pagination.

        Different sites indicate "no more results" differently:
        - Some show a "No Results Found" message
        - Some return a 404 error
        - Some return an empty results list
        - Some disable the "Next" button

        Args:
            crawler: The AsyncWebCrawler instance
            url: The URL to check
            session_id: The crawl session ID

        Returns:
            bool: True if no more results are available, False otherwise
        """
        pass

    def get_css_selector(self) -> str:
        """
        Get the CSS selector for grant elements on listing pages.

        Returns:
            str: CSS selector to target grant containers
        """
        return self.css_selector

    def get_base_urls(self) -> List[str]:
        """
        Get the list of base URLs to crawl for this site.

        Returns:
            List[str]: List of URLs to crawl
        """
        return self.base_urls

    def supports_pagination(self) -> bool:
        """
        Check if this site supports pagination.

        Returns:
            bool: True if the site has multiple pages, False otherwise
        """
        return self.pagination_type != "none"

    def get_site_info(self) -> dict:
        """
        Get information about this site profile.

        Returns:
            dict: Site metadata including name, URL, description, and URL count
        """
        return {
            "name": self.site_name,
            "url": self.site_url,
            "description": self.description,
            "base_urls_count": len(self.base_urls),
            "supports_pagination": self.supports_pagination(),
            "pagination_type": self.pagination_type,
        }

    def __str__(self) -> str:
        """String representation of the profile."""
        return f"{self.site_name} ({len(self.base_urls)} URLs)"

    def __repr__(self) -> str:
        """Developer representation of the profile."""
        return f"<{self.__class__.__name__}: {self.site_name}>"
