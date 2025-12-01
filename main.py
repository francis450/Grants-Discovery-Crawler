import asyncio

from crawl4ai import AsyncWebCrawler
from dotenv import load_dotenv

from config import ENABLED_SITES, REQUIRED_KEYS
from site_profiles import get_profiles_by_names
from utils.data_utils import (
    save_grants_to_csv,
    save_grants_to_json,
)
from utils.scraper_utils import (
    fetch_and_process_page,
    get_browser_config,
    get_llm_strategy,
)

load_dotenv()


async def crawl_grants():
    """
    Main function to crawl grant data from multiple grant websites.
    Uses site profiles to support different grant websites with varying structures.
    """
    # Initialize configurations
    browser_config = get_browser_config()
    llm_strategy = get_llm_strategy()
    session_id = "grant_crawl_session"

    # Initialize state variables (shared across all sites and URLs)
    all_grants = []
    seen_titles = set()  # Track duplicates across all sites

    # Load enabled site profiles
    try:
        site_profiles = get_profiles_by_names(ENABLED_SITES)
    except ValueError as e:
        print(f"Error loading site profiles: {e}")
        return

    # Display crawl configuration
    print(f"\n{'='*80}")
    print(f"GRANT CRAWLER - Multi-Site Configuration")
    print(f"{'='*80}")
    print(f"Enabled sites: {len(site_profiles)}")
    for profile in site_profiles:
        print(f"  - {profile.site_name}: {len(profile.get_base_urls())} URLs")
    print(f"{'='*80}\n")

    try:
        # Start the web crawler context
        # https://docs.crawl4ai.com/api/async-webcrawler/#asyncwebcrawler
        async with AsyncWebCrawler(config=browser_config) as crawler:
            # Iterate through all site profiles
            for site_profile in site_profiles:
                print(f"\n{'='*80}")
                print(f"SITE: {site_profile.site_name}")
                print(f"{'='*80}")

                # Get all base URLs for this site
                base_urls = site_profile.get_base_urls()

                # Iterate through all URLs for this site
                for url_index, base_url in enumerate(base_urls, 1):
                    print(f"\n{'='*80}")
                    print(f"Starting crawl for URL {url_index}/{len(base_urls)}: {base_url}")
                    print(f"{'='*80}\n")

                    page_number = 1

                    while True:
                        # Fetch and process data from the current page
                        grants, no_results_found = await fetch_and_process_page(
                            crawler,
                            page_number,
                            base_url,
                            site_profile,  # Pass the profile instead of CSS_SELECTOR
                            llm_strategy,
                            session_id,
                            REQUIRED_KEYS,
                            seen_titles,
                        )

                        if no_results_found:
                            print(f"No more grants found for {base_url}. Moving to next URL.")
                            break  # Stop crawling this URL when no more results

                        if not grants:
                            print(f"No grants extracted from page {page_number} of {base_url}.")
                            break  # Stop if no grants are extracted

                        # Add the grants from this page to the total list
                        all_grants.extend(grants)

                        # Save progress incrementally
                        save_grants_to_csv(all_grants, "grants_output.csv")
                        save_grants_to_json(all_grants, "grants_output.json")
                        print(f"Progress saved. Total grants: {len(all_grants)}")

                        page_number += 1  # Move to the next page

                        # Pause between requests to be polite and avoid rate limits
                        await asyncio.sleep(2)  # Adjust sleep time as needed

                    print(f"\nCompleted crawl for: {base_url}")
                    print(f"Total grants collected so far: {len(all_grants)}\n")

                print(f"\nCompleted site: {site_profile.site_name}")
                print(f"Total grants collected so far: {len(all_grants)}\n")

    except KeyboardInterrupt:
        print("\n\nCrawl interrupted by user. Saving collected data...")
    except Exception as e:
        print(f"\n\nAn unexpected error occurred: {e}")
        print("Saving collected data...")

    # Save the collected grants to files
    if all_grants:
        save_grants_to_csv(all_grants, "grants_output.csv")
        save_grants_to_json(all_grants, "grants_output.json")
        print(f"\nTotal: Saved {len(all_grants)} grants to 'grants_output.csv' and 'grants_output.json'.")
    else:
        print("No grants were found during the crawl.")

    # Display usage statistics for the LLM strategy
    llm_strategy.show_usage()


async def main():
    """
    Entry point of the script.
    """
    await crawl_grants()


if __name__ == "__main__":
    asyncio.run(main())
