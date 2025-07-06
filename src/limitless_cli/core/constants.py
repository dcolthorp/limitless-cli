"""Central location for constants shared across the Limitless CLI package.

These values define API endpoints, default time-zone settings, pagination
limits, and various strategy flags used throughout the application.
"""

from __future__ import annotations
from pathlib import Path

# --- API --------------------------------------------------------------------
API_BASE_URL: str = "https://api.limitless.ai"
API_VERSION: str = "v1"
API_KEY_ENV_VAR: str = "LIMITLESS_API_KEY"
DEFAULT_TZ: str = "America/Detroit"

# Date formats
API_DATE_FMT: str = "%Y-%m-%d"
API_DATETIME_FMT: str = "%Y-%m-%d %H:%M:%S"

# Pagination
PAGE_LIMIT: int = 10

# Fetch-strategy defaults (may be overwritten at runtime)
FETCH_STRATEGY: str = "HYBRID"  # Valid: "PER_DAY" | "BULK" | "HYBRID"

HYBRID_BULK_MIN_DAYS: int = 3        # Min consecutive days to warrant bulk fetch
HYBRID_BULK_RATIO: float = 0.4        # Min ratio of range to warrant bulk fetch
HYBRID_MAX_WORKERS: int = 3           # Max parallel workers for hybrid gaps

# Backward compatibility flags
USE_BULK_RANGE_PAGINATION: bool = False  # If True, overrides FETCH_STRATEGY 

CACHE_ROOT = Path.home() / ".limitless" / "cache" 