"""Dig deeper into the EU API structure — examine request bodies, full result items, and filters."""
import json

with open('eu_portal_discovery.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Find the main search API call
for i, call in enumerate(data.get('api_calls', [])):
    url = call.get('url', '')

    # Search API — the main endpoint
    if 'search-api' in url and 'rest/search' in url:
        print('='*80)
        print(f'SEARCH API CALL [{i+1}]')
        print(f'URL: {url}')
        print(f'Method: {call.get("method")}')
        print(f'Status: {call.get("status")}')
        print(f'Content-Type: {call.get("content_type")}')
        print(f'Body length: {call.get("body_length")}')
        print()

        # Parse and show the full first result
        try:
            body = json.loads(call.get('body_preview', '{}'))
            print(f'Total Results: {body.get("totalResults")}')
            print(f'Page Number: {body.get("pageNumber")}')
            print(f'Page Size: {body.get("pageSize")}')
            print(f'Sort: {body.get("sort")}')
            print()

            results = body.get('results', [])
            if results:
                print(f'FIRST RESULT (full structure):')
                first = results[0]
                print(json.dumps(first, indent=2)[:3000])
                print()

                # Show metadata keys
                metadata = first.get('metadata', {})
                if metadata:
                    print(f'METADATA KEYS: {list(metadata.keys())}')
                    # Show first few values of each metadata field
                    for key, val in list(metadata.items())[:15]:
                        if isinstance(val, list):
                            print(f'  {key}: {val[:3]}')
                        else:
                            print(f'  {key}: {str(val)[:100]}')
        except Exception as e:
            print(f'Parse error: {e}')
            print(f'Raw preview: {call.get("body_preview", "")[:1000]}')

    # Facet API
    elif 'search-api' in url and 'rest/facet' in url:
        print('\n' + '='*80)
        print(f'FACET API CALL [{i+1}]')
        print(f'URL: {url}')
        try:
            body = json.loads(call.get('body_preview', '{}'))
            facets = body.get('facets', [])
            print(f'Number of facets: {len(facets)}')
            for facet in facets[:10]:
                print(f'  Facet: {facet.get("name")} — {facet.get("count")} values')
                for val in facet.get('values', [])[:3]:
                    print(f'    {val.get("rawValue")}: {val.get("count")} items')
        except Exception as e:
            print(f'Parse error: {e}')

    # Competitive calls
    elif 'competitive-calls.json' in url:
        print('\n' + '='*80)
        print(f'COMPETITIVE CALLS [{i+1}]')
        try:
            body = json.loads(call.get('body_preview', '{}'))
            calls = body.get('competitiveCalls', [])
            print(f'Number of competitive calls: {len(calls)}')
            if calls:
                print(f'First call keys: {list(calls[0].keys())}')
                first_call = calls[0].get('call', {})
                print(f'First call.call keys: {list(first_call.keys())}')
                print(f'First call title: {first_call.get("title")}')
        except Exception as e:
            print(f'Parse error: {e}')

    # Reference data
    elif 'topicdictionary' in url:
        print('\n' + '='*80)
        print(f'TOPIC DICTIONARY [{i+1}]')
        try:
            body = json.loads(call.get('body_preview', '{}'))
            for key in body:
                val = body[key]
                if isinstance(val, list):
                    print(f'  {key}: {len(val)} items')
                    for item in val[:3]:
                        print(f'    {item}')
                else:
                    print(f'  {key}: {str(val)[:100]}')
        except Exception as e:
            print(f'Parse error: {e}')


# Now examine the eui-card DOM structure
print('\n\n' + '='*80)
print('EUI-CARD DOM STRUCTURE')
print('='*80)
for page_name, pf in data.get('pages', {}).items():
    dom = pf.get('dom_structure', {})
    for sel, structures in dom.items():
        if 'card' in sel.lower():
            print(f'\nPage: {page_name}, Selector: {sel}')
            print(json.dumps(structures[:2], indent=2)[:3000])

    # Sample card HTML
    for card_group in pf.get('sample_cards_html', []):
        if 'card' in card_group.get('selector', '').lower():
            print(f'\nPage: {page_name}, Card selector: {card_group["selector"]}')
            for sample in card_group.get('samples', [])[:1]:
                print(f'Sample HTML (first 2000 chars):')
                print(sample[:2000])
