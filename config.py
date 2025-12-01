# config.py

# ============================================================================
# SITE PROFILES CONFIGURATION
# ============================================================================
# List of site profiles to crawl (profiles are defined in site_profiles/)
# Available profiles: "fundsforngos" (more to be added)
ENABLED_SITES = [
    "fundsforngos",
    "eufundingportal",
    # Add more sites here as profiles are implemented:
    # "grants_gov",
    # "globalgiving",
]

# ============================================================================
# LEGACY CONFIGURATION (Deprecated - kept for reference)
# ============================================================================
# NOTE: GRANT_URLS and CSS_SELECTOR are now managed by site profiles.
# These are kept here for backward compatibility but are not used anymore.

# Old URL configuration (now handled by FundsForNGOsProfile)
GRANT_URLS = [
    "https://www2.fundsforngos.org/category/children/",
    "https://www2.fundsforngos.org/category/education/",
    "https://www2.fundsforngos.org/tag/funding-opportunities-and-resources-in-kenya/",
    "https://www2.fundsforngos.org/category/information-technology/",
    "https://www2.fundsforngos.org/category/science-and-technology/",
]

# Old CSS selector (now handled by site profiles)
CSS_SELECTOR = "article.post, article.entry"

# ============================================================================
# DATA VALIDATION CONFIGURATION
# ============================================================================
REQUIRED_KEYS = [
    "title",
    "deadline",
    "description",
    "application_url",
]

# Optional but valuable fields
OPTIONAL_KEYS = [
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
MIN_RELEVANCE_SCORE = 60  # Only include grants scoring 60 or above
