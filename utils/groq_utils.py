# utils/groq_utils.py
"""
Groq integration for grant relevance scoring.
Uses the free tier of Groq API (30 RPM, very fast inference).
"""

import json
import os
from typing import Dict, Optional

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# Global client instance
_groq_client = None


def get_groq_client():
    """
    Get or create Groq client with API key from environment.
    
    Returns:
        Client instance or None if unavailable.
    """
    global _groq_client
    
    if not GROQ_AVAILABLE:
        print("  ⚠ Warning: groq library not installed.")
        print("    Install with: pip install groq")
        return None
    
    if _groq_client is not None:
        return _groq_client
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("  ⚠ Warning: GROQ_API_KEY not found in environment variables.")
        print("    Add it to your .env file: GROQ_API_KEY=your_key_here")
        return None
    
    _groq_client = Groq(api_key=api_key)
    return _groq_client


async def extract_one_grant_groq(html_chunk: str, client) -> Optional[dict]:
    """
    Extracts a single grant object from an HTML chunk using Groq.
    """
    if not html_chunk or len(html_chunk) < 50:
        return None

    prompt = f"""Extract 1 grant opportunity from this HTML content.
    Return ONLY a JSON object with these keys: title, funding_organization, grant_amount, deadline, geographic_focus, thematic_areas, eligibility_criteria, description, application_url, category, date_posted.
    If a field is missing, use null.
    
    HTML CONTENT:
    {html_chunk}
    """
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a helpful data extraction assistant. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        print(f"Error extracting grant from chunk: {e}")
        return None


async def extract_grants_from_html_groq(html_content: str) -> list:
    """
    Extracts grants from HTML content by splitting and processing sequentially to avoid rate limits.
    """
    import asyncio
    client = get_groq_client()
    if not client:
        return []

    # Heuristic split by </article> to separate items
    # This assumes the CSS selector return multiple 'article' elements concatenated
    # If not, we might need a different split strategy
    chunks = html_content.split("</article>")
    
    grants = []
    print(f"Processing {len(chunks)} potential blocks sequentially with Groq...")
    
    for i, chunk in enumerate(chunks):
        if len(chunk.strip()) < 100:
            continue
            
        print(f"  - Extracting block {i+1}/{len(chunks)}...")
        grant = await extract_one_grant_groq(chunk, client)
        if grant:
            grants.append(grant)
        
        # Rate limiting: Sleep 2s between calls (approx 30 RPM)
        await asyncio.sleep(2)
        
    return grants


async def analyze_grant_relevance_groq(grant_data: dict) -> Optional[Dict]:
    """
    Analyze grant relevance using Groq (free tier with Llama 3.1 70B).
    
    Args:
        grant_data: Dict containing title, description, thematic_areas, 
                    geographic_focus, eligibility_criteria from initial extraction.
    
    Returns:
        Dict with is_relevant, score, reasoning, how_it_helps, matching_themes
        or None if Groq is unavailable/fails.
    """
    client = get_groq_client()
    if client is None:
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
Funding Organization: {grant_data.get('funding_organization', 'N/A')}
Grant Amount: {grant_data.get('grant_amount', 'N/A')}

MINIMUM REQUIREMENTS (at least 3 of 5 must be met for is_relevant=true):
1. Must accept NONPROFIT organizations (NGOs, CBOs, charities)
2. Must NOT be a competition, contest, award, or prize
3. Must focus on: children, youth, students, schools, or education
4. Must include: Africa, Sub-Saharan Africa, East Africa, Kenya, developing countries, Global South, worldwide, or international
5. Must relate to ONE of: digital literacy, IT equipment, technology education, e-waste/recycling, refurbished tech, digital divide, computer labs, STEM education, school infrastructure, education equipment/supplies, capacity building, climate action/green technology

IDEAL THEMES (higher scores):
- Refurbished/repurposed IT equipment, circular economy for electronics
- E-waste management, electronic waste recycling
- Digital literacy programs for children/youth in Africa
- Technology education, IT skills training in underserved schools
- Computer lab setup, IT infrastructure in rural areas
- Bridging the digital divide
- School infrastructure grants (if they could include computer labs)
- Grants with simple/accessible application processes for new organizations

SCORING GUIDE:
- 90-100: Perfect match (directly funds IT equipment for African schools)
- 75-89: Strong match (education + technology + Africa)
- 60-74: Good match (meets requirements with some adaptation needed)
- Below 60: Not relevant (missing key requirements)

IMPORTANT: Respond with ONLY a valid JSON object, no markdown formatting, no code blocks, no explanation outside JSON:
{{
  "is_relevant": true or false,
  "score": number 0-100,
  "reasoning": "Brief explanation of why this grant does or does not match the mission. First state which minimum requirements are met/unmet.",
  "how_it_helps": "Specific, actionable explanation of how this grant could fund IT equipment acquisition or distribution to African schools. Be concrete, e.g., 'This grant could fund refurbishment of 50 laptops for deployment to a Kenya school computer lab.' If not relevant, state 'Not applicable'",
  "matching_themes": ["list", "of", "matching", "themes"]
}}"""

    try:
        # Use Llama 3.3 70B for high quality, fast inference
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,  # Low temperature for consistent scoring
            max_tokens=500,
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Clean response - remove markdown code blocks if present
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith('```') and not in_json:
                    in_json = True
                    continue
                elif line.startswith('```') and in_json:
                    break
                elif in_json:
                    json_lines.append(line)
            response_text = '\n'.join(json_lines)
        
        # Parse JSON response
        result = json.loads(response_text)
        
        # Validate required fields exist
        required_fields = ['is_relevant', 'score', 'reasoning']
        for field in required_fields:
            if field not in result:
                print(f"  ⚠ Warning: Groq response missing '{field}' field")
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
        
    except json.JSONDecodeError as e:
        print(f"  ⚠ Warning: Failed to parse Groq JSON response: {e}")
        print(f"    Response was: {response_text[:200]}...")
        return None
    except Exception as e:
        error_msg = str(e).lower()
        if 'api_key' in error_msg or 'invalid' in error_msg or 'authentication' in error_msg:
            print("  ⚠ Warning: Invalid Groq API key. Please check your GROQ_API_KEY.")
        elif 'rate' in error_msg:
            print("  ⚠ Warning: Groq rate limit hit. Please wait and try again.")
        else:
            print(f"  ⚠ Warning: Groq error: {e}")
        return None
