import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Import Gemini relevance analyzer
from utils.gemini_utils import analyze_grant_relevance_gemini, GEMINI_AVAILABLE

# Import Groq relevance analyzer
from utils.groq_utils import analyze_grant_relevance_groq, GROQ_AVAILABLE

# Import xAI relevance analyzer
from utils.xai_utils import analyze_grant_relevance_xai, XAI_AVAILABLE

from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CacheMode,
    CrawlerRunConfig,
    LLMExtractionStrategy,
)

from models.grant import Grant
from utils.data_utils import is_complete_grant, is_duplicate_grant
from config import MIN_DEADLINE_DAYS, RELEVANCE_PROVIDER, MIN_RELEVANCE_SCORE


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
- 75-89: Strong match (education + technology + Africa)
- 60-74: Good match (meets requirements with some adaptation needed)
- Below 60: Not relevant (missing key requirements)

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


def get_browser_config() -> BrowserConfig:
    """
    Returns the browser configuration for the crawler.

    Returns:
        BrowserConfig: The configuration settings for the browser.
    """
    # https://docs.crawl4ai.com/core/browser-crawler-config/
    return BrowserConfig(
        browser_type="chromium",  # Type of browser to simulate
        headless=True,  # Run headless for faster automated crawling
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

    # 0. Check for xAI (Grok) - PRIMARY configuration
    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
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

    # 1. Check for Local LLM flag (Ollama)
    # Set USE_LOCAL_LLM=true in your .env or environment
    if os.getenv("USE_LOCAL_LLM", "false").lower() == "true":
        print("[LLM Strategy] Using Local Ollama (llama3.1) for extraction.")
        return LLMExtractionStrategy(
            provider="ollama/llama3.1",
            api_token="ollama",
            schema=Grant.model_json_schema(),
            extraction_type="schema",
            chunk_token_threshold=2000,
            instruction=instruction,
            input_format="markdown",
            verbose=True,
        )

    # 2. Check for Gemini API key as it has higher rate limits
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        print("[LLM Strategy] Using Gemini (gemini-1.5-flash) for extraction.")
        return LLMExtractionStrategy(
            provider="gemini/gemini-1.5-flash-latest",
            api_token=gemini_key,
            schema=Grant.model_json_schema(),
            extraction_type="schema",
            chunk_token_threshold=8000,
            instruction=instruction,
            input_format="markdown",
            verbose=True,
        )

    # 3. Fallback to Groq
    print("[LLM Strategy] Using Groq (llama-3.1-8b-instant) for extraction.")
    return LLMExtractionStrategy(
        provider="groq/llama-3.1-8b-instant",  # Smaller model with higher rate limits
        api_token=os.getenv("GROQ_API_KEY"),  # From .env file
        schema=Grant.model_json_schema(),  # JSON schema of the data model
        extraction_type="schema",  # Type of extraction to perform
        chunk_token_threshold=800,  # Drastically reduced chunk size to respect 6k TPM limit
        overlap=50, # Add overlap to ensure context preservation
        word_count_threshold=20, # Filter out small blocks
        instruction=instruction,  # Instructions for the LLM
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
            "60-74 is a good match, and below 60 is not relevant. "
            "Be critical: if a grant is for 'environmental' projects but doesn't mention technology or e-waste, it's a weak match. "
            "If it's for 'education' but doesn't mention technology, it's a weak match. "
            "The 'how_it_helps' field MUST be a concrete, actionable plan for using this specific grant to achieve the mission, "
            "not a generic statement. For example: 'This grant could fund the refurbishment of 50 laptops, which would then be "
            "deployed to a school in Kenya to set up a new computer lab.' Be specific."
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
    print(f"Loading page {page_number}...")

    # Use site profile to check if we've reached the end of results
    no_results = await site_profile.detect_end_of_results(crawler, url, session_id)
    if no_results:
        return [], True, False  # No more results, signal to stop crawling

    # Debug LLM strategy
    print(f"[DEBUG] llm_strategy type: {type(llm_strategy)}")
    provider = getattr(llm_strategy, 'provider', 'NOT_FOUND')
    print(f"[DEBUG] llm_strategy provider: {provider}")

    # Check if we should use manual Groq extraction
    # Check for both "groq" string and if the provider itself is "groq"
    use_manual_groq = "groq" in str(provider).lower()
    print(f"[DEBUG] Using Manual Groq Extraction: {use_manual_groq}")
    
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,  # Do not use cached data
        extraction_strategy=llm_strategy if not use_manual_groq else None,  # Use manual for Groq
        css_selector=site_profile.get_css_selector(),  # Get selector from site profile
        session_id=session_id,  # Unique session ID for the crawl
    )

    # Fetch page content
    result = await crawler.arun(
        url=url,
        config=config,
    )

    extracted_data = []

    if use_manual_groq:
        if result.success and result.cleaned_html:
            from utils.groq_utils import extract_grants_from_html_groq
            print(f"[MANUAL GROQ] Extracting grants sequentially to respect rate limits...")
            extracted_data = await extract_grants_from_html_groq(result.cleaned_html)
        else:
             print(f"Error fetching page {page_number} (Manual Groq): {result.error_message}")
             return [], False, False
    else:
        # Standard Crawl4AI extraction
        if not (result.success and result.extracted_content):
            print(f"Error fetching page {page_number}: {result.error_message}")
            return [], False, False
        
        try:
            extracted_data = json.loads(result.extracted_content)
        except json.JSONDecodeError:
             print(f"Error decoding JSON content from page {page_number}")
             return [], False, False

    if not extracted_data:
        print(f"No grants found on page {page_number} of {base_url}.")
        return [], False, False

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

        # Analyze grant relevance using configured LLM provider
        # Stage 2: Deep analysis — fetch full grant page when URL is available
        grant_url = grant.get("application_url")
        print(f"Analyzing relevance for: {grant['title']} (using {RELEVANCE_PROVIDER})")

        relevance_analysis = None
        if grant_url:
            # Full-page analysis: fetches the complete grant page for deeper scoring
            relevance_analysis = await analyze_grant_relevance(crawler, grant_url, session_id)

        # Fallback to provider-specific analysis with listing-page data if full-page fails
        if not relevance_analysis:
            if RELEVANCE_PROVIDER == "gemini":
                relevance_analysis = await analyze_grant_relevance_gemini(grant)
            elif RELEVANCE_PROVIDER == "groq":
                relevance_analysis = await analyze_grant_relevance_groq(grant)
            elif RELEVANCE_PROVIDER == "xai":
                relevance_analysis = await analyze_grant_relevance_xai(grant)
            else:  # Default to ollama
                relevance_analysis = await analyze_grant_relevance_local(grant)
        if relevance_analysis:
            print(
                f"  Score: {relevance_analysis.get('score', 0)}/100 | "
                f"Relevant: {relevance_analysis.get('is_relevant', False)}"
            )
            print(f"  Reasoning: {relevance_analysis.get('reasoning', 'N/A')}")
            print(f"  How it helps: {relevance_analysis.get('how_it_helps', 'N/A')}")

            # Use numeric score threshold instead of binary is_relevant flag
            score = relevance_analysis.get("score", 0)
            if score < MIN_RELEVANCE_SCORE:
                print(f"  ✗ Skipping - score {score} below threshold {MIN_RELEVANCE_SCORE}")
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

    # Track if we found any grants on the page (even if filtered out)
    grants_found_on_page = len(extracted_data) > 0

    if not complete_grants:
        print(f"No complete grants found on page {page_number}.")
        return [], False, grants_found_on_page

    print(f"Extracted {len(complete_grants)} grants from page {page_number}.")
    return complete_grants, False, grants_found_on_page  # Continue crawling
