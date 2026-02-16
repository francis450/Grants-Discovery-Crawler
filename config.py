# config.py

# ============================================================================
# SITE PROFILES CONFIGURATION
# ============================================================================
# List of site profiles to crawl (profiles are defined in site_profiles/)
# Available profiles: "fundsforngos" (more to be added)
ENABLED_SITES = [
    "fundsforngos",
    "eufundingportal",
    "charityexcellence",
    "globalgiving",
    "devex",
    "reliefweb",
    # "localtest",
]

# ============================================================================
# PAGINATION CONFIGURATION
# ============================================================================
# Maximum number of pages to crawl per URL (prevents infinite crawling)
MAX_PAGES = 20

# ============================================================================
# DATA VALIDATION CONFIGURATION
# ============================================================================
REQUIRED_KEYS = [
    "title",
    "description",
]

# Optional but valuable fields (grants missing these are still kept)
OPTIONAL_KEYS = [
    "deadline",
    "application_url",
    "funding_organization",
    "grant_amount",
    "geographic_focus",
    "thematic_areas",
    "eligibility_criteria",
    "category",
    "date_posted",
]

# Filtering Configuration
# Minimum days before deadline to consider a grant (skip if deadline is sooner or passed)
MIN_DEADLINE_DAYS = 3  # Skip grants with less than 3 days to apply

# Relevance scoring threshold (0-100)
# Updated scoring: 90-100=Perfect, 75-89=Strong, 60-74=Good, 50-59=Marginal, <50=Not relevant
# Recommended: Start with 60 to capture direct, strong, and adaptable matches
# You can lower to 55 temporarily to see what marginal grants look like, then adjust
MIN_RELEVANCE_SCORE = 60  # Only include grants scoring 60 or above

# ============================================================================
# LLM PROVIDER CONFIGURATION
# ============================================================================
# Choose the LLM provider for relevance scoring:
# - "groq": Groq (free tier: 30 RPM, very fast Llama 3.1 70B)
# - "gemini": Google Gemini (free tier: 15 RPM, 1M tokens/day)
# - "ollama": Local Ollama (requires ollama running locally)
RELEVANCE_PROVIDER = "xai"  # Options: "groq", "gemini", "ollama", "xai"

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
# SQLite database for persistent grant storage and cross-run deduplication
DB_PATH = "grants.db"

# Fuzzy deduplication: titles with similarity >= this threshold are considered duplicates
# Uses difflib.SequenceMatcher ratio (0.0 - 1.0)
DEDUP_SIMILARITY_THRESHOLD = 0.85

# ============================================================================
# EXCEL ONLINE CONFIGURATION (OneDrive Sync)
# ============================================================================
# Path to the shared Excel file in your OneDrive-synced folder.
# The crawler appends new grants to the specified sheet.
# Set to None to disable Excel export.
EXCEL_OUTPUT_PATH = "https://netorgft5302216-my.sharepoint.com/personal/daniela_v_dragonsino_com/Documents/TOH NON-PROFIT/Grant_Tracker_Database.xlsx"  # e.g. r"C:\Users\Francis\OneDrive\Shared\GrantsReview.xlsx"
EXCEL_SHEET_NAME = "From Automation"

