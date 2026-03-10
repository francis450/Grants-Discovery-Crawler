"""
EC Europa Funding & Tenders Portal — Discovery Script
=====================================================
Navigates the EU Funding & Tenders Opportunities Portal with Playwright,
intercepts API calls, maps DOM structure, and captures selectors needed
to build a site profile for grant scraping.

Target: https://ec.europa.eu/info/funding-tenders/opportunities/portal/
"""

import asyncio
import json
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from utils.playwright_utils import create_stealth_context, new_stealth_page

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

PAGES_TO_EXPLORE = [
    {
        "name": "Topic Search",
        "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search",
    },
    {
        "name": "Calls for Proposals",
        "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals",
    },
    {
        "name": "Competitive Calls (Open)",
        "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/competitive-calls",
    },
]

DISCOVERY_OUTPUT = "eu_portal_discovery.json"
DISCOVERY_TEXT   = "eu_portal_discovery.txt"

# ──────────────────────────────────────────────────────────────────────
# Network interception — capture API endpoints
# ──────────────────────────────────────────────────────────────────────

api_calls = []

def make_response_handler(page_name):
    """Create a response handler that tags captured calls with the page name."""
    async def on_response(response):
        url = response.url
        # Capture JSON API calls (skip static assets)
        if any(pattern in url for pattern in [
            "/api/", "/rest/", "/search", "application/json",
            "sedia.", "funding-tenders", "/topics", "/calls",
            "grants", "/programmes",
        ]):
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "javascript" not in content_type:
                entry = {
                    "page": page_name,
                    "url": url,
                    "status": response.status,
                    "content_type": content_type,
                    "method": response.request.method,
                }
                # Try to capture a snippet of the response body
                try:
                    body = await response.text()
                    entry["body_length"] = len(body)
                    # Store first 2000 chars for inspection
                    entry["body_preview"] = body[:2000]
                    # If it's JSON, try to parse and summarize keys
                    if "json" in content_type:
                        try:
                            data = json.loads(body)
                            if isinstance(data, dict):
                                entry["json_keys"] = list(data.keys())
                                # If there's a results array, show its length and first item keys
                                for key in ["results", "data", "items", "content", "topics", "calls", "topicDetails"]:
                                    if key in data and isinstance(data[key], list):
                                        entry[f"{key}_count"] = len(data[key])
                                        if data[key]:
                                            entry[f"{key}_first_item_keys"] = list(data[key][0].keys()) if isinstance(data[key][0], dict) else type(data[key][0]).__name__
                            elif isinstance(data, list):
                                entry["json_array_length"] = len(data)
                                if data and isinstance(data[0], dict):
                                    entry["json_first_item_keys"] = list(data[0].keys())
                        except json.JSONDecodeError:
                            pass
                except Exception:
                    entry["body_preview"] = "<could not read>"

                api_calls.append(entry)
    return on_response


# ──────────────────────────────────────────────────────────────────────
# DOM structure extraction
# ──────────────────────────────────────────────────────────────────────

async def extract_dom_structure(page, selector, max_depth=6):
    """
    Extract the DOM tree under elements matching `selector`.
    Returns a list of element descriptions with tag, classes, id, 
    data attributes, text preview, and children count.
    """
    return await page.evaluate("""
        (args) => {
            const { selector, maxDepth } = args;
            function describeElement(el, depth) {
                if (depth > maxDepth || !el) return null;
                const children = Array.from(el.children).map(c => describeElement(c, depth + 1)).filter(Boolean);
                const text = el.childNodes.length > 0 
                    ? Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .filter(t => t.length > 0)
                        .join(' ')
                        .substring(0, 100)
                    : '';
                
                const attrs = {};
                for (const attr of el.attributes) {
                    if (attr.name.startsWith('data-') || attr.name === 'role' || attr.name === 'aria-label') {
                        attrs[attr.name] = attr.value.substring(0, 100);
                    }
                }
                
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || null,
                    classes: Array.from(el.classList).join(' ') || null,
                    attrs: Object.keys(attrs).length ? attrs : null,
                    text: text || null,
                    href: el.href || null,
                    childCount: el.children.length,
                    children: children.length > 0 ? children : null,
                };
            }
            const elements = document.querySelectorAll(selector);
            return Array.from(elements).slice(0, 5).map(el => describeElement(el, 0));
        }
    """, {"selector": selector, "maxDepth": max_depth})


