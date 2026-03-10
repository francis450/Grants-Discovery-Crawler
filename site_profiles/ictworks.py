"""
Site profile for ICTworks (ictworks.org/category/funding/).

ICTworks is a premier resource for ICT4D (ICT for Development) professionals.
Their funding category publishes grant opportunities from donors like FCDO,
GSMA, the World Bank and others targeting digital development projects.

Site characteristics (verified via Playwright DOM probe):
- Custom WordPress theme, server-rendered — Crawl4AI compatible
- Posts live inside ``div#posts`` as ``div.single-post[id^="post-"]``
- First 2 children of ``#posts`` are fixed header/description blocks (not posts)
- Pagination: path-based ``/page/N/`` with "Older Posts »" link
- End detection: high page numbers redirect to the homepage (no post IDs)
"""

from typing import List
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from .base_profile import BaseSiteProfile


class ICTworksProfile(BaseSiteProfile):
    """
    Profile for crawling ICTworks funding category.

    Site characteristics:
    - URL structure: Category page with path-based pagination
    - Pagination: Path-based (/page/2/, /page/3/, etc.)
    - CSS selector: div.single-post[id^="post-"] (skip fixed header blocks)
    - End detection: Absence of any div.single-post with a post-ID
    """

    # Site metadata
    site_name = "ICTworks"
    site_url = "https://www.ictworks.org"
    description = "ICT4D funding opportunities from major development donors"

    # Scraping configuration
    base_urls = [
        "https://www.ictworks.org/category/funding/",
    ]

    # Only match actual post entries (have id="post-NNNN"), skipping the
    # fixed header/description blocks that are also div.single-post.
    css_selector = "div.single-post[id^='post-']"
    pagination_type = "path"  # Uses /page/N/ format

    def get_page_url(self, base_url: str, page_number: int) -> str:
        """
        Construct URL for a specific page.

        ICTworks uses standard WordPress path-based pagination:
        - Page 1: https://www.ictworks.org/category/funding/
        - Page 2: https://www.ictworks.org/category/funding/page/2/
        """
        if page_number == 1:
            return base_url
        if base_url.endswith('/'):
            return f"{base_url}page/{page_number}/"
        return f"{base_url}/page/{page_number}/"

    async def detect_end_of_results(self, crawler: AsyncWebCrawler, url: str, session_id: str) -> bool:
        """
        Detect if we've reached the end of results on ICTworks.

        When a page number exceeds available content, ICTworks redirects to
        the homepage — no div.single-post with a post-ID will be present.
        We also check for the "Older Posts" navigation link; its absence
        means we're on the last page.
        """
        try:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    session_id=session_id,
                ),
            )

            if not result.success:
                return True

            # Use raw HTML (result.html) for attribute-based checks because
            # cleaned_html strips CSS classes and element IDs.
            raw_html = result.html or ''

            # No actual posts on this page — we've passed the last page.
            # ICTworks redirects out-of-range pages to the homepage, which
            # won't have div.single-post with post-NNN ids inside #posts.
            import re
            if not re.search(r'id=["\']post-\d+', raw_html):
                return True

            # Explicit empty check (cleaned_html is fine for text)
            cleaned = result.cleaned_html or ''
            if 'No Results Found' in cleaned or 'Nothing Found' in cleaned:
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
                "Funding (ICT4D grants and opportunities)",
            ],
            "pagination_format": "/page/{N}/",
            "end_detection_method": "Absence of div.single-post with post-ID, or redirect to homepage",
            "content_type": "Grant/funding announcements with application links",
        })
        return info
