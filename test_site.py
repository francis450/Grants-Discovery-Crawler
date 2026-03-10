import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv

# Ensure the current directory is in the python path
sys.path.append(os.getcwd())

from config import REQUIRED_KEYS
from crawl4ai import AsyncWebCrawler
import site_profiles
from utils.scraper_utils import (
    fetch_and_process_page,
    get_browser_config,
    get_llm_strategy,
)
from utils.logging_utils import setup_logger, logger

# Load environment variables
load_dotenv()

# Configure logging
# logging.basicConfig(level=logging.INFO) # Removed in favor of setup_logger
# logger = logging.getLogger(__name__) # Removed in favor of setup_logger

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

async def main():
    parser = argparse.ArgumentParser(description="Test a specific site profile.")
    parser.add_argument("site_name", help="Name of the site profile to test (e.g., 'fundsforngos')")
    parser.add_argument("--limit", type=int, default=1, help="Max pages to crawl per base URL (default: 1)")
    parser.add_argument("--no-headless", action="store_true", help="Run browser visibly (not headless)")
    parser.add_argument("--save", action="store_true", help="Save results to JSON file")

    args = parser.parse_args()
    
    # Configure logger for this run
    # Note: setup_logger was already called on import. We can stick with the default or force new handlers.
    # For simplicity, we'll just log to the main log file.
    logger.info(f"Running test for site: {args.site_name}")

    # Determine headless state
    headless = not args.no_headless
    
    # Load the profile
    try:
        profile = site_profiles.get_profile(args.site_name)
    except Exception as e:
        logger.error(f"Error: Site profile '{args.site_name}' not found or failed to load. Details: {e}")
        if hasattr(site_profiles, 'AVAILABLE_PROFILES'):
            logger.info(f"Available profiles: {', '.join(site_profiles.AVAILABLE_PROFILES.keys())}")
        return

    logger.info(f"Starting test for site: {profile.site_name}")
    logger.info(f"Headless mode: {headless}")
    logger.info(f"Page limit: {args.limit}")

    # Initialize strategies and config
    llm_strategy = get_llm_strategy()
    browser_config = get_browser_config(headless=headless)
    
    all_results = []
    session_id = f"test_{args.site_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    logger.info(f"{'='*80}")
    logger.info(f"SITE: {profile.site_name}")
    logger.info(f"{'='*80}")

    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Iterate through valid base URLs
        base_urls = profile.get_base_urls()
        
        for base_url in base_urls:
            logger.info(f"Processing Base URL: {base_url}")
            
            # Using a set for seen_titles to simulate duplicate checking within the run
            seen_titles = set()

            for page_num in range(1, args.limit + 1):
                logger.info(f"  Fetching page {page_num}...")
                
                try:
                    # fetch_and_process_page returns (grants, no_results_found, grants_found_on_page)
                    grants, no_results_found, grants_found_on_page = await fetch_and_process_page(
                        crawler=crawler,
                        page_number=page_num,
                        base_url=base_url,
                        site_profile=profile,
                        llm_strategy=llm_strategy,
                        session_id=session_id,
                        required_keys=REQUIRED_KEYS,
                        seen_titles=seen_titles
                    )
                    
                    if grants:
                        logger.info(f"    Found {len(grants)} grants on page {page_num}.")
                        all_results.extend(grants)
                        # Update seen titles so we don't count duplicates if we encounter them again
                        for grant in grants:
                            if grant.get("title"):
                                seen_titles.add(grant["title"])
                    else:
                        logger.info(f"    No grants extracted from page {page_num}.")

                    if no_results_found:
                        logger.info("    [End of Results Detected by Profile]")
                        break
                        
                except Exception as e:
                    logger.error(f"    Error processing page {page_num}: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())

    # Output results
    logger.info("="*80)
    logger.info(f"TEST COMPLETE")
    logger.info(f"Total Grants Found: {len(all_results)}")
    logger.info("="*80)
    
    # Print to stdout for CLI usage (still useful to keep pure JSON output clean if possible)
    # But logging usually prints to stdout too.
    # We might want to just print the JSON at the end for the user.
    print(json.dumps(all_results, indent=2, default=json_serial))

    # Save to file if requested
    if args.save:
        filename = f"test_output_{args.site_name}.json"
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=2, default=json_serial, ensure_ascii=False)
            logger.info(f"Results saved to {filename}")
        except Exception as e:
            logger.error(f"Error saving to file: {e}")

if __name__ == "__main__":
    asyncio.run(main())
