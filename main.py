import asyncio
import sys
import argparse
from typing import List, Optional
from datetime import datetime

from crawl4ai import AsyncWebCrawler
from playwright.async_api import async_playwright
from dotenv import load_dotenv

from config import ENABLED_SITES, REQUIRED_KEYS, MAX_PAGES, MIN_RELEVANCE_SCORE, EARLY_STOP_ON_ALL_DUPLICATES, MAX_POSTING_AGE_DAYS
from site_profiles import get_profiles_by_names, AVAILABLE_PROFILES
from site_profiles.base_api_profile import BaseAPIProfile
from site_profiles.base_playwright_profile import BasePlaywrightProfile
from utils.playwright_utils import create_stealth_context
from utils.data_utils import (
    save_grants_to_csv,
    save_grants_to_json,
    is_how_it_helps_valid,
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
    is_deadline_valid,
    is_posting_fresh,
)
from utils.xai_utils import analyze_grant_relevance_xai
from utils.logging_utils import setup_logger, logger
from utils.site_tracker import RunTracker

load_dotenv()


def normalize_analysis(analysis: dict) -> dict:
    """
    Normalize LLM relevance-analysis field names to match the Grant model/DB schema.
    The LLM returns: score, reasoning, is_relevant, how_it_helps, matching_themes
    The Grant model expects: relevance_score, relevance_reasoning, ...
    """
    if not analysis:
        return analysis
    out = dict(analysis)  # shallow copy
    # Map score → relevance_score
    if "score" in out and "relevance_score" not in out:
        out["relevance_score"] = int(out.pop("score", 0))
    # Map reasoning → relevance_reasoning
    if "reasoning" in out and "relevance_reasoning" not in out:
        out["relevance_reasoning"] = out.pop("reasoning", "")
    # is_relevant is used for filtering only — keep it but don't persist
    return out


