# utils/xai_utils.py
"""
xAI (Grok) integration for grant relevance scoring.
Uses the xAI API (compatible with OpenAI SDK).
"""

import json
import os
from typing import Dict, Optional

try:
    from openai import AsyncOpenAI
    XAI_AVAILABLE = True
except ImportError:
    XAI_AVAILABLE = False

# Global client instance
_xai_client = None


def get_xai_client():
    """
    Get or create xAI client with API key from environment.
    
    Returns:
        AsyncClient instance or None if unavailable.
    """
    global _xai_client
    
    if not XAI_AVAILABLE:
        print("  ⚠ Warning: openai library not installed.")
        print("    Install with: pip install openai")
        return None
    
    if _xai_client is not None:
        return _xai_client
    
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        print("  ⚠ Warning: XAI_API_KEY not found in environment variables.")
        return None
    
    # xAI API endpoint
    _xai_client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )
    return _xai_client


async def analyze_grant_relevance_xai(grant_data: dict) -> Optional[Dict]:
    """
    Analyzes the relevance of a grant using xAI's Grok model.
    
    Args:
        grant_data: Dictionary containing grant details.
        
    Returns:
        Dictionary with relevance score and reasoning, or None if failed.
    """
    client = get_xai_client()
    if not client:
        return None

    # Construct mission-aligned prompt
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

Respond with ONLY a JSON object (no markdown):
{{
  "is_relevant": true or false,
  "score": number 0-100,
  "reasoning": "Brief explanation",
  "how_it_helps": "Specific action plan or 'Not applicable'",
  "matching_themes": ["list", "of", "themes"]
}}"""

    try:
        # xAI Grok call
        completion = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        
        content = completion.choices[0].message.content
        result = json.loads(content)
        
        # Ensure types
        result['score'] = int(result.get('score', 0))
        result['is_relevant'] = bool(result.get('is_relevant', False))
        
        return result
        
    except Exception as e:
        print(f"  ⚠ Error with xAI analysis: {e}")
        return None
