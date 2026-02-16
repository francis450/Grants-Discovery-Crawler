"""
Site Profiles Registry

This module provides a registry of all available site profiles and utility functions
for accessing them.
"""

from typing import Dict, List, Type
from .base_profile import BaseSiteProfile
from .fundsforngos import FundsForNGOsProfile
from .eufundingportal import EUFundingPortalProfile
from .charityexcellence import CharityExcellenceProfile
from .globalgiving import GlobalGivingProfile
from .devex import DevExProfile
from .reliefweb import ReliefWebProfile
from .localtest import LocalTestProfile

# Registry of all available site profiles
AVAILABLE_PROFILES: Dict[str, Type[BaseSiteProfile]] = {
    "fundsforngos": FundsForNGOsProfile,
    "eufundingportal": EUFundingPortalProfile,
    "charityexcellence": CharityExcellenceProfile,
    "globalgiving": GlobalGivingProfile,
    "devex": DevExProfile,
    "reliefweb": ReliefWebProfile,
    "localtest": LocalTestProfile,
}


def get_profile(site_name: str) -> BaseSiteProfile:
    """
    Get a site profile instance by name.

    Args:
        site_name: The name of the site profile (e.g., "fundsforngos")

    Returns:
        BaseSiteProfile: An instance of the requested site profile

    Raises:
        ValueError: If the site profile is not found

    Example:
        >>> profile = get_profile("fundsforngos")
        >>> print(profile.site_name)
        Funds for NGOs
    """
    site_name_lower = site_name.lower()

    if site_name_lower not in AVAILABLE_PROFILES:
        available = ", ".join(AVAILABLE_PROFILES.keys())
        raise ValueError(
            f"Unknown site profile: '{site_name}'. "
            f"Available profiles: {available}"
        )

    profile_class = AVAILABLE_PROFILES[site_name_lower]
    return profile_class()


def get_all_profiles() -> List[BaseSiteProfile]:
    """
    Get instances of all available site profiles.

    Returns:
        List[BaseSiteProfile]: List of all available site profile instances

    Example:
        >>> profiles = get_all_profiles()
        >>> for profile in profiles:
        ...     print(f"{profile.site_name}: {len(profile.base_urls)} URLs")
    """
    return [profile_class() for profile_class in AVAILABLE_PROFILES.values()]


def list_available_sites() -> List[str]:
    """
    Get a list of all available site profile names.

    Returns:
        List[str]: List of available site names

    Example:
        >>> sites = list_available_sites()
        >>> print(sites)
        ['fundsforngos']
    """
    return list(AVAILABLE_PROFILES.keys())


def get_profiles_by_names(site_names: List[str]) -> List[BaseSiteProfile]:
    """
    Get multiple site profiles by their names.

    Args:
        site_names: List of site profile names

    Returns:
        List[BaseSiteProfile]: List of site profile instances

    Raises:
        ValueError: If any of the site profiles is not found

    Example:
        >>> profiles = get_profiles_by_names(["fundsforngos", "grants_gov"])
        >>> for profile in profiles:
        ...     print(profile.site_name)
    """
    return [get_profile(name) for name in site_names]


# Export main classes and functions
__all__ = [
    "BaseSiteProfile",
    "FundsForNGOsProfile",
    "AVAILABLE_PROFILES",
    "get_profile",
    "get_all_profiles",
    "list_available_sites",
    "get_profiles_by_names",
]
