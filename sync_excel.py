#!/usr/bin/env python3
"""
Sync all grants from the local SQLite database to the shared Excel workbook.

Usage:
    python sync_excel.py              # sync to the default "From Automation" sheet
    python sync_excel.py --sheet "My Sheet"  # sync to a custom sheet name

The script reads every grant from grants.db, skips titles that already
exist in the Excel sheet (dedup), and appends the rest via the Microsoft
Graph API (or the legacy openpyxl fallback).
"""

import argparse
import logging
import sys

from utils.db_utils import init_db, get_grant_count
from utils.excel_utils import sync_db_to_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("grant_crawler")


def main():
    parser = argparse.ArgumentParser(
        description="Push all grants from the local DB to the shared Excel workbook."
    )
    parser.add_argument(
        "--sheet",
        type=str,
        default=None,
        help='Target sheet name (default: "From Automation")',
    )
    args = parser.parse_args()

    init_db()
    total = get_grant_count()
    logger.info(f"Database contains {total} grants.")

    if total == 0:
        logger.info("Nothing to sync — database is empty.")
        sys.exit(0)

    appended = sync_db_to_excel(sheet_name=args.sheet)
    logger.info(f"Done. {appended} grants appended to Excel.")


if __name__ == "__main__":
    main()