async def find_grant_containers(page):
    """
    Try multiple common selectors to find the grant listing containers.
    Returns the first successful selector and its DOM structure.
    """
    # Common patterns for Angular/SPA sites and the EU portal specifically
    candidate_selectors = [
        # EU portal-specific Angular custom elements
        "eui-card",
        "app-topic-card",
        "app-call-card",
        "app-result-card",
        "app-topic-search-result",
        "app-call-search-result",
        # General card/list patterns
        "[class*='topic-']",
        "[class*='call-']",
        "[class*='result-']",
        "[class*='card']",
        "[class*='grant']",
        "[class*='funding']",
        "sedia-card",
        "sedia-result",
        # Table-based results
        "table.results tbody tr",
        "table[class*='result'] tbody tr",
        # Generic list patterns
        ".search-results > *",
        ".results-list > *",
        ".topic-list > *",
        ".call-list > *",
        "mat-card",
        "mat-list-item",
        # Data attribute patterns
        "[data-topic]",
        "[data-call]",
        "[data-result]",
        # Try all custom elements (Web Components)
        "main *:not(div):not(span):not(p):not(a):not(ul):not(li):not(h1):not(h2):not(h3):not(h4):not(h5):not(h6):not(img):not(button):not(input):not(select):not(form):not(table):not(thead):not(tbody):not(tr):not(td):not(th):not(nav):not(header):not(footer):not(section):not(article):not(style):not(script):not(link):not(meta):not(br):not(hr):not(label):not(option):not(textarea):not(strong):not(em):not(b):not(i):not(small):not(svg):not(path):not(g):not(circle)",
    ]

    results = {}
    for sel in candidate_selectors:
        try:
            count = await page.evaluate(f"document.querySelectorAll('{sel}').length")
            if count > 0:
                results[sel] = count
        except Exception:
            pass

    return results


async def get_all_custom_elements(page):
    """Find all custom HTML elements (Web Components / Angular components) on the page."""
    return await page.evaluate("""
        () => {
            const all = document.querySelectorAll('*');
            const customElements = new Set();
            for (const el of all) {
                const tag = el.tagName.toLowerCase();
                if (tag.includes('-') && !tag.startsWith('font-')) {
                    customElements.add(tag);
                }
            }
            return Array.from(customElements).sort();
        }
    """)


async def get_sample_cards_html(page, selector, count=3):
    """Get the outerHTML of the first N elements matching selector."""
    return await page.evaluate("""
        (args) => {
            const { selector, count } = args;
            const elements = document.querySelectorAll(selector);
            return Array.from(elements).slice(0, count).map(el => el.outerHTML);
        }
    """, {"selector": selector, "count": count})


async def get_pagination_info(page):
    """Find pagination controls and their structure."""
    pagination_selectors = [
        "eui-paginator",
        "mat-paginator",
        "[class*='pagination']",
        "[class*='paginator']",
        "[class*='pager']",
        "nav[aria-label*='page']",
        "nav[aria-label*='Page']",
        ".page-link",
        ".page-item",
        "button[aria-label*='Next']",
        "button[aria-label*='next']",
        "a[aria-label*='Next']",
        "[class*='next-page']",
        "[class*='nextPage']",
    ]

    results = {}
    for sel in pagination_selectors:
        try:
            count = await page.evaluate(f"document.querySelectorAll('{sel}').length")
            if count > 0:
                # Get outerHTML of first match
                html = await page.evaluate(f"document.querySelector('{sel}').outerHTML.substring(0, 500)")
                results[sel] = {"count": count, "html_preview": html}
        except Exception:
            pass

    # Also look for "Showing X of Y" type text
    total_text = await page.evaluate("""
        () => {
            const all = document.querySelectorAll('*');
            const matches = [];
            for (const el of all) {
                const text = el.textContent.trim();
                if ((text.match(/\\d+\\s*(of|out of|results|topics|calls|items|total|found)/i) ||
                     text.match(/(showing|displaying|page)\\s*\\d+/i)) &&
                    text.length < 100 && el.children.length < 3) {
                    matches.push({
                        tag: el.tagName.toLowerCase(),
                        classes: el.className,
                        text: text,
                    });
                }
            }
            return matches.slice(0, 10);
        }
    """)

    return {"selectors": results, "result_count_text": total_text}


