"""
Site Performance Tracker — per-site metrics for evaluating profile utility.

Tracks every stage of the crawl pipeline per site so that after a full run
you can see at a glance which sites produce valuable grants and which don't.

Usage:
    tracker = RunTracker()
    st = tracker.site("fundsforngos")
    st.record_fetched(15)
    st.record_filtered("incomplete", 3)
    st.record_scored(title, score, how_it_helps, accepted=True)
    st.record_error("page_fetch", "Timeout on page 5")
    ...
    tracker.print_report()
    tracker.save_report("logs/site_performance.json")
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("grant_crawler")

# Filter-reason labels used across the pipeline
FILTER_REASONS = [
    "incomplete",           # Missing required fields (title/description)
    "duplicate_in_run",     # Already seen in this run
    "duplicate_in_db",      # Already exists in database
    "deadline_expired",     # Deadline passed or too soon
    "preliminary_irrelevant",  # LLM flagged is_relevant_preliminary=False on listing page
    "prefilter_keywords",   # API keyword pre-filter (eceuropa etc.)
    "low_score",            # Relevance score below threshold
    "how_it_helps_invalid", # "Not applicable" how_it_helps
    "analysis_failed",      # LLM scoring returned None after retries
    "other",
]


@dataclass
class ScoredGrant:
    """Record of one grant that reached the scoring stage."""
    title: str
    score: int
    how_it_helps: str
    accepted: bool
    reason_rejected: str = ""


@dataclass
class SiteMetrics:
    """Accumulated metrics for a single site profile."""
    site_name: str
    profile_type: str = ""  # "api", "playwright", "scraper"
    start_time: float = 0.0
    end_time: float = 0.0

    # Page-level
    pages_crawled: int = 0
    pages_errored: int = 0

    # Grant counts at each funnel stage
    grants_fetched: int = 0           # Raw items from extraction / API
    grants_filtered: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    grants_sent_to_scoring: int = 0   # Reached the LLM relevance scorer
    grants_accepted: int = 0          # Passed all checks, inserted into DB
    grants_already_in_db: int = 0     # Existed before this run

    # Per-grant scoring detail
    scored_grants: List[ScoredGrant] = field(default_factory=list)

    # Errors
    errors: List[Dict[str, str]] = field(default_factory=list)

    # ── Recording helpers ────────────────────────────────────────────

    def start(self):
        self.start_time = time.time()

    def finish(self):
        self.end_time = time.time()

    @property
    def elapsed(self) -> float:
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 1)
        return 0.0

    def record_page(self, success: bool = True):
        if success:
            self.pages_crawled += 1
        else:
            self.pages_errored += 1

    def record_fetched(self, count: int):
        self.grants_fetched += count

    def record_filtered(self, reason: str, count: int = 1):
        self.grants_filtered[reason] += count

    def record_sent_to_scoring(self, count: int = 1):
        self.grants_sent_to_scoring += count

    def record_scored(
        self,
        title: str,
        score: int,
        how_it_helps: str = "",
        accepted: bool = False,
        reason_rejected: str = "",
    ):
        self.scored_grants.append(
            ScoredGrant(
                title=title,
                score=score,
                how_it_helps=how_it_helps,
                accepted=accepted,
                reason_rejected=reason_rejected,
            )
        )
        if accepted:
            self.grants_accepted += 1

    def record_existing(self, count: int = 1):
        self.grants_already_in_db += count

    def record_error(self, stage: str, message: str):
        self.errors.append({"stage": stage, "message": message})

    # ── Derived stats ────────────────────────────────────────────────

    @property
    def total_filtered(self) -> int:
        return sum(self.grants_filtered.values())

    @property
    def acceptance_rate(self) -> str:
        if self.grants_fetched == 0:
            return "N/A"
        return f"{(self.grants_accepted / self.grants_fetched) * 100:.1f}%"

    @property
    def avg_score(self) -> str:
        scores = [g.score for g in self.scored_grants if g.score > 0]
        if not scores:
            return "N/A"
        return f"{sum(scores) / len(scores):.0f}"

    def to_dict(self) -> dict:
        return {
            "site_name": self.site_name,
            "profile_type": self.profile_type,
            "elapsed_seconds": self.elapsed,
            "pages_crawled": self.pages_crawled,
            "pages_errored": self.pages_errored,
            "grants_fetched": self.grants_fetched,
            "filters": dict(self.grants_filtered),
            "total_filtered": self.total_filtered,
            "sent_to_scoring": self.grants_sent_to_scoring,
            "grants_accepted": self.grants_accepted,
            "grants_already_in_db": self.grants_already_in_db,
            "acceptance_rate": self.acceptance_rate,
            "avg_score": self.avg_score,
            "scored_grants": [
                {
                    "title": g.title,
                    "score": g.score,
                    "how_it_helps": g.how_it_helps[:120],
                    "accepted": g.accepted,
                    "reason_rejected": g.reason_rejected,
                }
                for g in self.scored_grants
            ],
            "errors": self.errors,
        }


class RunTracker:
    """
    Aggregates SiteMetrics for all sites in a single crawl run.
    Create one at the start of crawl_grants(), pass it around,
    then call print_report() and save_report() at the end.
    """

    def __init__(self):
        self.run_id: str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.run_start: float = time.time()
        self._sites: Dict[str, SiteMetrics] = {}

    def site(self, site_name: str, profile_type: str = "") -> SiteMetrics:
        """Get-or-create SiteMetrics for a given site."""
        if site_name not in self._sites:
            sm = SiteMetrics(site_name=site_name, profile_type=profile_type)
            self._sites[site_name] = sm
        else:
            sm = self._sites[site_name]
            if profile_type and not sm.profile_type:
                sm.profile_type = profile_type
        return sm

    @property
    def all_sites(self) -> List[SiteMetrics]:
        return list(self._sites.values())

    # ── Report: console ──────────────────────────────────────────────

    def print_report(self):
        """Print a human-readable performance report to the logger."""
        run_elapsed = round(time.time() - self.run_start, 1)
        total_accepted = sum(s.grants_accepted for s in self.all_sites)
        total_fetched = sum(s.grants_fetched for s in self.all_sites)

        lines = [
            "",
            "=" * 90,
            "SITE PERFORMANCE REPORT",
            f"Run: {self.run_id}  |  Duration: {run_elapsed}s  |  "
            f"Total fetched: {total_fetched}  |  Total accepted: {total_accepted}",
            "=" * 90,
        ]

        # Sort: accepted desc, then fetched desc
        sorted_sites = sorted(
            self.all_sites,
            key=lambda s: (s.grants_accepted, s.grants_fetched),
            reverse=True,
        )

        for sm in sorted_sites:
            lines.append("")
            lines.append(f"─── {sm.site_name} ({sm.profile_type}) {'─' * max(1, 60 - len(sm.site_name))}")
            lines.append(
                f"  Time: {sm.elapsed}s  |  Pages: {sm.pages_crawled} ok, "
                f"{sm.pages_errored} errors"
            )
            lines.append(
                f"  Funnel:  fetched={sm.grants_fetched}  →  "
                f"filtered={sm.total_filtered}  →  "
                f"scored={sm.grants_sent_to_scoring}  →  "
                f"accepted={sm.grants_accepted}"
            )
            lines.append(
                f"  Acceptance rate: {sm.acceptance_rate}  |  "
                f"Avg score: {sm.avg_score}  |  "
                f"Already in DB: {sm.grants_already_in_db}"
            )

            # Filter breakdown
            if sm.grants_filtered:
                parts = [f"{k}={v}" for k, v in sorted(sm.grants_filtered.items()) if v > 0]
                lines.append(f"  Filter breakdown: {', '.join(parts)}")

            # Scored grants detail
            if sm.scored_grants:
                lines.append(f"  Scored grants ({len(sm.scored_grants)}):")
                for g in sorted(sm.scored_grants, key=lambda x: x.score, reverse=True):
                    status = "✅" if g.accepted else "❌"
                    rej = f" [{g.reason_rejected}]" if g.reason_rejected else ""
                    hih = g.how_it_helps[:80] if g.how_it_helps else ""
                    lines.append(
                        f"    {status} {g.score:3d}  {g.title[:65]}{rej}"
                    )
                    if hih:
                        lines.append(f"           └ {hih}")

            # Errors
            if sm.errors:
                lines.append(f"  Errors ({len(sm.errors)}):")
                for e in sm.errors[:10]:  # cap at 10
                    lines.append(f"    ⚠ [{e['stage']}] {e['message'][:100]}")

        # ── Utility verdict ──────────────────────────────────────────
        lines.append("")
        lines.append("─" * 90)
        lines.append("UTILITY VERDICT (sites ranked by value)")
        lines.append("─" * 90)
        for sm in sorted_sites:
            if sm.grants_fetched == 0:
                verdict = "⛔ NO DATA — check profile / site availability"
            elif sm.grants_accepted == 0 and sm.grants_sent_to_scoring > 0:
                verdict = "⚠️  LOW VALUE — fetched grants but none passed scoring"
            elif sm.grants_accepted == 0:
                verdict = "⚠️  FILTERED OUT — grants fetched but all filtered pre-scoring"
            elif sm.grants_accepted <= 2:
                verdict = "🟡 MARGINAL — few accepted grants, may need profile tuning"
            else:
                verdict = "🟢 VALUABLE — producing relevant grants"
            lines.append(f"  {sm.site_name:30s}  {verdict}")

        lines.append("=" * 90)

        for line in lines:
            logger.info(line)

    # ── Report: JSON file ────────────────────────────────────────────

    def save_report(self, filepath: str = "logs/site_performance.json"):
        """Save the full report as a structured JSON file for later analysis."""
        run_elapsed = round(time.time() - self.run_start, 1)
        report = {
            "run_id": self.run_id,
            "run_duration_seconds": run_elapsed,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_sites": len(self.all_sites),
                "total_fetched": sum(s.grants_fetched for s in self.all_sites),
                "total_accepted": sum(s.grants_accepted for s in self.all_sites),
                "total_errors": sum(len(s.errors) for s in self.all_sites),
            },
            "sites": [sm.to_dict() for sm in self.all_sites],
        }

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Site performance report saved to {filepath}")

    # ── Report: CSV summary ──────────────────────────────────────────

    def save_csv_summary(self, filepath: str = "logs/site_performance.csv"):
        """Save a one-row-per-site CSV for easy spreadsheet comparison."""
        import csv

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "run_id", "site_name", "profile_type", "elapsed_seconds",
            "pages_crawled", "pages_errored", "grants_fetched",
            "total_filtered", "sent_to_scoring", "grants_accepted",
            "already_in_db", "acceptance_rate", "avg_score", "error_count",
        ]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for sm in self.all_sites:
                writer.writerow({
                    "run_id": self.run_id,
                    "site_name": sm.site_name,
                    "profile_type": sm.profile_type,
                    "elapsed_seconds": sm.elapsed,
                    "pages_crawled": sm.pages_crawled,
                    "pages_errored": sm.pages_errored,
                    "grants_fetched": sm.grants_fetched,
                    "total_filtered": sm.total_filtered,
                    "sent_to_scoring": sm.grants_sent_to_scoring,
                    "grants_accepted": sm.grants_accepted,
                    "already_in_db": sm.grants_already_in_db,
                    "acceptance_rate": sm.acceptance_rate,
                    "avg_score": sm.avg_score,
                    "error_count": len(sm.errors),
                })

        logger.info(f"Site performance CSV saved to {filepath}")
