import aiohttp
import asyncio
import json

async def test_search():
    url = "https://api.grants.gov/v1/api/search2"
    payload = {
        "keyword": "technology",
        "oppStatuses": "posted",
        "sortBy": "openDate|desc",
        "rows": 10
    }
    
    async with aiohttp.ClientSession() as session:
        print(f"POST {url}")
        print(f"Payload: {json.dumps(payload)}")
        async with session.post(url, json=payload) as response:
            print(f"Status: {response.status}")
            text = await response.text()
            print(f"Response: {text[:500]}...")

if __name__ == "__main__":
    asyncio.run(test_search())