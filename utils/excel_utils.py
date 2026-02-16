"""
Excel utilities for exporting grants to a shared Excel Online file via OneDrive sync.
Appends new grants to an existing workbook's "From Automation" sheet.
"""

import json
from typing import List, Optional

try:
    from openpyxl import load_workbook
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from config import EXCEL_OUTPUT_PATH, EXCEL_SHEET_NAME

# Columns expected by the review team (order matters)
EXCEL_COLUMNS = [
    "title",
    "funding_organization",
    "application_url",
    "grant_amount",
    "deadline",
    "geographic_focus",
    "thematic_areas",
    "eligibility_criteria",
    "description",
    "Comments",
]

# Header row labels (human-readable)
EXCEL_HEADERS = [
    "Title",
    "Funding Organization",
    "Application URL",
    "Grant Amount",
    "Deadline",
    "Geographic Focus",
    "Thematic Areas",
    "Eligibility Criteria",
    "Description",
    "Comments",
]


def _format_field(grant: dict, field: str) -> str:
    """
    Format a grant field value for Excel output.
    Lists become comma-separated strings. None becomes empty string.
    """
    value = grant.get(field)
    if value is None:
        if field == "deadline":
            return "TBD"
        if field == "application_url":
            return "Check source page"
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def append_grants_to_excel(
    grants: List[dict],
    filepath: Optional[str] = None,
    sheet_name: Optional[str] = None,
) -> int:
    """
    Append new grants to an existing Excel workbook.
    Deduplicates against titles already present in the sheet.

    Args:
        grants: List of grant dicts to append.
        filepath: Path to the .xlsx file. Defaults to EXCEL_OUTPUT_PATH from config.
        sheet_name: Target sheet name. Defaults to EXCEL_SHEET_NAME from config.

    Returns:
        Number of grants actually appended (after dedup against existing sheet rows).
    """
    filepath = filepath or EXCEL_OUTPUT_PATH
    sheet_name = sheet_name or EXCEL_SHEET_NAME

    if not filepath:
        print("  ⚠ Excel export skipped: EXCEL_OUTPUT_PATH not configured in config.py")
        return 0

    if not OPENPYXL_AVAILABLE:
        print("  ⚠ Excel export skipped: openpyxl not installed. Run: pip install openpyxl")
        return 0

    if not grants:
        print("  No grants to export to Excel.")
        return 0

    try:
        wb = load_workbook(filepath)
    except FileNotFoundError:
        print(f"  ⚠ Excel file not found: {filepath}")
        print("    Create the file first or check the EXCEL_OUTPUT_PATH in config.py")
        return 0
    except Exception as e:
        print(f"  ⚠ Error opening Excel file: {e}")
        print("    The file may be locked (open by another user in Excel Online).")
        return 0

    # Get or create the target sheet
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.create_sheet(sheet_name)
        # Write headers if this is a new sheet
        for col_idx, header in enumerate(EXCEL_HEADERS, start=1):
            ws.cell(row=1, column=col_idx, value=header)
        print(f"  Created new sheet: '{sheet_name}'")

    # Read existing titles from column A to avoid duplicates
    existing_titles = set()
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        if row[0]:
            existing_titles.add(str(row[0]).strip().lower())

    # Find the next empty row
    next_row = ws.max_row + 1
    # Handle case where max_row includes the header but no data
    if next_row == 2 and ws.cell(row=2, column=1).value is None:
        next_row = 2

    appended = 0
    for grant in grants:
        title = grant.get("title", "")
        if title and title.strip().lower() in existing_titles:
            continue  # Skip duplicate

        # Write grant data
        for col_idx, field in enumerate(EXCEL_COLUMNS, start=1):
            if field == "Comments":
                # Leave Comments column empty for reviewers
                ws.cell(row=next_row, column=col_idx, value="")
            else:
                ws.cell(row=next_row, column=col_idx, value=_format_field(grant, field))

        next_row += 1
        appended += 1
        if title:
            existing_titles.add(title.strip().lower())

    if appended > 0:
        try:
            wb.save(filepath)
            print(f"  ✓ Appended {appended} new grants to Excel: {filepath} [{sheet_name}]")
        except PermissionError:
            print(f"  ⚠ Cannot save Excel file — it may be locked by OneDrive or another user.")
            print(f"    Close the file in Excel Online and try again.")
            return 0
        except Exception as e:
            print(f"  ⚠ Error saving Excel file: {e}")
            return 0
    else:
        print(f"  No new grants to add to Excel (all {len(grants)} already exist in the sheet).")

    wb.close()
    return appended