async def crawl_grants(sites_to_run: Optional[List[str]] = None, only_api: bool = False):
    """
    Main function to crawl grant data from multiple grant websites.
    
    Args:
        sites_to_run: Optional list of site names to run. If None, uses ENABLED_SITES from config.
        only_api: If True, only runs API-based profiles regardless of sites_to_run list.
    """
    # Initialize logger
    setup_logger(name="grant_crawler")
    
    # Initialize site performance tracker
    tracker = RunTracker()

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
    logger.info(f"Database: {db_total_before} grants from previous runs")

    # Initialize state variables (shared across all sites and URLs)
    all_grants = []
    new_grants_this_run = []  # Track grants added in this run (for Excel export)
    seen_titles = set()  # Track duplicates within this run
    # Pre-load titles from DB for in-memory fast dedup
    seen_titles.update(db_existing_titles)

    # Determine which sites to verify
    site_names = sites_to_run if sites_to_run else ENABLED_SITES
    
    # Load enabled site profiles
    try:
        site_profiles = get_profiles_by_names(site_names)
    except ValueError as e:
        logger.error(f"Error loading site profiles: {e}")
        return

    # Filter for only_api flag if set
    if only_api:
        original_count = len(site_profiles)
        site_profiles = [p for p in site_profiles if isinstance(p, BaseAPIProfile)]
        logger.info(f"Filtering for API-only profiles: {len(site_profiles)}/{original_count} kept")
        if not site_profiles:
            logger.warning("No API profiles found in the selected sites.")
            return

    # Display crawl configuration
    logger.info(f"{'='*80}")
    logger.info(f"GRANT CRAWLER - Multi-Site Configuration")
    logger.info(f"{'='*80}")
    logger.info(f"Enabled sites: {len(site_profiles)}")
    for profile in site_profiles:
        if isinstance(profile, BaseAPIProfile):
            logger.info(f"  - {profile.site_name} (API)")
        elif isinstance(profile, BasePlaywrightProfile):
            logger.info(f"  - {profile.site_name} (Playwright)")
        else:
            logger.info(f"  - {profile.site_name}: {len(profile.get_base_urls())} URLs")
    logger.info(f"{'='*80}\n")

    api_profiles = [p for p in site_profiles if isinstance(p, BaseAPIProfile)]
    playwright_profiles = [p for p in site_profiles if isinstance(p, BasePlaywrightProfile)]
    scraper_profiles = [p for p in site_profiles if not isinstance(p, BaseAPIProfile) and not isinstance(p, BasePlaywrightProfile)]

    # 1. Process API Profiles
    for api_profile in api_profiles:
        st = tracker.site(api_profile.site_name, profile_type="api")
        st.start()
        logger.info(f"{'='*80}")
        logger.info(f"API: {api_profile.site_name}")
        logger.info(f"{'='*80}")
        
        try:
            # Fetch grants using API logic
            fetched_grants = await api_profile.fetch_grants()
            st.record_fetched(len(fetched_grants))
            logger.info(f"Fetched {len(fetched_grants)} potential grants from {api_profile.site_name}")

            # Map internal profile stats to tracker if available
            if hasattr(api_profile, '_last_stats'):
                ps = api_profile._last_stats
                st.record_filtered("duplicate_in_db", ps.get("deduped", 0))
                st.record_filtered("prefilter_keywords", ps.get("filtered_prefilter", 0) + ps.get("filtered", 0))
                st.record_filtered("deadline_expired", ps.get("filtered_deadline", 0))
                if ps.get("fetch_failed", 0):
                    st.record_filtered("other", ps["fetch_failed"])
                # Override fetched with total_hits (pre-dedup count)
                if ps.get("total_hits", 0) > 0:
                    st.grants_fetched = ps["total_hits"]
            
            for grant in fetched_grants:
                # Check for duplicates
                if grant_exists(grant.get("title"), grant.get("application_url"), db_existing_titles, db_existing_urls):
                    logger.debug(f"Duplicate found: {grant.get('title')}")
                    st.record_filtered("duplicate_in_db")
                    continue
                
                # Analyze relevance using xAI (with retry on transient failures)
                logger.info(f"Analyzing: {grant.get('title')}...")
                st.record_sent_to_scoring()
                analysis = None
                for attempt in range(3):
                    try:
                        analysis = await analyze_grant_relevance_xai(grant)
                        break
                    except Exception as api_err:
                        logger.warning(f"xAI attempt {attempt+1}/3 failed: {api_err}")
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
                if analysis:
                    analysis = normalize_analysis(analysis)
                    grant.update(analysis)
                    
                    # Check Score
                    score = grant.get("relevance_score", 0)
                    hih = grant.get("how_it_helps", "")
                    
                    if score >= MIN_RELEVANCE_SCORE:
                        # Reject if LLM admits the grant doesn't help the mission
                        if not is_how_it_helps_valid(hih):
                            logger.info(f"🚫 Skipping ({score}): how_it_helps='Not applicable' — {grant.get('title')}")
                            st.record_scored(grant.get("title", ""), score, hih, accepted=False, reason_rejected="how_it_helps_invalid")
                            continue

                        # Safety-net deadline check
                        dl = grant.get("deadline", "")
                        if dl and not is_deadline_valid(dl):
                            logger.info(f"⏰ Skipping ({score}): deadline '{dl}' past/too soon — {grant.get('title')}")
                            st.record_scored(grant.get("title", ""), score, hih, accepted=False, reason_rejected="deadline_expired")
                            continue

                        # Stale posting check: no deadline + posted too long ago
                        if not dl and not is_posting_fresh(grant.get("date_posted")):
                            logger.info(f"⏰ Skipping ({score}): no deadline, posted {grant.get('date_posted')} (>{MAX_POSTING_AGE_DAYS}d ago) — {grant.get('title')}")
                            st.record_scored(grant.get("title", ""), score, hih, accepted=False, reason_rejected="stale_posting")
                            continue

                        logger.info(f"✅ RELEVANT ({score}): {grant.get('title')}")
                        st.record_scored(grant.get("title", ""), score, hih, accepted=True)
                        insert_grant(grant, run_id)
                        new_grants_this_run.append(grant)
                        all_grants.append(grant)
                        
                        # Update specific sets
                        if grant.get("title"): db_existing_titles.add(grant["title"])
                        if grant.get("application_url"): db_existing_urls.add(grant["application_url"])
                    else:
                        logger.info(f"❌ Low Score ({score}): {grant.get('title')}")
                        st.record_scored(grant.get("title", ""), score, hih, accepted=False, reason_rejected="low_score")
                else:
                    logger.warning(f"Could not analyze relevance for {grant.get('title')}")
                    st.record_filtered("analysis_failed")

        except Exception as e:
            logger.error(f"Error processing API {api_profile.site_name}: {e}")
            st.record_error("fetch_grants", str(e))
        finally:
            st.finish()

    # 2. Process Playwright Profiles (JS-heavy / anti-bot sites)
    if playwright_profiles:
        logger.info(f"{'='*80}")
        logger.info(f"PLAYWRIGHT PROFILES ({len(playwright_profiles)} sites)")
        logger.info(f"{'='*80}")

        try:
            async with async_playwright() as pw:
                browser, context = await create_stealth_context(pw)
                try:
                    for pw_profile in playwright_profiles:
                        st = tracker.site(pw_profile.site_name, profile_type="playwright")
                        st.start()
                        logger.info(f"{'='*80}")
                        logger.info(f"SITE [Playwright]: {pw_profile.site_name}")
                        logger.info(f"{'='*80}")

                        # Relevance analyzer — uses xAI Grok for all scoring
                        async def _relevance_analyzer(grant_data):
                            return await analyze_grant_relevance_xai(grant_data)

                        try:
                            grants = await pw_profile.run(
                                context=context,
                                llm_strategy=llm_strategy,
                                required_keys=REQUIRED_KEYS,
                                seen_titles=seen_titles,
                                relevance_analyzer=_relevance_analyzer,
                            )
                        except Exception as pw_err:
                            logger.error(f"Playwright run error for {pw_profile.site_name}: {pw_err}")
                            st.record_error("run", str(pw_err))
                            st.finish()
                            continue

                        st.record_fetched(len(grants) if grants else 0)

                        if grants:
                            for grant in grants:
                                # Score gate — Playwright profiles may return grants
                                # that passed the profile's own threshold but we
                                # double-check here for safety.
                                score = grant.get("relevance_score", grant.get("score", 0)) or 0
                                hih = grant.get("how_it_helps", "")
                                title = grant.get("title", "")

                                if score < MIN_RELEVANCE_SCORE:
                                    logger.debug(f"Skipping '{title}': score {score} below {MIN_RELEVANCE_SCORE}.")
                                    st.record_scored(title, score, hih, accepted=False, reason_rejected="low_score")
                                    continue

                                # Reject if LLM admits the grant doesn't help
                                if not is_how_it_helps_valid(hih):
                                    logger.info(f"🚫 Skipping: how_it_helps='Not applicable' — {title}")
                                    st.record_scored(title, score, hih, accepted=False, reason_rejected="how_it_helps_invalid")
                                    continue

                                # Safety-net deadline check
                                dl = grant.get("deadline", "")
                                if dl and not is_deadline_valid(dl):
                                    logger.debug(f"Skipping '{title}': deadline '{dl}' past/too soon.")
                                    st.record_scored(title, score, hih, accepted=False, reason_rejected="deadline_expired")
                                    continue

                                # Stale posting check: no deadline + posted too long ago
                                if not dl and not is_posting_fresh(grant.get("date_posted")):
                                    logger.info(f"⏰ Skipping '{title}': no deadline, posted {grant.get('date_posted')} (>{MAX_POSTING_AGE_DAYS}d ago).")
                                    st.record_scored(title, score, hih, accepted=False, reason_rejected="stale_posting")
                                    continue

                                if grant_exists(
                                    grant.get("title"),
                                    grant.get("application_url"),
                                    db_existing_titles,
                                    db_existing_urls,
                                ):
                                    st.record_existing()
                                    continue

                                st.record_scored(title, score, hih, accepted=True)
                                insert_grant(grant, run_id)
                                new_grants_this_run.append(grant)
                                all_grants.append(grant)
                                if grant.get("title"):
                                    db_existing_titles.add(grant["title"])
                                if grant.get("application_url"):
                                    db_existing_urls.add(grant["application_url"])

                            # Save progress incrementally
                            save_grants_to_csv(all_grants, "grants_output.csv")
                            save_grants_to_json(all_grants, "grants_output.json")
                            logger.info(f"Progress saved. Total grants: {len(all_grants)}")

                        st.finish()
                        logger.info(f"Completed Playwright site: {pw_profile.site_name}")
                        logger.info(f"Total grants collected so far: {len(all_grants)}\n")

                finally:
                    await context.close()
                    await browser.close()

        except Exception as e:
            logger.exception(f"Playwright processing error: {e}")

    # 3. Process Scraper Profiles (Crawl4AI browser-based)
    if scraper_profiles:
        try:
            # Start the web crawler context
            # https://docs.crawl4ai.com/api/async-webcrawler/#asyncwebcrawler
            async with AsyncWebCrawler(config=browser_config) as crawler:
                # Iterate through all site profiles
                for site_profile in scraper_profiles:
                    st = tracker.site(site_profile.site_name, profile_type="scraper")
                    st.start()
                    logger.info(f"{'='*80}")
                    logger.info(f"SITE: {site_profile.site_name}")
                    logger.info(f"{'='*80}")

                    # Get all base URLs for this site
                    base_urls = site_profile.get_base_urls()

                    # Iterate through all URLs for this site
                    for url_index, base_url in enumerate(base_urls, 1):
                        logger.info(f"{'='*80}")
                        logger.info(f"Starting crawl for URL {url_index}/{len(base_urls)}: {base_url}")
                        logger.info(f"{'='*80}\n")

                        page_number = 1

                        while page_number <= MAX_PAGES:
                            # Fetch and process data from the current page
                            grants, no_results_found, grants_found_on_page, all_were_duplicates = await fetch_and_process_page(
                                crawler,
                                page_number,
                                base_url,
                                site_profile,
                                llm_strategy,
                                session_id,
                                REQUIRED_KEYS,
                                seen_titles,
                                site_metrics=st,
                            )

                            if grants_found_on_page:
                                st.record_page(success=True)
                            elif not no_results_found:
                                st.record_page(success=False)

                            # Stop if we've reached the end of results
                            if no_results_found:
                                logger.info(f"No more grants found for {base_url}. Moving to next URL.")
                                break

                            # Stop if no grants were found on the page at all
                            if not grants_found_on_page:
                                logger.info(f"No grants found on page {page_number} of {base_url}.")
                                break

                            # Early stop: entire page was already-known grants — deeper pages will be too
                            if all_were_duplicates and EARLY_STOP_ON_ALL_DUPLICATES:
                                logger.info(
                                    f"Early stop: all grants on page {page_number} of {base_url} "
                                    f"already in database. Skipping remaining pages."
                                )
                                break

                            # If grants were found but all filtered out, continue to next page
                            if not grants:
                                logger.info(f"All grants on page {page_number} were filtered out. Continuing to next page...")
                                page_number += 1
                                await asyncio.sleep(2)
                                continue

                            # Add the grants from this page to the total list
                            all_grants.extend(grants)

                            # Insert new grants into database
                            for grant in grants:
                                if grant_exists(
                                    grant.get("title"),
                                    grant.get("application_url"),
                                    db_existing_titles,
                                    db_existing_urls,
                                ):
                                    st.record_existing()
                                else:
                                    insert_grant(grant, run_id)
                                    new_grants_this_run.append(grant)
                                    if grant.get("title"):
                                        db_existing_titles.add(grant["title"])
                                    if grant.get("application_url"):
                                        db_existing_urls.add(grant["application_url"])

                            # Save progress incrementally
                            save_grants_to_csv(all_grants, "grants_output.csv")
                            save_grants_to_json(all_grants, "grants_output.json")
                            logger.info(f"Progress saved. Total grants: {len(all_grants)}")

                            page_number += 1
                            await asyncio.sleep(2)

                        # Check if we hit the page limit
                        if page_number > MAX_PAGES:
                            logger.warning(f"Reached maximum page limit ({MAX_PAGES}) for {base_url}.")

                        logger.info(f"\nCompleted crawl for: {base_url}")
                        logger.info(f"Total grants collected so far: {len(all_grants)}\n")

                    st.finish()
                    logger.info(f"\nCompleted site: {site_profile.site_name}")
                    logger.info(f"Total grants collected so far: {len(all_grants)}\n")

        except KeyboardInterrupt:
            logger.warning("\n\nCrawl interrupted by user. Saving collected data...")
        except Exception as e:
            logger.exception(f"\n\nAn unexpected error occurred: {e}")
            logger.info("Saving collected data...")

    # Save the collected grants to files
    if all_grants:
        save_grants_to_csv(all_grants, "grants_output.csv")
        save_grants_to_json(all_grants, "grants_output.json")
        logger.info(f"\nTotal: Saved {len(all_grants)} grants to 'grants_output.csv' and 'grants_output.json'.")
    else:
        logger.info("No grants were found during the crawl.")

    # Export new grants to shared Excel file (OneDrive sync)
    if new_grants_this_run:
        logger.info(f"\n{'='*80}")
        logger.info(f"EXCEL EXPORT")
        logger.info(f"{'='*80}")
        try:
            appended = append_grants_to_excel(new_grants_this_run)
            if appended > 0:
                logger.info(f"Exported {appended} new grants to shared Excel file.")
        except Exception as e:
            logger.error(f"  ⚠ Excel export failed (non-fatal): {e}")

    # Summary
    db_total_after = get_grant_count()
    logger.info(f"\n{'='*80}")
    logger.info(f"RUN SUMMARY")
    logger.info(f"{'='*80}")
    logger.info(f"Grants found this run: {len(all_grants)}")
    logger.info(f"New grants added to DB: {len(new_grants_this_run)}")
    logger.info(f"Total grants in database: {db_total_after}")
    logger.info(f"{'='*80}\n")

    # Display usage statistics for the LLM strategy
    llm_strategy.show_usage()

    # ── Site Performance Report ──────────────────────────────────────
    tracker.print_report()
    tracker.save_report()
    tracker.save_csv_summary()


async def main():
    """
    Entry point of the script.
    """
    parser = argparse.ArgumentParser(description="Grant Crawler with API support")
    parser.add_argument("--sites", nargs="+", help="Specific sites to run (e.g. grants_gov fundsforngos)")
    parser.add_argument("--api-only", action="store_true", help="Only run API-based profiles")
    parser.add_argument("--list", action="store_true", help="List available site profiles")
    
    args = parser.parse_args()

    if args.list:
        print("\nAvailable Site Profiles:")
        for name in AVAILABLE_PROFILES.keys():
            print(f" - {name}")
        return

    # If --api-only is set, default to all API-capable sites if no specific sites are provided
    # However, currently get_profiles_by_names needs explicit names.
    # So if api-only is set but no sites provided, we still use ENABLED_SITES first, then filter.
    
    await crawl_grants(sites_to_run=args.sites, only_api=args.api_only)


if __name__ == "__main__":
    asyncio.run(main())
