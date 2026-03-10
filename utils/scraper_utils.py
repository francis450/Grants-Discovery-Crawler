import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

# Import xAI relevance analyzer (sole LLM provider)
from utils.xai_utils import analyze_grant_relevance_xai, XAI_AVAILABLE

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMExtractionStrategy,
)

from models.grant import Grant
from utils.data_utils import is_complete_grant, is_duplicate_grant, is_how_it_helps_valid
from config import MIN_DEADLINE_DAYS, MIN_RELEVANCE_SCORE, MAX_POSTING_AGE_DAYS
from utils.logging_utils import logger, MetricsLogger

# Initialize detailed metrics logger
metrics_logger = MetricsLogger()

async def analyze_grant_relevance_local(grant_data: dict) -> Optional[Dict]:
    """
    Analyze grant relevance using local Ollama LLM (llama3.1).
    
    Replaces the cloud-based analyze_grant_relevance() with a local call.
    Uses the already-extracted grant data (from Grok-3) for scoring.
    
    Args:
        grant_data: Dict containing title, description, thematic_areas, 
                    geographic_focus, eligibility_criteria from initial extraction.
    
    Returns:
        Dict with is_relevant, score, reasoning, how_it_helps, matching_themes
        or None if Ollama is unavailable/fails.
    """
    if not OLLAMA_AVAILABLE:
        print("  ⚠ Warning: ollama library not installed. Skipping local relevance analysis.")
        return None
    
    # Construct mission-aligned prompt using pre-extracted data
    prompt = f"""You are analyzing grant opportunities for a nonprofit organization.

ORGANIZATION MISSION:
Collect out-of-service IT equipment, refurbish/repurpose them, and provide them to children in schools in underserved areas of Africa (especially Kenya) to close the digital gap.

WHAT THE ORGANIZATION DOES:
1. Source discarded/donated computers, laptops, tablets from companies
2. Refurbish and repurpose devices (e-waste management, circular economy)
3. Distribute to schools in underserved/rural areas in Africa
4. Enable children to interact with technology
5. Promote digital literacy and technology education

ORGANIZATION STATUS:
We are a new organization, so we lack extensive credibility and a long track record.
Therefore, grants with stringent requirements (e.g., long operational history, large budgets, extensive prior funding) are less suitable.
Prioritize grants with simpler, more accessible application processes.

GRANT TO ANALYZE:
Title: {grant_data.get('title', 'N/A')}
Description: {grant_data.get('description', 'N/A')}
Thematic Areas: {grant_data.get('thematic_areas', [])}
Geographic Focus: {grant_data.get('geographic_focus', 'N/A')}
Eligibility: {grant_data.get('eligibility_criteria', 'N/A')}

MINIMUM REQUIREMENTS (at least 3 of 5 must be met for is_relevant=true):
1. Must accept NONPROFIT organizations (NGOs, CBOs, charities)
2. Must NOT be a competition, contest, award, or prize
3. Must focus on: children, youth, students, schools, or education
4. Must include: Africa, Sub-Saharan Africa, East Africa, Kenya, developing countries, Global South, worldwide, or international
5. Must relate to ONE of: digital literacy, IT equipment, technology education, e-waste/recycling, refurbished tech, digital divide, computer labs, STEM education, school infrastructure, education equipment/supplies, capacity building, climate action/green technology

SCORING GUIDE:
- 90-100: Perfect match (directly funds IT equipment for African schools)
- 75-89: Strong match (education + technology + Africa, with clear path to fund our work)
- 70-79: Good match (meets requirements with some adaptation needed, but a plausible path exists)
- 50-69: Weak match (tangentially related but no realistic path to fund our specific mission)
- Below 50: Not relevant (missing key requirements)

CRITICAL SCORING RULES:
- If the grant's geographic focus EXCLUDES Africa entirely (e.g. only EU, only US, only Western Balkans), score below 50.
- If the grant is purely research/academic with no operational funding for equipment or programs, score below 60.
- If you cannot write a specific, realistic plan in 'how_it_helps', you MUST set how_it_helps to 'Not applicable' AND score below 50.
- Do NOT inflate scores for grants that only loosely match keywords. The score must reflect whether this grant can REALISTICALLY fund collecting, refurbishing, or distributing IT equipment to African schools.

Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{{
  "is_relevant": true or false,
  "score": number 0-100,
  "reasoning": "Brief explanation of why this grant does or does not match the mission",
  "how_it_helps": "Specific, actionable explanation of how this grant could fund IT equipment acquisition or distribution to African schools. If not relevant, state 'Not applicable'",
  "matching_themes": ["list", "of", "matching", "themes"]
}}"""

    try:
        # Call local Ollama with JSON format enforcement
        response = ollama.generate(
            model='llama3.1',
            prompt=prompt,
            format='json',
            options={
                'temperature': 0.1,  # Low temperature for consistent scoring
                'num_predict': 500,  # Limit response length
            }
        )
        
        # Parse JSON response
        result = json.loads(response['response'])
        
        # Validate required fields exist
        required_fields = ['is_relevant', 'score', 'reasoning']
        for field in required_fields:
            if field not in result:
                print(f"  ⚠ Warning: Ollama response missing '{field}' field")
                return None
        
        # Ensure score is an integer
        result['score'] = int(result.get('score', 0))
        
        # Ensure matching_themes is a list
        if not isinstance(result.get('matching_themes'), list):
            result['matching_themes'] = []
        
        # Ensure how_it_helps exists
        if 'how_it_helps' not in result:
            result['how_it_helps'] = ''
        
        return result
        
    except ConnectionError:
        print("  ⚠ Warning: Cannot connect to Ollama service. Is it running? (ollama serve)")
        return None
    except json.JSONDecodeError as e:
        print(f"  ⚠ Warning: Failed to parse Ollama JSON response: {e}")
        return None
    except Exception as e:
        # Catch ollama-specific errors (service not running, model not found, etc.)
        error_msg = str(e).lower()
        if 'connection' in error_msg or 'refused' in error_msg:
            print("  ⚠ Warning: Ollama service not running. Start with 'ollama serve'")
        elif 'not found' in error_msg:
            print("  ⚠ Warning: Model 'llama3.1' not found. Run 'ollama pull llama3.1'")
        else:
            print(f"  ⚠ Warning: Ollama error: {e}")
        return None


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parses a date string into a datetime object.
    Supports common formats like 'DD MMM YYYY', 'YYYY-MM-DD', etc.
    """
    if not date_str:
        return None
    
    formats = [
        "%d %b %Y", "%d %B %Y",  # 01 Jan 2025, 01 January 2025
        "%Y-%m-%d",              # 2025-01-01
        "%b %d, %Y", "%B %d, %Y", # Jan 01, 2025, January 01, 2025
        "%d/%m/%Y", "%m/%d/%Y"   # 01/01/2025
    ]
    
    cleaned_date = date_str.strip()
    for fmt in formats:
        try:
            return datetime.strptime(cleaned_date, fmt)
        except ValueError:
            continue
    return None


def is_deadline_valid(deadline_str: str, min_days: int = MIN_DEADLINE_DAYS) -> bool:
    """
    Checks if the deadline is valid (more than min_days from now).
    Returns True if valid or if deadline is missing/unparseable (to be safe).

    Args:
        deadline_str: The deadline string to check
        min_days: Minimum number of days before deadline (default from config)

    Returns:
        bool: True if deadline is valid (far enough in the future), False otherwise
    """
    if not deadline_str:
        return True  # Keep if no deadline specified

    deadline = parse_date(deadline_str)
    if not deadline:
        return True  # Keep if we can't parse it

    now = datetime.now()
    threshold = now + timedelta(days=min_days)

    # If deadline is in the past or within the threshold, it's invalid
    if deadline < threshold:
        return False

    return True


def is_posting_fresh(date_posted_str: str, max_age_days: int = MAX_POSTING_AGE_DAYS) -> bool:
    """
    Returns False if the grant was posted more than max_age_days ago.
    Only meaningful when the deadline field is null — used as a staleness proxy.
    Returns True (pass) when date_posted is missing or unparseable.
    """
    if not max_age_days or not date_posted_str:
        return True
    posted = parse_date(date_posted_str)
    if not posted:
        return True
    return (datetime.now() - posted).days <= max_age_days


def get_browser_config(headless: bool = True) -> BrowserConfig:
    """
    Returns the browser configuration for the crawler.

    Args:
        headless (bool): Whether to run the browser in headless mode. Defaults to True.

    Returns:
        BrowserConfig: The configuration settings for the browser.
    """
    # https://docs.crawl4ai.com/core/browser-crawler-config/
    return BrowserConfig(
        browser_type="chromium",  # Type of browser to simulate
        headless=headless,  # Run headless for faster automated crawling
        verbose=True,  # Enable verbose logging
    )


def get_llm_strategy() -> LLMExtractionStrategy:
    """
    Returns the configuration for the language model extraction strategy.

    Returns:
        LLMExtractionStrategy: The settings for how to extract data using LLM.
    """
    # Define extraction instruction
    instruction = (
        "Extract all grant/funding opportunity objects from the following content. "
        "For each grant, extract: 'title' (grant name), 'funding_organization' (donor/funder name), "
        "'grant_amount' (funding range if mentioned), 'deadline' (application deadline), "
        "'geographic_focus' (eligible countries/regions - prioritize Africa, Kenya, developing countries), "
        "'thematic_areas' (focus sectors like education, technology, e-waste, sustainability, "
        "environmental conservation, digital divide, circular economy), 'eligibility_criteria' "
        "(organization types accepted), 'description' (grant summary), 'application_url' (link to apply "
        "or read more), 'category' (if specified), and 'date_posted' (if available). "
        "Also evaluate 'is_relevant_preliminary' (boolean). Set it to false ONLY if ANY of the following are true: "
        "1. It IS a competition, contest, award, or prize (academic awards, startup competitions, innovation challenges, etc.). "
        "2. It is explicitly for-profit/commercial organizations ONLY (excludes nonprofits). "
        "3. It has NO connection to: education, technology, children/youth/students, Africa/developing countries, schools, nonprofits, IT equipment, or infrastructure. "
        "Otherwise, set 'is_relevant_preliminary' to true (to allow the deep analysis to evaluate it properly). "
        "If any field is not available, set it to null."
    )

    # xAI Grok — sole LLM provider
    xai_key = os.getenv("XAI_API_KEY")
    if not xai_key:
        raise RuntimeError(
            "XAI_API_KEY is not set. This crawler requires an xAI API key. "
            "Set it in your .env file: XAI_API_KEY=<your-key>"
        )

    print("[LLM Strategy] Using xAI Grok (grok-4-1-fast-reasoning) for extraction.")
    return LLMExtractionStrategy(
        provider="xai/grok-4-1-fast-reasoning",
        api_token=xai_key,
        schema=Grant.model_json_schema(),
        extraction_type="schema",
        chunk_token_threshold=8000,
        instruction=instruction,
        input_format="markdown",
        verbose=True,
    )


def get_relevance_strategy() -> LLMExtractionStrategy:
    """
    Returns the LLM strategy for analyzing grant relevance.

    Returns:
        LLMExtractionStrategy: Strategy configured for relevance scoring.
    """
    from pydantic import BaseModel, Field

    class RelevanceScore(BaseModel):
        is_relevant: bool = Field(description="Whether the grant is relevant to the mission")
        score: int = Field(description="Relevance score from 0-100")
        reasoning: str = Field(description="Brief explanation of the relevance assessment")
        how_it_helps: str = Field(description="Specific, actionable explanation of HOW this grant helps acquire/provide/maintain IT equipment for children in African schools")
        matching_themes: List[str] = Field(description="List of matching themes from the grant")
        deadline: Optional[str] = Field(default=None, description="Application deadline date (e.g. '2026-03-15', 'March 15, 2026', 'Rolling'). Extract from the page if available.")

    return LLMExtractionStrategy(
        provider="xai/grok-4-1-fast-reasoning",
        api_token=os.getenv("XAI_API_KEY"),
        schema=RelevanceScore.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Analyze this grant opportunity for a nonprofit organization with the following specific mission:\n\n"
            "CORE MISSION: Collect out-of-service IT equipment, refurbish/repurpose them, and provide them to "
            "children in schools in underserved areas of Africa (especially Kenya) to close the digital gap.\n\n"
            "WHAT WE DO:\n"
            "1. Source discarded/donated computers, laptops, tablets, and IT equipment from companies looking to go green\n"
            "2. Refurbish and repurpose these devices (e-waste management, circular economy, extending IT equipment lifecycle)\n"
            "3. Distribute them to schools in underserved/rural areas in Africa\n"
            "4. Enable children who would otherwise have no access to interact with technology\n"
            "5. Promote digital literacy and technology education for youth\n\n"
            "ORGANIZATION STATUS: We are a new organization, so we lack extensive credibility and a long track record. "
            "Therefore, grants with stringent requirements (e.g., long operational history, large budgets, extensive prior funding) are less suitable. "
            "Prioritize grants with simpler, more accessible application processes.\n\n"
            "MINIMUM REQUIREMENTS - Grant must meet at least 3 of these 5:\n"
            "1. Must be for or include NONPROFIT organizations (NGOs, CBOs, charities, social enterprises)\n"
            "2. Must NOT be primarily a competition, contest, award, or prize\n"
            "3. Must focus on or include: children, youth, students, schools, or educational institutions\n"
            "4. Must be in or include: Africa, Sub-Saharan Africa, East Africa, Kenya, developing countries, underserved communities, Global South, worldwide, or international\n"
            "5. Must relate to at least ONE of: digital literacy, IT/computer equipment, technology education/training, "
            "e-waste/electronics recycling, refurbished/repurposed technology, digital divide/access, computer labs, "
            "school infrastructure, educational technology, STEM education, circular economy (electronics), "
            "teacher training (technology), education equipment/supplies, capacity building, climate action/green technology\n\n"
            "IDEAL THEMES (higher scores, but not required):\n"
            "- Refurbished/repurposed IT equipment, circular economy for electronics, extending equipment lifecycle\n"
            "- E-waste management, electronic waste recycling, waste-to-resource programs, helping companies go green\n"
            "- Digital literacy programs for children/youth in Africa or developing countries\n"
            "- Technology education, IT skills training, computer training in underserved schools\n"
            "- Computer lab setup, IT infrastructure in rural/underserved areas\n"
            "- Bridging the digital divide, improving technology access for youth\n"
            "- ICT4Education, ICT4Development in developing countries\n"
            "- School infrastructure grants (if they could include computer labs/equipment)\n"
            "- Education equipment/supplies grants (if they could include IT equipment)\n"
            "- Teacher training/capacity building (if technology-related)\n"
            "- Grants with simple/accessible application processes for new organizations\n\n"
            "Based on this, analyze the provided grant. In your reasoning, first state whether it meets the minimum requirements. "
            "Then, explain how well it aligns with the core mission and ideal themes. "
            "Assign a score from 0-100, where 90-100 is a perfect match, 75-89 is a strong match, "
            "70-79 is a good match with a plausible path, 50-69 is a weak/tangential match, and below 50 is not relevant. "
            "Be critical: if a grant is for 'environmental' projects but doesn't mention technology or e-waste, it's a weak match. "
            "If it's for 'education' but doesn't mention technology, it's a weak match. "
            "If the grant's geographic focus EXCLUDES Africa entirely (e.g. only EU, only US, only Western Balkans), score below 50. "
            "If the grant is purely research/academic with no operational funding, score below 60. "
            "The 'how_it_helps' field MUST be a concrete, actionable plan for using this specific grant to achieve the mission, "
            "not a generic statement. For example: 'This grant could fund the refurbishment of 50 laptops, which would then be "
            "deployed to a school in Kenya to set up a new computer lab.' Be specific. "
            "If you CANNOT write a realistic, specific plan, set how_it_helps to 'Not applicable' AND score below 50. "
            "Do NOT inflate scores for grants that only loosely match keywords — the score must reflect whether this grant "
            "can REALISTICALLY fund collecting, refurbishing, or distributing IT equipment to African schools.\n\n"
            "DEADLINE EXTRACTION: You MUST extract the application deadline from the page content. "
            "Look for phrases like 'deadline', 'apply by', 'applications close', 'submissions due', 'closing date', etc. "
            "Return the deadline in a standard date format (e.g. '2026-03-15' or 'March 15, 2026'). "
            "If the grant has rolling/ongoing applications, return 'Rolling'. "
            "If no deadline is found anywhere on the page, return null."
        ),  # Instructions for the LLM
        input_format="html",  # The input from the grant details page
        verbose=True,  # Enable verbose logging
    )


async def analyze_grant_relevance(
    crawler: AsyncWebCrawler,
    grant_url: str,
    session_id: str,
) -> Optional[Dict]:
    """
    Fetches the full grant page and analyzes its relevance to the mission.

    Args:
        crawler: The web crawler instance
        grant_url: URL of the grant to analyze
        session_id: Session identifier

    Returns:
        Dict with relevance analysis or None if analysis fails
    """
    try:
        relevance_strategy = get_relevance_strategy()

        # Fetch the full grant page with relevance analysis
        result = await crawler.arun(
            url=grant_url,
            config=CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                extraction_strategy=relevance_strategy,
                session_id=session_id,
            ),
        )

        if result.success and result.extracted_content:
            analysis = json.loads(result.extracted_content)
            if isinstance(analysis, list) and len(analysis) > 0:
                return analysis[0]
            return analysis
        else:
            print(f"Failed to analyze relevance for {grant_url}: {result.error_message}")
            return None

    except Exception as e:
        print(f"Error analyzing grant relevance: {str(e)}")
        return None


async def check_no_results(
    crawler: AsyncWebCrawler,
    url: str,
    session_id: str,
) -> bool:
    """
    Checks if the "No Results Found" message is present on the page.

    Args:
        crawler (AsyncWebCrawler): The web crawler instance.
        url (str): The URL to check.
        session_id (str): The session identifier.

    Returns:
        bool: True if "No Results Found" message is found, False otherwise.
    """
    # Fetch the page without any CSS selector or extraction strategy
    result = await crawler.arun(
        url=url,
        config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            session_id=session_id,
        ),
    )

    if result.success:
        if "No Results Found" in result.cleaned_html:
            return True
    else:
        print(
            f"Error fetching page for 'No Results Found' check: {result.error_message}"
        )

    return False


async def fetch_and_process_page(
    crawler: AsyncWebCrawler,
    page_number: int,
    base_url: str,
    site_profile,  # Now accepts a BaseSiteProfile instead of css_selector
    llm_strategy: LLMExtractionStrategy,
    session_id: str,
    required_keys: List[str],
    seen_titles: Set[str],
    site_metrics=None,  # Optional SiteMetrics from site_tracker
) -> Tuple[List[dict], bool, bool]:
    """
    Fetches and processes a single page of grant data.

    Args:
        crawler (AsyncWebCrawler): The web crawler instance.
        page_number (int): The page number to fetch.
        base_url (str): The base URL of the website.
        site_profile: The site profile instance (implements BaseSiteProfile).
        llm_strategy (LLMExtractionStrategy): The LLM extraction strategy.
        session_id (str): The session identifier.
        required_keys (List[str]): List of required keys in the grant data.
        seen_titles (Set[str]): Set of grant titles that have already been seen.

    Returns:
        Tuple[List[dict], bool, bool]:
            - List[dict]: A list of processed grants from the page.
            - bool: A flag indicating if the "No Results Found" message was encountered.
            - bool: A flag indicating if any grants were found on the page (before filtering).
    """
    # Use site profile to construct the page URL
    url = site_profile.get_page_url(base_url, page_number)
    logger.info(f"Loading page {page_number}...")

    # Use site profile to check if we've reached the end of results
    no_results = await site_profile.detect_end_of_results(crawler, url, session_id)
    if no_results:
        return [], True, False  # No more results, signal to stop crawling

    # Debug LLM strategy
    logger.debug(f"llm_strategy type: {type(llm_strategy)}")
    provider = getattr(llm_strategy, 'provider', 'NOT_FOUND')
    logger.debug(f"llm_strategy provider: {provider}")

    # Check if we should use manual Groq extraction
    # Check for both "groq" string and if the provider itself is "groq"
    use_manual_groq = "groq" in str(provider).lower()
    logger.debug(f"Using Manual Groq Extraction: {use_manual_groq}")
    
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,  # Do not use cached data
        extraction_strategy=llm_strategy if not use_manual_groq else None,  # Use manual for Groq
        css_selector=site_profile.get_css_selector(),  # Get selector from site profile
        session_id=session_id,  # Unique session ID for the crawl
    )

    # Fetch page content
    with metrics_logger.measure("fetch_page", site=site_profile.site_name, url=url) as ctx:
        result = await crawler.arun(
            url=url,
            config=config,
        )
        if not result.success:
            ctx.status = "ERROR"
            ctx.error = result.error_message

    extracted_data = []

    if use_manual_groq:
        if result.success and result.cleaned_html:
            from utils.groq_utils import extract_grants_from_html_groq
            logger.info("Extracting grants sequentially to respect rate limits...")
            with metrics_logger.measure("extract_groq_manual", site=site_profile.site_name, url=url) as ctx:
                extracted_data = await extract_grants_from_html_groq(result.cleaned_html)
                ctx.items = len(extracted_data)
        else:
             logger.error(f"Error fetching page {page_number} (Manual Groq): {result.error_message}")
             return [], False, False, False
    else:
        # Standard Crawl4AI extraction
        if not (result.success and result.extracted_content):
            logger.error(f"Error fetching page {page_number}: {result.error_message}")
            return [], False, False, False

        try:
            extracted_data = json.loads(result.extracted_content)
        except json.JSONDecodeError:
             logger.error(f"Error decoding JSON content from page {page_number}")
             return [], False, False, False

    if not extracted_data:
        logger.warning(f"No grants found on page {page_number} of {base_url}.")
        return [], False, False, False

    # After parsing extracted content
    logger.debug(f"Extracted data: {extracted_data}")

    # Process grants
    complete_grants = []
    duplicate_count = 0  # Track grants already known (for early-stop signal)

    # Record total fetched for site tracker
    if site_metrics:
        site_metrics.record_fetched(len(extracted_data))

    # Log number of grants found before processing
    with metrics_logger.measure("process_loop", site=site_profile.site_name, url=url) as loop_ctx:
        loop_ctx.items = len(extracted_data)

        for grant in extracted_data:
            # Debugging: Print each grant to understand its structure
            logger.debug(f"Processing grant: {grant}")

            # Ignore the 'error' key if it's False
            if grant.get("error") is False:
                grant.pop("error", None)  # Remove the 'error' key if it's False

            if not is_complete_grant(grant, required_keys):
                if site_metrics:
                    site_metrics.record_filtered("incomplete")
                continue  # Skip incomplete grants

            if is_duplicate_grant(grant.get("title"), seen_titles):
                logger.debug(f"Duplicate grant '{grant.get('title')}' found. Skipping.")
                duplicate_count += 1
                if site_metrics:
                    site_metrics.record_filtered("duplicate_in_run")
                continue  # Skip duplicate grants

            # Pre-deep-analysis deadline check (listing-page deadline, if available)
            deadline = grant.get("deadline")
            if deadline and not is_deadline_valid(deadline):
                logger.debug(f"Skipping '{grant.get('title')}': deadline '{deadline}' is in the past or too soon.")
                if site_metrics:
                    site_metrics.record_filtered("deadline_expired")
                continue

            # Stale posting check: no deadline + posted too long ago → likely expired
            if not deadline:
                date_posted = grant.get("date_posted")
                if not is_posting_fresh(date_posted):
                    logger.info(
                        f"⏰ Skipping '{grant.get('title')}': no deadline, "
                        f"posted {date_posted} (>{MAX_POSTING_AGE_DAYS}d ago)."
                    )
                    if site_metrics:
                        site_metrics.record_filtered("stale_posting")
                    continue

            # Check preliminary relevance
            # If is_relevant_preliminary is explicitly False, we skip.
            # If it's None (LLM didn't return it), we proceed to be safe.
            if grant.get("is_relevant_preliminary") is False:
                 logger.debug(f"Skipping '{grant.get('title')}': Not relevant based on preliminary check.")
                 if site_metrics:
                     site_metrics.record_filtered("preliminary_irrelevant")
                 continue

            # Analyze grant relevance using configured LLM provider
            grant_url = grant.get("application_url")
            logger.info(f"Analyzing relevance for: {grant.get('title', 'Unknown')} (using {RELEVANCE_PROVIDER})")

            if site_metrics:
                site_metrics.record_sent_to_scoring()

            relevance_analysis = None
            
            with metrics_logger.measure("analyze_relevance", site=site_profile.site_name, url=grant_url or "N/A") as rel_ctx:
                if grant_url:
                    # Full-page analysis: fetches the complete grant page for deeper scoring
                    relevance_analysis = await analyze_grant_relevance(crawler, grant_url, session_id)

                # Fallback to xAI analysis with listing-page data if full-page fails
                if not relevance_analysis:
                    relevance_analysis = await analyze_grant_relevance_xai(grant)
                
                if relevance_analysis:
                    rel_ctx.status = "SUCCESS"
                else:
                    rel_ctx.status = "FAILED"
                    rel_ctx.error = "No analysis returned"

            if relevance_analysis:
                # Normalize field names: score→relevance_score, reasoning→relevance_reasoning
                if "score" in relevance_analysis and "relevance_score" not in relevance_analysis:
                    relevance_analysis["relevance_score"] = int(relevance_analysis.pop("score", 0))
                if "reasoning" in relevance_analysis and "relevance_reasoning" not in relevance_analysis:
                    relevance_analysis["relevance_reasoning"] = relevance_analysis.pop("reasoning", "")
                
                # Merge analysis results into grant object
                grant.update(relevance_analysis)
                
                # Check score against threshold
                score = grant.get("relevance_score", grant.get("score", 0))
                hih = grant.get("how_it_helps", "")
                title = grant.get("title", "")

                if score >= MIN_RELEVANCE_SCORE:
                    # Reject if the LLM admits the grant doesn't help the mission
                    if not is_how_it_helps_valid(hih):
                        logger.info(f" \u2717 Skipping - score {score} but how_it_helps='Not applicable'")
                        if site_metrics:
                            site_metrics.record_scored(title, score, hih, accepted=False, reason_rejected="how_it_helps_invalid")
                        continue

                    # Post-deep-analysis deadline check (may now have deadline from full page)
                    deep_deadline = grant.get("deadline")
                    if deep_deadline and deep_deadline.lower() not in ("rolling", "ongoing", "open", "continuous", "no deadline"):
                        if not is_deadline_valid(deep_deadline):
                            logger.info(f" ✗ Skipping - score {score} but deadline '{deep_deadline}' is in the past or too soon")
                            if site_metrics:
                                site_metrics.record_scored(title, score, hih, accepted=False, reason_rejected="deadline_expired")
                            continue

                    logger.info(f" ✓ Relevant grant found! Score: {score}/100 - {title}")
                    if site_metrics:
                        site_metrics.record_scored(title, score, hih, accepted=True)
                    
                    # Add source website metadata
                    grant["source_website"] = site_profile.site_name
                    seen_titles.add(grant["title"])
                    
                    complete_grants.append(grant)
                else:
                    logger.info(f" ✗ Skipping - score {score} below threshold ({MIN_RELEVANCE_SCORE})")
                    if site_metrics:
                        site_metrics.record_scored(title, score, hih, accepted=False, reason_rejected="low_score")
            else:
                logger.warning(f"Could not analyze relevance for '{grant.get('title')}'. Skipping.")
                if site_metrics:
                    site_metrics.record_filtered("analysis_failed")

    # Track if we found any grants on the page (even if filtered out)
    grants_found_on_page = len(extracted_data) > 0

    # Signal early stop when every extracted grant was already known to the DB/run
    all_were_duplicates = grants_found_on_page and (duplicate_count == len(extracted_data))

    if not complete_grants:
        logger.info(f"No complete grants found on page {page_number}.")
        return [], False, grants_found_on_page, all_were_duplicates

    logger.info(f"Extracted {len(complete_grants)} grants from page {page_number}.")
    return complete_grants, False, grants_found_on_page, all_were_duplicates
