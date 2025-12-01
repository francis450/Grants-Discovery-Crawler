# Deep Seek Grants Crawler

This project is an AI-powered web crawler built with Python that extracts grant and funding opportunity data from **fundsforngos.org** using asynchronous programming with Crawl4AI. It utilizes a language model-based extraction strategy to intelligently parse grant information and saves the collected data to both CSV and JSON formats.

## Features

- **Asynchronous web crawling** using [Crawl4AI](https://pypi.org/project/Crawl4AI/)
- **LLM-powered data extraction** using xAI Grok-3 model
- **Multi-URL support** - Crawl multiple category/tag pages simultaneously
- **Two-stage intelligent filtering** - Optimized to reduce AI usage and processing time:
  - **Stage 1 (Listing Page)**: Fast preliminary relevance check on title + description
  - **Stage 2 (Full Page)**: Deep AI analysis only for candidates that pass initial filters
- **Smart deadline filtering** - Automatically skips grants with deadlines <7 days away or already passed
- **Mission-focused filtering** - Targets grants specifically for:
  - Nonprofit organizations providing refurbished IT equipment
  - Children in Africa closing the digital gap
  - Technology education in underserved schools
  - E-waste management and circular economy
- **Competition grant exclusion** - Automatically filters out contests, awards, and competitions
- **Dual output formats** - CSV and JSON for flexibility
- **Pagination handling** - Automatically crawls through multiple pages
- **Deduplication** - Prevents duplicate grant entries across all URLs
- **Modular code structure** - Easy to understand and extend

## Project Structure
```
.
├── main.py                 # Main entry point for the crawler
├── config.py               # Configuration constants (Base URL, CSS selectors, etc.)
├── models
│   ├── __init__.py         # Package exports
│   └── grant.py            # Defines the Grant data model using Pydantic
├── utils
│   ├── __init__.py         # Package marker for utils
│   ├── data_utils.py       # Utility functions for processing and saving data
│   └── scraper_utils.py    # Utility functions for configuring and running the crawler
├── requirements.txt        # Python package dependencies
├── .env.example            # Environment variable template
├── .gitignore              # Git ignore file
└── README.MD               # This file
```

## Installation

1. **Create and Activate a Conda Environment**

   ```bash
   conda create -n deep-seek-crawler python=3.12 -y
   conda activate deep-seek-crawler
   ```

2. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set Up Your Environment Variables**

   Create a `.env` file in the root directory with content similar to:

   ```env
   XAI_API_KEY=your_xai_api_key_here
   ```

   Get your xAI API key at [x.ai/api](https://x.ai/api)

   *(Note: The `.env` file is in your .gitignore, so it won't be pushed to version control.)*

## Usage

To start the crawler, run:

```bash
python main.py
```

The script will:
1. Crawl all URLs configured in `GRANT_URLS` (in [config.py](config.py))
2. Extract grant data page by page using AI (Stage 1 - Listing page analysis)
3. Apply fast filters:
   - Check deadline (must be >3 days away by default)
   - Preliminary relevance check (competition? nonprofit? children in Africa? digital gap?)
4. For grants that pass initial filters:
   - Fetch full grant page content (Stage 2 - Deep analysis)
   - Analyze detailed relevance against your specific mission
5. Filter grants based on relevance score (60+ = relevant)
6. Validate grant information and remove duplicates
7. Save relevant grants to:
   - `grants_output.csv` - CSV format with all fields including relevance scores
   - `grants_output.json` - JSON format (preserves list structures)
8. Display LLM usage statistics (tokens used, cost, etc.)

## Extracted Grant Fields

Each grant entry includes the following information:

| Field                       | Description                                           |
|-----------------------------|-------------------------------------------------------|
| `title`                     | Grant title or funding opportunity name              |
| `funding_organization`      | Donor or funder name                                  |
| `grant_amount`              | Funding amount or range (if specified)                |
| `deadline`                  | Application deadline or submission date               |
| `geographic_focus`          | Eligible countries/regions                            |
| `thematic_areas`            | Focus sectors (list)                                  |
| `eligibility_criteria`      | Organization types accepted                           |
| `description`               | Grant summary or description                          |
| `application_url`           | Link to apply or read more                            |
| `category`                  | Grant category (if available)                         |
| `date_posted`               | Date the grant was posted (if available)              |
| `is_relevant_preliminary`   | Stage 1 filter result (from listing page)             |
| `relevance_score`           | Stage 2 AI-calculated relevance score (0-100)         |
| `relevance_reasoning`       | Explanation of why the grant is relevant              |
| `how_it_helps`              | **Actionable explanation** of HOW to use this grant (acquire/provide/maintain equipment) |
| `matching_themes`           | List of matching themes from your mission             |

**Note:** Fields marked as `null` were not available on the source page.

### Understanding the "how_it_helps" Field

The `how_it_helps` field is the most important field for determining grant quality. It provides a **specific, actionable explanation** of how you can use this grant for your mission, focusing on one or more of these areas:

1. **Acquiring IT Equipment**: Can fund purchasing new equipment, sourcing old equipment, or partnerships with e-waste collectors
2. **Providing/Distributing Equipment**: Can fund logistics, installation, or staffing for distribution programs
3. **Maintaining Equipment & Program**: Can fund technical staff, spare parts, training, or ongoing operations

**Example outputs:**
- ✅ **Good**: "This grant funds computer lab setup in rural African schools, which directly covers the cost of distributing our refurbished laptops and installing them in classrooms in underserved areas."
- ✅ **Good**: "This grant supports e-waste recycling programs in Kenya, which we can use to fund partnerships with local e-waste collectors to source discarded IT equipment for refurbishment."
- ❌ **Bad** (would be rejected): "This grant aligns with our mission of helping children in Africa."

This ensures you only save grants with a **clear path to implementation**, not just thematic alignment.

## Configuration

The [config.py](config.py) file contains key constants:

### URL Configuration
- **GRANT_URLS**: List of URLs to crawl (supports category pages, tag pages, etc.)
  - Example: `["https://www2.fundsforngos.org/latest-funds-for-ngos"]`
  - Add more URLs to target specific categories:
    - Kenya: `https://www2.fundsforngos.org/tag/funding-opportunities-and-resources-in-kenya/`
    - Education: `https://www2.fundsforngos.org/category/education/`
    - Environment: `https://www2.fundsforngos.org/category/environment/`
    - Children/Youth: `https://www2.fundsforngos.org/category/children/`
- **CSS_SELECTOR**: `article.post, article.entry` (targets grant article elements)

### Data Validation
- **REQUIRED_KEYS**: `["title", "deadline", "description", "application_url"]`
- **OPTIONAL_KEYS**: Additional valuable fields that enhance grant information

### Filtering Configuration
- **MIN_DEADLINE_DAYS**: `3` - Skip grants with deadlines less than 3 days away or already passed
  - Increase this value if you need more time to prepare applications
  - Decrease to capture more urgent opportunities
- **MIN_RELEVANCE_SCORE**: `60` - Only include grants scoring 60 or above (0-100 scale)
  - Increase for more selective filtering (e.g., 70 for only strong matches)
  - Decrease to capture more opportunities (e.g., 50 for broader results)

You can modify these values to scrape different grant websites or adjust filtering behavior to match your workflow.

## How It Works

### Optimized Two-Stage Filtering Process

1. **Multi-URL Crawling**: Iterates through all URLs configured in `GRANT_URLS`
2. **Browser Automation**: Uses Chromium via Crawl4AI to handle JavaScript-rendered pages
3. **Smart Pagination**: Automatically detects and crawls through multiple pages (`/page/2/`, `/page/3/`, etc.)
4. **Stage 1 - Listing Page Extraction**: Sends listing page content to Grok-3 with structured instructions to extract:
   - Basic grant information (title, deadline, description, etc.)
   - **Preliminary relevance check**: AI evaluates if grant meets core requirements:
     - NOT a competition/contest/award
     - FOR nonprofit organizations
     - ABOUT helping children in Africa close the digital gap
5. **Fast Filtering**: Applies quick filters BEFORE fetching full pages:
   - ✅ **Completeness check**: Has all required fields
   - ✅ **Duplicate check**: Not already seen
   - ✅ **Deadline check**: More than 7 days away (configurable)
   - ✅ **Preliminary relevance**: Passed initial AI screening
6. **Stage 2 - Deep Content Analysis**: Only for grants that pass Stage 1, fetches the full application page
7. **AI Relevance Scoring**: Analyzes full grant content against specific mission (0-100 score)
8. **Final Filtering**: Only includes grants scoring 60+ in relevance
9. **Schema Validation**: Uses Pydantic models to ensure data quality
10. **Enhanced Metadata**: Adds relevance score, reasoning, and matching themes to each grant

**Performance Impact**: This two-stage approach reduces full page fetches and deep AI analysis by ~70-80%, significantly lowering processing time and API costs.

## Customization

### Adding More URLs

To crawl additional category or tag pages:

1. Open [config.py](config.py)
2. Add URLs to the `GRANT_URLS` list:
   ```python
   GRANT_URLS = [
       "https://www2.fundsforngos.org/latest-funds-for-ngos",
       "https://www2.fundsforngos.org/tag/funding-opportunities-and-resources-in-kenya/",
       "https://www2.fundsforngos.org/category/education/",
       "https://www2.fundsforngos.org/category/environment/",
   ]
   ```
3. The crawler will automatically process all URLs and deduplicate grants

### Targeting Different Websites

To scrape a different grants website:

1. Update URLs in `GRANT_URLS` in [config.py](config.py)
2. Inspect the target website and update `CSS_SELECTOR` to target grant containers
3. Adjust the LLM extraction instructions in [utils/scraper_utils.py](utils/scraper_utils.py)
4. Modify the Grant model in [models/grant.py](models/grant.py) if different fields are needed

### Adjusting Crawl Behavior

- **Speed**: Change `await asyncio.sleep(2)` in [main.py](main.py) to adjust delay between requests
- **Page Limit**: Add a max page counter in the while loop to limit crawling
- **Headless Mode**: Set `headless=True` in [utils/scraper_utils.py](utils/scraper_utils.py):17 to run without UI

## Cost Considerations

This project uses xAI's Grok-3 model for intelligent grant extraction and filtering.

**Optimized for Efficiency:**
- **Two-stage filtering** reduces full page fetches by ~70-80%
- Only deeply analyzes grants that pass preliminary checks
- Significantly lower API costs compared to analyzing every grant
- Fast inference times with strategic filtering

**Example Cost Savings:**
- Before optimization: 100 grants = 100 full page analyses
- After optimization: 100 grants = 20-30 full page analyses (70-80% reduction)
- Deadline and preliminary filters eliminate most irrelevant grants early

The crawler will display detailed token usage and estimated costs after completion, allowing you to track efficiency improvements.

## Troubleshooting

**Issue**: "No grants extracted from page 1"
- The website may have anti-bot protection (ShopShield)
- Try setting `headless=False` to see what's happening
- Check if the CSS selector is correct

**Issue**: Missing grant fields
- The LLM may not find all information on listing pages
- Consider crawling individual grant detail pages for complete data

**Issue**: XAI_API_KEY error
- Ensure you've created a `.env` file with your xAI API key
- Get an API key at [x.ai/api](https://x.ai/api)

## Additional Notes

- **Logging**: Currently uses print statements. Consider integrating Python's `logging` module for production
- **Rate Limiting**: Includes 2-second delays between requests to be polite to servers
- **Data Quality**: Only saves grants with required fields (title, deadline, description, URL)
- **Extensibility**: Modular design makes it easy to adapt for other websites

## License

MIT License - Feel free to use and modify for your projects.
