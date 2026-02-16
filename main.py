import asyncio
from datetime import datetime

from crawl4ai import AsyncWebCrawler
from dotenv import load_dotenv

from config import ENABLED_SITES, REQUIRED_KEYS, MAX_PAGES
from site_profiles import get_profiles_by_names
from utils.data_utils import (
    save_grants_to_csv,
    save_grants_to_json,
)
from utils.db_utils import (
    init_db,
    load_existing_titles,
    load_existing_urls,
    grant_exists,
    insert_grant,
    get_grant_count,
)
from utils.excel_utils import append_grants_to_excel
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
    run_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Initialize database
    init_db()
    db_existing_titles = load_existing_titles()
    db_existing_urls = load_existing_urls()
    db_total_before = get_grant_count()
    print(f"Database: {db_total_before} grants from previous runs")

    # Initialize state variables (shared across all sites and URLs)
    all_grants = []
    new_grants_this_run = []  # Track grants added in this run (for Excel export)
    seen_titles = set()  # Track duplicates within this run
    # Pre-load titles from DB for in-memory fast dedup
    seen_titles.update(db_existing_titles)

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

                    while page_number <= MAX_PAGES:
                        # Fetch and process data from the current page
                        grants, no_results_found, grants_found_on_page = await fetch_and_process_page(
                            crawler,
                            page_number,
                            base_url,
                            site_profile,  # Pass the profile instead of CSS_SELECTOR
                            llm_strategy,
                            session_id,
                            REQUIRED_KEYS,
                            seen_titles,
                        )

                        # Stop if we've reached the end of results (site returned "No Results Found" or equivalent)
                        if no_results_found:
                            print(f"No more grants found for {base_url}. Moving to next URL.")
                            break

                        # Stop if no grants were found on the page at all (not even to filter)
                        if not grants_found_on_page:
                            print(f"No grants found on page {page_number} of {base_url}.")
                            break

                        # If grants were found but all filtered out, continue to next page
                        if not grants:
                            print(f"All grants on page {page_number} were filtered out. Continuing to next page...")
                            page_number += 1
                            await asyncio.sleep(2)
                            continue

                        # Add the grants from this page to the total list
                        all_grants.extend(grants)

                        # Insert new grants into database
                        for grant in grants:
                            if not grant_exists(
                                grant.get("title"),
                                grant.get("application_url"),
                                db_existing_titles,
                                db_existing_urls,
                            ):
                                insert_grant(grant, run_id)
                                new_grants_this_run.append(grant)
                                # Update in-memory sets for subsequent checks
                                if grant.get("title"):
                                    db_existing_titles.add(grant["title"])
                                if grant.get("application_url"):
                                    db_existing_urls.add(grant["application_url"])

                        # Save progress incrementally
                        save_grants_to_csv(all_grants, "grants_output.csv")
                        save_grants_to_json(all_grants, "grants_output.json")
                        print(f"Progress saved. Total grants: {len(all_grants)}")

                        page_number += 1  # Move to the next page

                        # Pause between requests to be polite and avoid rate limits
                        await asyncio.sleep(2)  # Adjust sleep time as needed

                    # Check if we hit the page limit
                    if page_number > MAX_PAGES:
                        print(f"Reached maximum page limit ({MAX_PAGES}) for {base_url}.")

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

    # Export new grants to shared Excel file (OneDrive sync)
    if new_grants_this_run:
        print(f"\n{'='*80}")
        print(f"EXCEL EXPORT")
        print(f"{'='*80}")
        try:
            appended = append_grants_to_excel(new_grants_this_run)
            if appended > 0:
                print(f"Exported {appended} new grants to shared Excel file.")
        except Exception as e:
            print(f"  ⚠ Excel export failed (non-fatal): {e}")

    # Summary
    db_total_after = get_grant_count()
    print(f"\n{'='*80}")
    print(f"RUN SUMMARY")
    print(f"{'='*80}")
    print(f"Grants found this run: {len(all_grants)}")
    print(f"New grants added to DB: {len(new_grants_this_run)}")
    print(f"Total grants in database: {db_total_after}")
    print(f"{'='*80}\n")

    # Display usage statistics for the LLM strategy
    llm_strategy.show_usage()


async def main():
    """
    Entry point of the script.
    """
    await crawl_grants()


if __name__ == "__main__":
    asyncio.run(main())
