"""
Test the EU Funding & Tenders Search API directly.
Confirm the API works, understand the request body format, and examine full result objects.
"""
import asyncio
import json
import httpx

API_BASE = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
API_KEY = "SEDIA"

# The portal sends this POST request to search for calls for proposals
# Status values: 31094501=Forthcoming, 31094502=Open, 31094503=Closed
# We want Open (31094502) and Forthcoming (31094501)
SEARCH_PARAMS = {
    "apiKey": API_KEY,
    "text": "***",  # Wildcard
    "pageSize": 5,  # Small for testing
    "pageNumber": 1,
}

# The body payload mimics what the portal sends
# We need to figure out the exact format by sending a minimal request first
async def test_basic_search():
    """Test the basic search API endpoint."""
    print("="*80)
    print("TEST 1: Basic search with URL params only (GET-style)")
    print("="*80)
    
    url = f"{API_BASE}?apiKey={API_KEY}&text=***&pageSize=5&pageNumber=1"
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Try GET first
        resp = await client.get(url)
        print(f"GET Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Total results: {data.get('totalResults')}")
            print(f"Results count: {len(data.get('results', []))}")
        else:
            print(f"Response: {resp.text[:500]}")
        
        # Try POST with body (the portal uses POST)
        print("\n" + "="*80)
        print("TEST 2: POST with filter body (mimicking portal)")
        print("="*80)
        
        # The portal sends the body as form-encoded query with JSON filters
        # Let's try with the status filter for Open + Forthcoming calls
        post_url = f"{API_BASE}?apiKey={API_KEY}&text=***&pageSize=5&pageNumber=1"
        
        # Body contains the query filters
        body = {
            "bool": {
                "must": [
                    {"terms": {"sortStatus": ["31094502", "31094501"]}}  # Open + Forthcoming
                ]
            }
        }
        
        headers = {"Content-Type": "application/json"}
        resp = await client.post(post_url, json=body, headers=headers)
        print(f"POST Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"Total results: {data.get('totalResults')}")
            results = data.get('results', [])
            print(f"Results in page: {len(results)}")
            
            if results:
                print("\n" + "-"*60)
                print("FULL FIRST RESULT:")
                print("-"*60)
                first = results[0]
                # Print the key fields
                print(f"  Reference: {first.get('reference')}")
                print(f"  Title: {first.get('title')}")
                print(f"  URL: {first.get('url')}")
                print(f"  Content Type: {first.get('contentType')}")
                print(f"  Database: {first.get('database')}")
                print(f"  Summary: {first.get('summary', '')[:200]}")
                
                # Metadata is the richest part
                meta = first.get('metadata', {})
                print(f"\n  METADATA KEYS: {list(meta.keys())}")
                for key, val in meta.items():
                    if isinstance(val, list):
                        print(f"    {key}: {val[:3]}")
                    else:
                        print(f"    {key}: {str(val)[:150]}")
                
                # Print full JSON of first result
                print(f"\n  FULL JSON (first result):")
                print(json.dumps(first, indent=2)[:5000])
        else:
            print(f"Response: {resp.text[:500]}")
        
        # TEST 3: Search with specific keywords relevant to our mission
        print("\n" + "="*80)
        print("TEST 3: Search with mission-relevant keywords")
        print("="*80)
        
        keywords_url = f"{API_BASE}?apiKey={API_KEY}&text=education+digital+africa&pageSize=5&pageNumber=1"
        body_filtered = {
            "bool": {
                "must": [
                    {"terms": {"sortStatus": ["31094502", "31094501"]}}  # Open + Forthcoming
                ]
            }
        }
        
        resp = await client.post(keywords_url, json=body_filtered, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            print(f"Total results for 'education digital africa': {data.get('totalResults')}")
            for i, r in enumerate(data.get('results', [])[:5]):
                meta = r.get('metadata', {})
                print(f"\n  [{i+1}] {r.get('title', 'No title')}")
                print(f"      Status: {meta.get('status', ['?'])}")
                print(f"      Deadline: {meta.get('deadlineDate', ['?'])}")
                print(f"      Programme: {meta.get('programmePeriod', ['?'])}")
                print(f"      URL: {r.get('url', '')[:100]}")
        
        # TEST 4: Try a broader search for capacity building / NGO / ICT
        print("\n" + "="*80)
        print("TEST 4: Broader search - ICT capacity building")
        print("="*80)
        
        url4 = f"{API_BASE}?apiKey={API_KEY}&text=ICT+capacity+building+developing+countries&pageSize=5&pageNumber=1"
        resp = await client.post(url4, json=body_filtered, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            print(f"Total results: {data.get('totalResults')}")
            for i, r in enumerate(data.get('results', [])[:5]):
                meta = r.get('metadata', {})
                print(f"\n  [{i+1}] {r.get('title', 'No title')}")
                print(f"      Status: {meta.get('status', ['?'])}")
                print(f"      Deadline: {meta.get('deadlineDate', ['?'])}")


asyncio.run(test_basic_search())
