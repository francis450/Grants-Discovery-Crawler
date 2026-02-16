# Copilot Instructions - Grants Crawler

## Project Overview
AI-powered async web crawler extracting NGO grant opportunities using Crawl4AI + LLM-based extraction. Mission-focused: IT equipment refurbishment for African schools. Grants are stored in SQLite, exported to CSV/JSON, and synced to a shared Excel Online sheet via OneDrive.

## Architecture

### Site Profile Pattern (Plugin Architecture)
New grant websites are added via **site profiles** in `site_profiles/`:
1. Create class extending `BaseSiteProfile` in `site_profiles/`
2. Implement required methods: `get_page_url()`, `detect_end_of_results()`
3. Define `site_name`, `base_urls`, `css_selector`, `pagination_type`
4. Register in `site_profiles/__init__.py` → `AVAILABLE_PROFILES` dict
5. Enable in `config.py` → `ENABLED_SITES` list

Reference: `site_profiles/fundsforngos.py` for path-based pagination, `site_profiles/globalgiving.py` for query-based.

### Two-Stage Filtering Pipeline
```
Listing Page → Stage 1 (Fast LLM)  → Stage 2 (Deep LLM) → Output
              is_relevant_preliminary    relevance_score ≥ MIN_RELEVANCE_SCORE (60)
```
- **Stage 1**: Quick relevance check on listing page content via LLM extraction
- **Stage 2**: Full page fetch + deep analysis via `analyze_grant_relevance()` in `utils/scraper_utils.py`; falls back to provider-specific analysis if full-page fetch fails
- Relevance prompt requires **3 of 5** minimum criteria (not all 5)
- Numeric score threshold (`MIN_RELEVANCE_SCORE`) is the actual filter, not the boolean `is_relevant`

### Data Flow
```
main.py → site_profiles/*.py → utils/scraper_utils.py → utils/<provider>_utils.py
                                      ↓
                              utils/db_utils.py    → SQLite (grants.db)
                              utils/data_utils.py  → CSV/JSON output
                              utils/excel_utils.py → OneDrive-synced .xlsx
```

### Storage Layers
- **SQLite** (`grants.db`): Persistent storage with cross-run fuzzy deduplication (title similarity ≥ 0.85 + exact URL match). Configured in `config.py` → `DB_PATH`
- **CSV/JSON**: Incremental saves during crawl for debugging. Overwritten each run.
- **Excel Online**: New grants appended to shared workbook's "From Automation" sheet at end of run. Configured via `EXCEL_OUTPUT_PATH` in `config.py`. Syncs via OneDrive.

### Grant Data Model
Grants flow as **plain dicts** throughout the pipeline (not Pydantic instances). The `Grant` model in `models/grant.py` is used only for schema generation (`model_json_schema()`) and CSV column ordering (`model_fields.keys()`).

Required fields: `title`, `description`  
Optional but valuable: `deadline`, `application_url`, `funding_organization`, `grant_amount`, `geographic_focus`, `thematic_areas`, `eligibility_criteria`

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | `ENABLED_SITES`, thresholds, DB/Excel paths, LLM provider |
| `models/grant.py` | Pydantic schema (used for LLM schema + CSV columns) |
| `site_profiles/base_profile.py` | Abstract base for site plugins |
| `utils/scraper_utils.py` | Core crawl logic, LLM strategies, filtering pipeline |
| `utils/db_utils.py` | SQLite storage, fuzzy deduplication |
| `utils/excel_utils.py` | Excel Online export via OneDrive sync |
| `utils/xai_utils.py` | Primary LLM provider (xAI Grok) |

## LLM Provider Cascade
Order configured in `get_llm_strategy()` in `utils/scraper_utils.py`:
1. **xAI** (primary) - `XAI_API_KEY` → grok-4-1-fast-reasoning
2. **Ollama** (local) - `USE_LOCAL_LLM=true` → llama3.1
3. **Gemini** - `GEMINI_API_KEY` → gemini-1.5-flash
4. **Groq** (fallback) - `GROQ_API_KEY` → llama-3.1-8b-instant

Relevance scoring provider set via `RELEVANCE_PROVIDER` in config.py.

## Conventions

### Adding a New Site Profile
```python
# site_profiles/example.py
class ExampleProfile(BaseSiteProfile):
    site_name = "Example Site"
    base_urls = ["https://example.com/grants/"]
    css_selector = "div.grant-item"
    pagination_type = "query"  # "path", "query", or "none"
    
    def get_page_url(self, base_url: str, page_number: int) -> str:
        return f"{base_url}?page={page_number}" if page_number > 1 else base_url
    
    async def detect_end_of_results(self, crawler, url, session_id) -> bool:
        # Return True when no more results
```
Then register in `site_profiles/__init__.py` and add to `ENABLED_SITES` in `config.py`.

## Commands
```bash
# Run crawler
python main.py

# Setup
conda create -n deep-seek-crawler python=3.12 -y
conda activate deep-seek-crawler
pip install -r requirements.txt
```

## Environment Variables
```env
XAI_API_KEY=...          # Primary (required)
GROQ_API_KEY=...         # Fallback
GEMINI_API_KEY=...       # Alternative
USE_LOCAL_LLM=true       # Use Ollama instead
```

## Configuration (config.py)
- `EXCEL_OUTPUT_PATH`: Set to the full path of the shared .xlsx in your OneDrive folder (or `None` to disable)
- `DB_PATH`: SQLite file location (default: `grants.db` in project root)
- `DEDUP_SIMILARITY_THRESHOLD`: Fuzzy title matching threshold (default: 0.85)
- `MIN_RELEVANCE_SCORE`: Score cutoff for grants (default: 60)
- `MIN_DEADLINE_DAYS`: Skip grants with deadlines sooner than N days (default: 3)

## Testing
Use `localtest` profile with local HTML file (`test_grants_page.html`) for development:
```python
# config.py
ENABLED_SITES = ["localtest"]
```