async def get_filter_sidebar(page):
    """Find filter/facet controls on the page."""
    return await page.evaluate("""
        () => {
            // Look for filter-related elements
            const filterSelectors = [
                '[class*="filter"]', '[class*="facet"]', '[class*="sidebar"]',
                '[class*="programme"]', '[class*="status"]', '[class*="type"]',
                'select', 'mat-select', 'eui-select', 'eui-dropdown',
                '[role="listbox"]', '[role="combobox"]',
                'input[type="checkbox"]', 'mat-checkbox', 'eui-checkbox',
            ];
            
            const results = {};
            for (const sel of filterSelectors) {
                const elements = document.querySelectorAll(sel);
                if (elements.length > 0) {
                    results[sel] = {
                        count: elements.length,
                        samples: Array.from(elements).slice(0, 3).map(el => ({
                            tag: el.tagName.toLowerCase(),
                            id: el.id || null,
                            classes: el.className ? el.className.substring(0, 200) : null,
                            text: el.textContent.trim().substring(0, 150),
                            aria: el.getAttribute('aria-label') || null,
                        }))
                    };
                }
            }
            return results;
        }
    """)


async def dismiss_cookie_banner(page):
    """Try to dismiss the cookie consent banner."""
    cookie_selectors = [
        "button:has-text('Accept all')",
        "button:has-text('Accept All')",
        "button:has-text('Accept cookies')",
        "button:has-text('Accept')",
        "button:has-text('I agree')",
        "button:has-text('OK')",
        "button:has-text('Agree')",
        "#cookie-consent-banner button",
        ".cookie-banner button",
        ".cck-actions-button",
        "[class*='cookie'] button",
        "[id*='cookie'] button",
        "button[class*='accept']",
        "a.wt-ecl-button--primary",  # EU cookie consent specific
    ]
    for sel in cookie_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                print(f"  ✓ Dismissed cookie banner via: {sel}")
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
    return False


# ──────────────────────────────────────────────────────────────────────
# Main exploration routine
# ──────────────────────────────────────────────────────────────────────

