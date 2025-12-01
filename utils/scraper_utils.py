import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMExtractionStrategy,
)

from models.grant import Grant
from utils.data_utils import is_complete_grant, is_duplicate_grant
from config import MIN_DEADLINE_DAYS


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


def get_browser_config() -> BrowserConfig:
    """
    Returns the browser configuration for the crawler.

    Returns:
        BrowserConfig: The configuration settings for the browser.
    """
    # https://docs.crawl4ai.com/core/browser-crawler-config/
    return BrowserConfig(
        browser_type="chromium",  # Type of browser to simulate
        headless=False,  # Whether to run in headless mode (no GUI)
        verbose=True,  # Enable verbose logging
    )


def get_llm_strategy() -> LLMExtractionStrategy:
    """
    Returns the configuration for the language model extraction strategy.

    Returns:
        LLMExtractionStrategy: The settings for how to extract data using LLM.
    """
    # https://docs.crawl4ai.com/api/strategies/#llmextractionstrategy
    return LLMExtractionStrategy(
        provider="xai/grok-3",  # xAI Grok model with subscription
        api_token=os.getenv("XAI_API_KEY"),  # xAI API token
        schema=Grant.model_json_schema(),  # JSON schema of the data model
        extraction_type="schema",  # Type of extraction to perform
        chunk_token_threshold=4000,  # Break content into chunks to stay within rate limits
        instruction=(
            "Extract all grant/funding opportunity objects from the following content. "
            "For each grant, extract: 'title' (grant name), 'funding_organization' (donor/funder name), "
            "'grant_amount' (funding range if mentioned), 'deadline' (application deadline), "
            "'geographic_focus' (eligible countries/regions - prioritize Africa, Kenya, developing countries), "
            "'thematic_areas' (focus sectors like education, technology, e-waste, sustainability, "
            "environmental conservation, digital divide, circular economy), 'eligibility_criteria' "
            "(organization types accepted), 'description' (grant summary), 'application_url' (link to apply "
            "or read more), 'category' (if specified), and 'date_posted' (if available). "
            "Also evaluate 'is_relevant_preliminary' (boolean). Set it to true ONLY if ALL of the following are met: "
            "1. It is NOT a competition, contest, or award/prize. "
            "2. It is for NONPROFIT organizations (NGOs, CBOs, etc.). "
            "3. It is explicitly about helping CHILDREN in AFRICA close the DIGITAL GAP (e.g., providing IT equipment/computers to schools, digital literacy for kids). "
            "If it misses any of these or is irrelevant, set 'is_relevant_preliminary' to false. "
            "If any field is not available, set it to null."
        ),  # Instructions for the LLM
        input_format="markdown",  # Format of the input content
        verbose=True,  # Enable verbose logging
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

    return LLMExtractionStrategy(
        provider="xai/grok-3",
        api_token=os.getenv("XAI_API_KEY"),
        schema=RelevanceScore.model_json_schema(),
        extraction_type="schema",
        instruction=(
            "Analyze this grant opportunity for a nonprofit organization with the following specific mission:\n\n"
            "CORE MISSION: Collect out-of-service IT equipment, refurbish/repurpose them, and provide them to "
            "children in schools in underserved areas of Africa (especially Kenya) to close the digital gap.\n\n"
            "WHAT WE DO:\n"
            "1. Source discarded/donated computers, laptops, tablets, and IT equipment\n"
            "2. Refurbish and repurpose these devices (e-waste management, circular economy)\n"
            "3. Distribute them to schools in underserved/rural areas in Africa\n"
            "4. Enable children who would otherwise have no access to interact with technology\n"
            "5. Promote digital literacy and technology education for youth\n\n"
            "STRICT REQUIREMENTS - Grant must meet ALL of these:\n"
            "✓ Must be for NONPROFIT organizations (NGOs, CBOs, charities)\n"
            "✓ Must NOT be a competition, contest, award, or prize\n"
            "✓ Must focus on CHILDREN/YOUTH in AFRICA (especially Kenya or other developing countries)\n"
            "✓ Must relate to at least ONE of: digital literacy, IT equipment provision, technology education, "
            "e-waste management, refurbished technology, closing the digital divide, computer access for schools\n\n"
            "IDEAL THEMES (higher scores):\n"
            "- Refurbished/repurposed IT equipment, circular economy\n"
            "- E-waste management, electronic waste recycling\n"
            "- Digital literacy programs for children in Africa\n"
            "- Technology education in underserved schools\n"
            "- Computer lab setup in rural/underserved areas\n"
            "- Bridging the digital divide for youth\n"
            "- ICT4Education in developing countries\n\n"
            "CRITICAL: In the 'how_it_helps' field, you MUST provide a SPECIFIC, ACTIONABLE explanation of exactly HOW "
            "this grant can be used. Focus on ONE or MORE of these specific use cases:\n"
            "1. ACQUIRING IT EQUIPMENT: Can this grant fund purchasing new IT equipment? Can it fund sourcing/collecting old equipment? "
            "Can it fund partnerships with e-waste collectors or IT recyclers?\n"
            "2. PROVIDING/DISTRIBUTING EQUIPMENT: Can this grant fund delivery/logistics to schools? Can it fund installation of computer labs? "
            "Can it fund staffing for distribution programs?\n"
            "3. MAINTAINING EQUIPMENT & PROGRAM: Can this grant fund technical staff/repair technicians? Can it fund spare parts? "
            "Can it fund training programs? Can it fund ongoing program operations?\n\n"
            "DO NOT just list what criteria it meets. Instead, explain the ACTIONABLE PATH to using this grant.\n\n"
            "EXAMPLES OF GOOD 'how_it_helps':\n"
            "✓ 'This grant funds computer lab setup in rural African schools, which directly covers the cost of distributing our refurbished laptops and installing them in classrooms in underserved areas.'\n"
            "✓ 'This grant supports e-waste recycling programs in Kenya, which we can use to fund partnerships with local e-waste collectors to source discarded IT equipment for refurbishment.'\n"
            "✓ 'This grant funds digital literacy training for teachers in Africa, which we can use to train educators on how to use and maintain the refurbished computers we provide.'\n\n"
            "EXAMPLES OF BAD 'how_it_helps' (too vague, avoid these):\n"
            "✗ 'This grant aligns with our mission of helping children in Africa.'\n"
            "✗ 'This grant is about technology and education.'\n"
            "✗ 'This grant meets our criteria for nonprofit organizations.'\n\n"
            "SCORING:\n"
            "- 90-100: Perfect match with CLEAR actionable path (grant explicitly funds acquiring/providing/maintaining IT equipment for African schools)\n"
            "- 70-89: Strong match with SPECIFIC use case (grant funds closely related activities that support our mission)\n"
            "- 60-69: Good match with POTENTIAL use case (grant could reasonably be applied to our activities with some adaptation)\n"
            "- Below 60: Not relevant OR no clear actionable path (set is_relevant=false)\n\n"
            "A grant is RELEVANT (is_relevant=true) ONLY if:\n"
            "1. It scores 60 or above\n"
            "2. It meets all strict requirements\n"
            "3. You can provide a SPECIFIC, ACTIONABLE explanation in 'how_it_helps' (not just criteria matching)"
        ),
        input_format="markdown",
        verbose=True,
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
) -> Tuple[List[dict], bool]:
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
        Tuple[List[dict], bool]:
            - List[dict]: A list of processed grants from the page.
            - bool: A flag indicating if the "No Results Found" message was encountered.
    """
    # Use site profile to construct the page URL
    url = site_profile.get_page_url(base_url, page_number)
    print(f"Loading page {page_number}...")

    # Use site profile to check if we've reached the end of results
    no_results = await site_profile.detect_end_of_results(crawler, url, session_id)
    if no_results:
        return [], True  # No more results, signal to stop crawling

    # Fetch page content with the extraction strategy
    result = await crawler.arun(
        url=url,
        config=CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,  # Do not use cached data
            extraction_strategy=llm_strategy,  # Strategy for data extraction
            css_selector=site_profile.get_css_selector(),  # Get selector from site profile
            session_id=session_id,  # Unique session ID for the crawl
        ),
    )

    if not (result.success and result.extracted_content):
        print(f"Error fetching page {page_number}: {result.error_message}")
        return [], False

    # Parse extracted content
    extracted_data = json.loads(result.extracted_content)
    if not extracted_data:
        print(f"No grants found on page {page_number}.")
        return [], False

    # After parsing extracted content
    print("Extracted data:", extracted_data)

    # Process grants
    complete_grants = []
    for grant in extracted_data:
        # Debugging: Print each grant to understand its structure
        print("Processing grant:", grant)

        # Ignore the 'error' key if it's False
        if grant.get("error") is False:
            grant.pop("error", None)  # Remove the 'error' key if it's False

        if not is_complete_grant(grant, required_keys):
            continue  # Skip incomplete grants

        if is_duplicate_grant(grant.get("title"), seen_titles):
            print(f"Duplicate grant '{grant.get('title')}' found. Skipping.")
            continue  # Skip duplicate grants

        # Check deadline
        if not is_deadline_valid(grant.get("deadline")):
            print(f"Skipping '{grant.get('title')}': Deadline passed or too soon ({grant.get('deadline')})")
            continue

        # Check preliminary relevance
        # If is_relevant_preliminary is explicitly False, we skip.
        # If it's None (LLM didn't return it), we proceed to be safe.
        if grant.get("is_relevant_preliminary") is False:
             print(f"Skipping '{grant.get('title')}': Not relevant based on preliminary check.")
             continue

        # Analyze grant relevance by fetching the full page
        grant_url = grant.get("application_url")
        if grant_url:
            print(f"Analyzing relevance for: {grant['title']}")
            relevance_analysis = await analyze_grant_relevance(
                crawler, grant_url, session_id
            )

            if relevance_analysis:
                print(
                    f"  Score: {relevance_analysis.get('score', 0)}/100 | "
                    f"Relevant: {relevance_analysis.get('is_relevant', False)}"
                )
                print(f"  Reasoning: {relevance_analysis.get('reasoning', 'N/A')}")
                print(f"  How it helps: {relevance_analysis.get('how_it_helps', 'N/A')}")

                # Only include grants that are marked as relevant
                if not relevance_analysis.get("is_relevant", False):
                    print(f"  ✗ Skipping - not relevant to mission")
                    continue

                # Add relevance metadata to the grant
                grant["relevance_score"] = relevance_analysis.get("score", 0)
                grant["relevance_reasoning"] = relevance_analysis.get("reasoning", "")
                grant["how_it_helps"] = relevance_analysis.get("how_it_helps", "")
                grant["matching_themes"] = relevance_analysis.get("matching_themes", [])
            else:
                print(f"  Warning: Could not analyze relevance, including by default")

        # Add source website metadata
        grant["source_website"] = site_profile.site_name

        # Add grant to the list
        seen_titles.add(grant["title"])
        complete_grants.append(grant)

    if not complete_grants:
        print(f"No complete grants found on page {page_number}.")
        return [], False

    print(f"Extracted {len(complete_grants)} grants from page {page_number}.")
    return complete_grants, False  # Continue crawling
