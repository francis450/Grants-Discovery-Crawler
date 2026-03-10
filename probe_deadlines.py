"""Check what content the LLM sees on an ICTworks grant page."""
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

async def main():
    urls = [
        "https://www.ictworks.org/seed-grants-for-african-startups/",
        "https://www.ictworks.org/funding-your-humanitarian-technology-innovation/",
    ]
    async with AsyncWebCrawler() as crawler:
        for url in urls:
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(cache_mode=CacheMode.BYPASS),
            )
            if result.success:
                html = result.html or ""
                # Search for deadline-related text
                import re
                lines = html.split("\n")
                print(f"\n{'='*60}")
                print(f"URL: {url}")
                print(f"HTML length: {len(html)}")
                
                # Look for deadline-related keywords
                deadline_kw = re.findall(
                    r'(?i).{0,80}(deadline|apply by|closes?|due date|submission|applications? close).{0,80}',
                    html
                )
                print(f"\nDeadline mentions ({len(deadline_kw)}):")
                for m in deadline_kw[:5]:
                    print(f"  {m.strip()[:150]}")
                
                # Look for date patterns like "March 15, 2025"
                dates = re.findall(
                    r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
                    html
                )
                print(f"\nDate mentions: {dates[:8]}")
                
                # Also look for "Posted on" or publication date
                posted = re.findall(r'(?i).{0,40}(posted|published|date|by\s).{0,60}', html[:3000])
                print(f"\nPost date mentions (first 3k): {[p.strip()[:100] for p in posted[:5]]}")
                
                # Print the main article content (look for it in the body)
                # Try to find the article text
                article_match = re.search(r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
                if article_match:
                    content = re.sub(r'<[^>]+>', ' ', article_match.group(1))
                    content = re.sub(r'\s+', ' ', content).strip()
                    print(f"\nArticle content ({len(content)} chars):")
                    print(content[:2000])
                else:
                    # fallback: look for post content
                    post_match = re.search(r'<div[^>]*id="post-\d+"[^>]*>(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL)
                    if post_match:
                        content = re.sub(r'<[^>]+>', ' ', post_match.group(1))
                        content = re.sub(r'\s+', ' ', content).strip()
                        print(f"\nPost content ({len(content)} chars):")
                        print(content[:2000])
                    else:
                        # Find text with dates
                        text = re.sub(r'<[^>]+>', ' ', html)
                        text = re.sub(r'\s+', ' ', text).strip()
                        # Find section around any month mention
                        month_matches = list(re.finditer(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', text))
                        print(f"\nMonth abbreviation mentions: {len(month_matches)}")
                        for m in month_matches[:5]:
                            start = max(0, m.start() - 50)
                            end = min(len(text), m.end() + 100)
                            print(f"  ...{text[start:end]}...")
                        
                        # Also print first 500 chars of visible text
                        print(f"\nFirst 500 chars of visible text:")
                        print(text[:500])

asyncio.run(main())