async def explore():
    findings = {
        "timestamp": datetime.now().isoformat(),
        "pages": {},
        "api_calls": [],
    }

    async with async_playwright() as p:
        browser, context = await create_stealth_context(p, headless=False)

        for page_info in PAGES_TO_EXPLORE:
            page_name = page_info["name"]
            url = page_info["url"]
            print(f"\n{'='*80}")
            print(f"Exploring: {page_name}")
            print(f"URL: {url}")
            print(f"{'='*80}")

            page = await new_stealth_page(context)

            # Wire up API interception
            page.on("response", make_response_handler(page_name))

            page_findings = {
                "url": url,
                "custom_elements": [],
                "container_selectors": {},
                "sample_cards_html": [],
                "dom_structure": {},
                "pagination": {},
                "filters": {},
                "cookie_banner_dismissed": False,
                "page_title": "",
                "best_card_selector": None,
            }

            try:
                # Navigate with generous timeout
                print(f"  Navigating to {url} ...")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Wait for SPA to render — try multiple strategies
                print("  Waiting for SPA content to load ...")
                await page.wait_for_timeout(3000)  # Initial wait for Angular bootstrap
                
                # Try to wait for network to settle
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    print("  (networkidle timeout — continuing)")

                # Additional wait for dynamic content
                await page.wait_for_timeout(3000)

                # Dismiss cookie banner
                page_findings["cookie_banner_dismissed"] = await dismiss_cookie_banner(page)
                await page.wait_for_timeout(1000)

                # Get page title
                page_findings["page_title"] = await page.title()
                print(f"  Page title: {page_findings['page_title']}")

                # ── Step 1: Find all custom elements (Web Components / Angular) ──
                print("  Finding custom elements ...")
                custom_elements = await get_all_custom_elements(page)
                page_findings["custom_elements"] = custom_elements
                print(f"  Found {len(custom_elements)} custom elements: {custom_elements[:20]}")

                # ── Step 2: Find grant containers ──
                print("  Scanning for grant listing containers ...")
                containers = await find_grant_containers(page)
                page_findings["container_selectors"] = containers
                if containers:
                    sorted_containers = sorted(containers.items(), key=lambda x: x[1], reverse=True)
                    print(f"  Found potential containers:")
                    for sel, count in sorted_containers[:15]:
                        print(f"    {sel}: {count} elements")

                # ── Step 3: Get DOM structure for the most promising selectors ──
                print("  Extracting DOM structure of top containers ...")
                # Also try custom elements that look like cards/results
                card_candidates = [el for el in custom_elements if any(
                    kw in el.lower() for kw in ['card', 'result', 'topic', 'call', 'item', 'row', 'list']
                )]
                print(f"  Card-like custom elements: {card_candidates}")

                # Try to get DOM structure for the most likely selectors
                selectors_to_inspect = list(card_candidates) + [
                    sel for sel, count in sorted(containers.items(), key=lambda x: x[1])
                    if 2 <= count <= 100  # Reasonable number of results
                ][:10]

                for sel in selectors_to_inspect[:8]:
                    try:
                        structure = await extract_dom_structure(page, sel, max_depth=4)
                        if structure:
                            page_findings["dom_structure"][sel] = structure
                            print(f"  DOM structure for '{sel}': {len(structure)} elements captured")
                    except Exception as e:
                        print(f"  Could not extract DOM for '{sel}': {e}")

                # ── Step 4: Get sample card HTML ──
                print("  Capturing sample card HTML ...")
                for sel in (card_candidates + list(containers.keys()))[:5]:
                    try:
                        samples = await get_sample_cards_html(page, sel, count=2)
                        if samples:
                            page_findings["sample_cards_html"].append({
                                "selector": sel,
                                "samples": [s[:3000] for s in samples],  # Limit size
                            })
                            print(f"  Captured {len(samples)} samples for '{sel}'")
                    except Exception as e:
                        print(f"  Could not capture samples for '{sel}': {e}")

                # ── Step 5: Pagination info ──
                print("  Inspecting pagination controls ...")
                pagination = await get_pagination_info(page)
                page_findings["pagination"] = pagination
                if pagination["selectors"]:
                    print(f"  Pagination selectors found: {list(pagination['selectors'].keys())}")
                if pagination["result_count_text"]:
                    print(f"  Result count text: {pagination['result_count_text'][:3]}")

                # ── Step 6: Filters ──
                print("  Inspecting filter controls ...")
                filters = await get_filter_sidebar(page)
                page_findings["filters"] = filters
                if filters:
                    print(f"  Filter selectors found: {list(filters.keys())[:10]}")

                # ── Step 7: Take a screenshot ──
                screenshot_path = f"eu_portal_{page_name.replace(' ', '_').lower()}.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                print(f"  Screenshot saved: {screenshot_path}")

                # ── Step 8: Get the full page HTML for offline analysis ──
                full_html = await page.content()
                html_path = f"eu_portal_{page_name.replace(' ', '_').lower()}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(full_html)
                print(f"  Full HTML saved: {html_path} ({len(full_html)} chars)")

            except Exception as e:
                print(f"  ERROR exploring {page_name}: {e}")
                page_findings["error"] = str(e)

            finally:
                findings["pages"][page_name] = page_findings
                await page.close()

        # Close browser
        await browser.close()

    # ── Store captured API calls ──
    findings["api_calls"] = api_calls
    print(f"\n{'='*80}")
    print(f"NETWORK INTERCEPTION RESULTS")
    print(f"{'='*80}")
    print(f"Captured {len(api_calls)} API responses")
    for i, call in enumerate(api_calls):
        print(f"\n  [{i+1}] {call['method']} {call['status']} — {call['url'][:120]}")
        if call.get("json_keys"):
            print(f"      JSON keys: {call['json_keys']}")
        for key in ["results_count", "data_count", "items_count", "topics_count", "calls_count", "topicDetails_count"]:
            if key in call:
                print(f"      {key}: {call[key]}")
        if call.get("results_first_item_keys"):
            print(f"      First result keys: {call['results_first_item_keys']}")
        if call.get("data_first_item_keys"):
            print(f"      First data item keys: {call['data_first_item_keys']}")
        if call.get("topics_first_item_keys"):
            print(f"      First topic keys: {call['topics_first_item_keys']}")

    # ── Write JSON output ──
    with open(DISCOVERY_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2, default=str)
    print(f"\nFull findings written to: {DISCOVERY_OUTPUT}")

    # ── Write human-readable summary ──
    write_text_summary(findings)
    print(f"Text summary written to: {DISCOVERY_TEXT}")


