"""Check actual link URLs on ICTworks listing page."""
import asyncio, re
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://www.ictworks.org/category/funding/",
            config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                css_selector="div.single-post[id^='post-']",
            ),
        )
        if result.success:
            html = result.html or ""
            # Extract links from posts
            posts = re.findall(r'<div[^>]+class="single-post"[^>]+id="post-\d+"[^>]*>(.*?)</div>\s*(?=<div|$)', html, re.DOTALL)
            print(f"Found {len(posts)} posts")
            for i, post in enumerate(posts[:5]):
                links = re.findall(r'href="(https://www\.ictworks\.org/[^"]+)"', post)
                title = re.findall(r'<h2[^>]*>(.*?)</h2>', post, re.DOTALL)
                title_text = re.sub(r'<[^>]+>', '', title[0]).strip() if title else "NO TITLE"
                print(f"\nPost {i+1}: {title_text[:80]}")
                print(f"  Links: {links[:3]}")

asyncio.run(main())
