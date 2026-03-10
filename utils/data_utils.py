import csv
import json
import requests

from models.grant import Grant


def is_how_it_helps_valid(how_it_helps) -> bool:
    """Check if the how_it_helps field indicates genuine relevance.

    If the LLM itself says 'Not applicable', the grant doesn't actually help
    the mission, regardless of the numeric score it assigned.
    """
    if not how_it_helps or not isinstance(how_it_helps, str):
        return True  # Don't reject if the field is missing
    lower = how_it_helps.strip().lower()
    return not lower.startswith("not applicable")


def is_duplicate_grant(grant_title: str, seen_titles: set) -> bool:
    """Check if a grant title has already been processed."""
    if grant_title is None:
        return False
    return grant_title in seen_titles


def is_complete_grant(grant: dict, required_keys: list) -> bool:
    """Check if a grant has all required fields."""
    return all(key in grant and grant[key] is not None for key in required_keys)


def save_grants_to_csv(grants: list, filename: str):
    """Save grants to a CSV file."""
    if not grants:
        print("No grants to save.")
        return

    # Use field names from the Grant model
    fieldnames = Grant.model_fields.keys()

    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        # Handle list fields by converting to JSON strings
        for grant in grants:
            grant_row = grant.copy()
            if isinstance(grant_row.get("thematic_areas"), list):
                grant_row["thematic_areas"] = json.dumps(grant_row["thematic_areas"])
            if isinstance(grant_row.get("matching_themes"), list):
                grant_row["matching_themes"] = json.dumps(grant_row["matching_themes"])
            writer.writerow(grant_row)
    print(f"Saved {len(grants)} grants to '{filename}'.")


def save_grants_to_json(grants: list, filename: str):
    """Save grants to a JSON file for better structure preservation."""
    if not grants:
        print("No grants to save.")
        return

    with open(filename, mode="w", encoding="utf-8") as file:
        json.dump(grants, file, indent=2, ensure_ascii=False)
    print(f"Saved {len(grants)} grants to '{filename}'.")
