from pydantic import BaseModel
from typing import Optional, List


class Grant(BaseModel):
    """
    Represents the data structure of a Grant/Funding Opportunity.
    """

    title: Optional[str] = None
    funding_organization: Optional[str] = None
    grant_amount: Optional[str] = None
    deadline: Optional[str] = None
    geographic_focus: Optional[str] = None
    thematic_areas: Optional[List[str]] = None
    eligibility_criteria: Optional[str] = None
    description: Optional[str] = None
    application_url: Optional[str] = None

    # Additional helpful fields
    date_posted: Optional[str] = None
    category: Optional[str] = None
    source_website: Optional[str] = None  # Which website this grant was crawled from

    # Relevance analysis fields
    relevance_score: Optional[int] = None
    relevance_reasoning: Optional[str] = None
    how_it_helps: Optional[str] = None  # Specific actionable explanation of how grant helps the mission
    matching_themes: Optional[List[str]] = None

    # Preliminary relevance check (from list view)
    is_relevant_preliminary: Optional[bool] = None
