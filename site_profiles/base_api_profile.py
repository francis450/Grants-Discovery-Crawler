"""
Base profile for API-based grant sources.

This module defines the abstract base class that all API-based profiles must implement.
Unlike BaseSiteProfile, these do not require a browser crawler.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseAPIProfile(ABC):
    """
    Abstract base class for API-based grant providers.
    
    These profiles fetch data directly from APIs rather than scraping HTML,
    bypassing the need for Crawl4AI / Playwright.
    """

    # Site metadata
    site_name: str = "Unknown API"
    site_url: str = ""
    description: str = ""

    @abstractmethod
    async def fetch_grants(self) -> List[Dict[str, Any]]:
        """
        Orchestrates the API calls to search, filter, and retrieve grants.
        
        Returns:
            List[Dict[str, Any]]: A list of grant dictionaries conforming to the schema.
        """
        pass
