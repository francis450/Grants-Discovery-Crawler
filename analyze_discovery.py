import json

with open('eu_portal_discovery.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Show API calls - the most critical finding
print('='*80)
print(f'API CALLS INTERCEPTED: {len(data.get("api_calls", []))}')
print('='*80)
for i, call in enumerate(data.get('api_calls', [])):
    url = call.get('url', '')
    if any(x in url for x in ['api/', 'topic', 'call', 'search', 'competitive', 'grant']):
        method = call.get('method', '?')
        status = call.get('status', '?')
        print(f'\n[{i+1}] {method} {status} {url[:180]}')
        if call.get('json_keys'):
            print(f'   Keys: {call["json_keys"]}')
        for k in ['results_count', 'data_count', 'topics_count', 'calls_count', 
                   'topicDetails_count', 'competitiveCalls_count',
                   'json_array_length']:
            if k in call:
                print(f'   {k}: {call[k]}')
        for k in ['results_first_item_keys', 'data_first_item_keys', 
                   'topics_first_item_keys', 'calls_first_item_keys', 
                   'competitiveCalls_first_item_keys', 'json_first_item_keys']:
            if k in call:
                print(f'   First item keys: {call[k]}')
        if call.get('body_preview') and 'json' in call.get('content_type', ''):
            print(f'   Body preview: {call["body_preview"][:300]}')

print('\n\n')
print('='*80)
print('PAGE SUMMARIES')
print('='*80)
for page_name, pf in data.get('pages', {}).items():
    print(f'\n--- {page_name} ---')
    print(f'URL: {pf.get("url")}')
    print(f'Title: {pf.get("page_title")}')
    print(f'Custom elements: {pf.get("custom_elements", [])[:30]}')
    containers = pf.get('container_selectors', {})
    if containers:
        sorted_c = sorted(containers.items(), key=lambda x: x[1], reverse=True)[:15]
        print(f'Top containers:')
        for sel, count in sorted_c:
            print(f'  {sel}: {count}')
    pagination = pf.get('pagination', {})
    if pagination.get('selectors'):
        print(f'Pagination selectors: {list(pagination["selectors"].keys())}')
    if pagination.get('result_count_text'):
        for t in pagination['result_count_text'][:3]:
            print(f'  Result text: {t.get("text", "")[:80]}')
