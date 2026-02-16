# utils/gemini_utils.py
"""
Google Gemini integration for grant relevance scoring.
Uses the free tier of Gemini API (15 RPM, 1M tokens/day).
"""

import json
import os
from typing import Dict, Optional

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# Global client instance
_gemini_client = None


def get_gemini_client():
    """
    Get or create Gemini client with API key from environment.
    
    Returns:
        Client instance or None if unavailable.
    """
    global _gemini_client
    
    if not GEMINI_AVAILABLE:
        print("  ⚠ Warning: google-genai library not installed.")
        print("    Install with: pip install google-genai")
        return None
    
    if _gemini_client is not None:
        return _gemini_client
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠ Warning: GEMINI_API_KEY not found in environment variables.")
        print("    Add it to your .env file: GEMINI_API_KEY=your_key_here")
        return None
    
    _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


async def analyze_grant_relevance_gemini(grant_data: dict) -> Optional[Dict]:
    """
    Analyze grant relevance using Google Gemini (free tier).
    
    Uses the Gemini 2.0 Flash model for fast, cost-effective analysis.
    
    Args:
        grant_data: Dict containing title, description, thematic_areas, 
                    geographic_focus, eligibility_criteria from initial extraction.
    
    Returns:
        Dict with is_relevant, score, reasoning, how_it_helps, matching_themes
        or None if Gemini is unavailable/fails.
    """
    client = get_gemini_client()
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
        # Use Gemini 1.5 Flash for fast, free inference (new API)
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,  # Low temperature for consistent scoring
                max_output_tokens=500,
            )
        )
        
        response_text = response.text.strip()
        
        # Clean response - remove markdown code blocks if present
        if response_text.startswith('```'):
            # Extract JSON from code block
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
                print(f"  ⚠ Warning: Gemini response missing '{field}' field")
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
        print(f"  ⚠ Warning: Failed to parse Gemini JSON response: {e}")
        print(f"    Response was: {response_text[:200]}...")
        return None
    except Exception as e:
        error_msg = str(e).lower()
        if 'api_key' in error_msg or 'invalid' in error_msg:
            print("  ⚠ Warning: Invalid Gemini API key. Please check your GEMINI_API_KEY.")
        elif 'quota' in error_msg or 'rate' in error_msg:
            print("  ⚠ Warning: Gemini rate limit exceeded. Please wait and try again.")
        else:
            print(f"  ⚠ Warning: Gemini error: {e}")
        return None


# Convenience function to match the existing interface
analyze_grant_relevance_cloud = analyze_grant_relevance_gemini
