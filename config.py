# config.py
import os
from dotenv import load_dotenv
load_dotenv()

# ============================================================================
# SITE PROFILES CONFIGURATION
# ============================================================================
# List of site profiles to crawl (profiles are defined in site_profiles/)
# Available profiles: "fundsforngos" (more to be added)
ENABLED_SITES = [
    # "grants_gov",  # API-based (Fast)
    "fundsforngos",
    "eufundingportal",
    "charityexcellence",
    # "globalgiving",
    "devex",
    "ictworks",  # disabled for devaid test
    "developmentaid",
    "eceuropa",  # EU Funding & Tenders Portal API
    "instrumentl",  # Instrumentl grant browse (Playwright, card-based)
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
MIN_RELEVANCE_SCORE = 70  # Only include grants scoring 70 or above

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
# EARLY STOP CONFIGURATION
# ============================================================================
# Stop paginating a URL when an entire page consists of already-known grants.
# Most listing sites sort newest-first, so an all-duplicate page means no new
# content remains on deeper pages — saves LLM extraction calls.
EARLY_STOP_ON_ALL_DUPLICATES = True

# ============================================================================
# STALE POSTING FILTER
# ============================================================================
# When a grant has no extractable deadline, fall back to posting date as a proxy.
# Grants posted more than this many days ago with no deadline are rejected as
# likely expired. Set to 0 to disable.
MAX_POSTING_AGE_DAYS = 60

# ============================================================================
# EXCEL ONLINE CONFIGURATION (Microsoft Graph API)
# ============================================================================
# The crawler appends new grants to a shared Excel workbook hosted on
# SharePoint / OneDrive for Business via the Microsoft Graph API.
#
# SETUP:
#   1. Register an app in Azure Portal → App Registrations
#   2. Grant API permission: Microsoft Graph → Application → Files.ReadWrite.All
#   3. Grant admin consent
#   4. Create a client secret and store the values in your .env file:
#        AZURE_TENANT_ID=<your-tenant-id>
#        AZURE_CLIENT_ID=<your-app-client-id>
#        AZURE_CLIENT_SECRET=<your-client-secret>
#   5. Set EXCEL_SHAREPOINT_URL below to the SharePoint URL of the Excel file.
#      Set to None to disable Excel export.

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")

# Full SharePoint / OneDrive URL to the shared Excel workbook
# Set to None to disable Graph API and use local file instead
EXCEL_SHAREPOINT_URL = None
EXCEL_SHEET_NAME = "From Automation"

# Legacy local-file path (if you prefer local OneDrive sync instead of Graph API)
EXCEL_OUTPUT_PATH = r"C:\Users\Francis\Documents\Grants\Grant_Tracker_Database.xlsx"

# ============================================================================
# PLAYWRIGHT CONFIGURATION (for JS-heavy sites)
# ============================================================================
# Sites that fail with Crawl4AI's default rendering (React SPAs, anti-bot sites)
# are fetched using direct Playwright with stealth. These settings control that path.
PLAYWRIGHT_HEADLESS = False           # Set False for visual debugging
PLAYWRIGHT_DEFAULT_TIMEOUT = 30000   # ms — max wait for selectors/navigation
PLAYWRIGHT_STEALTH = True            # Enable anti-detection (user agent, webdriver flag, etc.)

# ============================================================================
# CHARITY EXCELLENCE CONFIGURATION (login-gated site)
# ============================================================================
# Credentials loaded from .env — register free at:
# https://myaccount.charityexcellence.co.uk/Account/Register
CE_EMAIL = os.getenv("CHARITY_EXCELLENCE_EMAIL", "")
CE_PASSWORD = os.getenv("CHARITY_EXCELLENCE_PASSWORD", "")

# Filter presets for the Charity Excellence Funding Finder search.
# Values are the option codes from their multi-select dropdowns.
CE_REGION = "1"                      # "1" = International, "2" = UK
CE_REGION_PARTS = ["H", "I"]         # H=International, I=Africa
CE_SECTOR_TYPES = ["876", "869", "860", "862"]  # Education, Tech, Humanitarian, Buildings & Equipment
CE_PEOPLE_GROUPS = []                # e.g. ["897", "872"] for Community Groups, Small Charities

