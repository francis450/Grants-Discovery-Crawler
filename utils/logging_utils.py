import logging
import csv
import time
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, Any
from logging.handlers import RotatingFileHandler

__all__ = ['setup_logger', 'MetricsLogger', 'get_logger']

# Ensure logs directory exists
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

def setup_logger(
    name: str = "GrantCrawler", 
    log_file: Optional[str] = "crawler", 
    level: int = logging.INFO
) -> logging.Logger:
    """
    Sets up a logger with both console and file handlers.
    File logs are rotated daily by default naming convention.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent adding handlers multiple times if function is called repeatedly
    if logger.handlers:
        return logger

    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Console Handler
    # Use stderr so stdout can be used for JSON output piping
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File Handler
    if log_file:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d")
            filename = os.path.join(LOGS_DIR, f"{log_file}_{timestamp}.log")
            
            # Rotate: Max 10MB per file, keep last 5 backups
            file_handler = RotatingFileHandler(
                filename, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            print(f"Failed to set up file logging: {e}")

    return logger

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

class MetricsLogger:
    """Handles logging of structured performance metrics to a CSV file."""
    
    FIELDNAMES = [
        "timestamp", "site", "url", "operation", 
        "duration_seconds", "items_count", "token_usage", 
        "status", "error_details"
    ]

    def __init__(self, filepath: str = "metrics.csv"):
        self.filepath = filepath
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.filepath):
            with open(self.filepath, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()

    def log_metric(
        self, site: str, url: str, operation: str, 
        duration: float, items: int = 0, token_usage: int = 0, 
        status: str = "SUCCESS", error: Optional[str] = None
    ):
        try:
            with open(self.filepath, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writerow({
                    "timestamp": datetime.now().isoformat(),
                    "site": site,
                    "url": url,
                    "operation": operation,
                    "duration_seconds": round(duration, 4),
                    "items_count": items,
                    "token_usage": token_usage,
                    "status": status,
                    "error_details": str(error) if error else ""
                })
        except Exception as e:
            # Fallback to standard logging if structured logging fails
            logging.error(f"Failed to write metrics: {e}")

    @contextmanager
    def measure(self, operation: str, site: str = "Unknown", url: str = "N/A"):
        start_time = time.time()
        # Context object to expose internal counters
        ctx = type('MetricContext', (), {'items': 0, 'token_usage': 0, 'status': "SUCCESS", 'error': None})()
        try:
            yield ctx
        except Exception as e:
            ctx.status = "ERROR"
            ctx.error = str(e)
            raise
        finally:
            self.log_metric(
                site=site, url=url, operation=operation, 
                duration=time.time() - start_time,
                items=ctx.items, token_usage=ctx.token_usage, 
                status=ctx.status, error=ctx.error
            )

# Create a default logger instance for easy import
logger = setup_logger()