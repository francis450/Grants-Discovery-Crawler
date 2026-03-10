"""
Per-run grant decision audit log.

Writes one JSON line per decision event to logs/audit/run_<run_id>.jsonl
so every run can be fully reconstructed and reviewed after the fact.

Event types
-----------
run_start       — crawl kicked off: sites, key config values
filtered        — grant skipped before LLM scoring (duplicate, deadline, stale, etc.)
scored          — grant reached the LLM scorer: records score, decision, reasoning
early_stop      — pagination stopped early because a full page was all-duplicate
run_end         — crawl finished: totals and duration

Usage
-----
    from utils.audit_utils import AuditLog

    audit = AuditLog(run_id="2026-03-10T14-35-00")
    audit.log_run_start(sites=["grants_gov", "fundsforngos"], config={...})
    audit.log_filtered(site="grants_gov", title="...", url="...", reason="duplicate_in_db")
    audit.log_scored(site="grants_gov", title="...", url="...", score=82,
                     how_it_helps="...", reasoning="...", accepted=True)
    audit.log_early_stop(site="fundsforngos", url="...", page=3, duplicate_count=10)
    audit.log_run_end(total_accepted=5, total_fetched=120, duration_seconds=342.1)
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

AUDIT_DIR = os.path.join("logs", "audit")


class AuditLog:
    """
    Append-only JSONL audit log for a single crawl run.

    Each call to a log_* method appends one JSON object (one line) to the
    run's .jsonl file.  The file can be read back line-by-line with
    json.loads() for post-run analysis.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        Path(AUDIT_DIR).mkdir(parents=True, exist_ok=True)
        safe_id = run_id.replace(":", "-")
        self.filepath = os.path.join(AUDIT_DIR, f"run_{safe_id}.jsonl")

    # ── Internal writer ───────────────────────────────────────────────

    def _write(self, record: Dict[str, Any]) -> None:
        record["run_id"] = self.run_id
        record["ts"] = datetime.now().isoformat(timespec="seconds")
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            # Never let audit logging crash the crawler
            pass

    # ── Public log methods ────────────────────────────────────────────

    def log_run_start(self, sites: List[str], config: Dict[str, Any]) -> None:
        """Record the configuration at the start of a run."""
        self._write({
            "event": "run_start",
            "sites": sites,
            "config": config,
        })

    def log_filtered(
        self,
        site: str,
        title: str,
        url: str,
        reason: str,
        detail: str = "",
    ) -> None:
        """
        Record a grant that was rejected before reaching the LLM scorer.

        reason: one of the FILTER_REASONS labels (e.g. 'duplicate_in_db',
                'deadline_expired', 'stale_posting', 'preliminary_irrelevant')
        """
        self._write({
            "event": "filtered",
            "site": site,
            "title": title,
            "url": url,
            "reason": reason,
            "detail": detail,
        })

    def log_scored(
        self,
        site: str,
        title: str,
        url: str,
        score: int,
        how_it_helps: str,
        reasoning: str,
        accepted: bool,
        reason_rejected: str = "",
        deadline: str = "",
    ) -> None:
        """
        Record a grant that went through the LLM relevance scorer.

        Captures the score, whether it was accepted, and — if rejected —
        the specific reason so you can tune thresholds over time.
        """
        self._write({
            "event": "scored",
            "site": site,
            "title": title,
            "url": url,
            "score": score,
            "accepted": accepted,
            "reason_rejected": reason_rejected if not accepted else "",
            "deadline": deadline,
            # Truncate long fields to keep file size manageable
            "how_it_helps": (how_it_helps or "")[:300],
            "reasoning": (reasoning or "")[:300],
        })

    def log_early_stop(
        self,
        site: str,
        url: str,
        page: int,
        duplicate_count: int = 0,
    ) -> None:
        """Record a pagination early-stop triggered by an all-duplicate page."""
        self._write({
            "event": "early_stop",
            "site": site,
            "url": url,
            "page": page,
            "duplicate_count": duplicate_count,
        })

    def log_run_end(
        self,
        total_accepted: int,
        total_fetched: int,
        duration_seconds: float,
    ) -> None:
        """Record final totals at the end of a run."""
        self._write({
            "event": "run_end",
            "total_accepted": total_accepted,
            "total_fetched": total_fetched,
            "duration_seconds": round(duration_seconds, 1),
        })