def write_text_summary(findings):
    """Generate a human-readable text summary of the discovery findings."""
    lines = []
    lines.append("=" * 80)
    lines.append("EC EUROPA FUNDING & TENDERS PORTAL — DISCOVERY REPORT")
    lines.append(f"Generated: {findings['timestamp']}")
    lines.append("=" * 80)

    for page_name, pf in findings["pages"].items():
        lines.append(f"\n{'─'*80}")
        lines.append(f"PAGE: {page_name}")
        lines.append(f"URL:  {pf['url']}")
        lines.append(f"Title: {pf.get('page_title', 'N/A')}")
        lines.append(f"Cookie banner dismissed: {pf.get('cookie_banner_dismissed')}")
        lines.append(f"{'─'*80}")

        lines.append(f"\n  CUSTOM ELEMENTS ({len(pf.get('custom_elements', []))}):")
        for el in pf.get("custom_elements", []):
            lines.append(f"    <{el}>")

        lines.append(f"\n  CONTAINER SELECTORS:")
        for sel, count in sorted(pf.get("container_selectors", {}).items(), key=lambda x: x[1], reverse=True)[:20]:
            lines.append(f"    {sel}: {count} elements")

        lines.append(f"\n  DOM STRUCTURE:")
        for sel, structures in pf.get("dom_structure", {}).items():
            lines.append(f"\n    Selector: {sel}")
            for i, s in enumerate(structures[:2]):
                lines.append(f"    Element {i+1}: <{s.get('tag')}> .{s.get('classes')} #{s.get('id')}")
                if s.get("children"):
                    for child in s["children"][:5]:
                        lines.append(f"      └ <{child.get('tag')}> .{child.get('classes')} text='{child.get('text', '')[:60]}'")
                        if child.get("children"):
                            for gc in child["children"][:3]:
                                lines.append(f"          └ <{gc.get('tag')}> .{gc.get('classes')} text='{gc.get('text', '')[:60]}'")

        lines.append(f"\n  SAMPLE CARD HTML:")
        for card_group in pf.get("sample_cards_html", [])[:3]:
            lines.append(f"    Selector: {card_group['selector']}")
            for j, sample in enumerate(card_group.get("samples", [])[:1]):
                lines.append(f"    Sample {j+1} (first 1000 chars):")
                lines.append(f"    {sample[:1000]}")

        lines.append(f"\n  PAGINATION:")
        pagination = pf.get("pagination", {})
        for sel, info in pagination.get("selectors", {}).items():
            lines.append(f"    {sel}: {info.get('count')} elements")
            lines.append(f"      HTML: {info.get('html_preview', '')[:200]}")
        for text_info in pagination.get("result_count_text", [])[:5]:
            lines.append(f"    Result text: <{text_info.get('tag')}> '{text_info.get('text', '')[:80]}'")

        lines.append(f"\n  FILTERS:")
        for sel, info in pf.get("filters", {}).items():
            lines.append(f"    {sel}: {info.get('count')} elements")
            for sample in info.get("samples", [])[:2]:
                lines.append(f"      <{sample.get('tag')}> .{sample.get('classes', '')[:60]} text='{sample.get('text', '')[:60]}'")

    lines.append(f"\n{'='*80}")
    lines.append("API CALLS INTERCEPTED")
    lines.append(f"{'='*80}")
    for i, call in enumerate(findings.get("api_calls", [])):
        lines.append(f"\n  [{i+1}] {call.get('method')} {call.get('status')} — {call.get('url', '')[:150]}")
        lines.append(f"      Content-Type: {call.get('content_type', 'N/A')}")
        lines.append(f"      Body length: {call.get('body_length', 'N/A')}")
        if call.get("json_keys"):
            lines.append(f"      JSON top-level keys: {call['json_keys']}")
        for key in ["results_count", "data_count", "items_count", "topics_count", "calls_count", "topicDetails_count"]:
            if key in call:
                lines.append(f"      {key}: {call[key]}")
        for key in ["results_first_item_keys", "data_first_item_keys", "topics_first_item_keys", "calls_first_item_keys"]:
            if key in call:
                lines.append(f"      First item keys: {call[key]}")
        if call.get("body_preview"):
            lines.append(f"      Body preview: {call['body_preview'][:300]}")

    with open(DISCOVERY_TEXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(explore())
