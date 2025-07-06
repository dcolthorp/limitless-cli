"""Streaming strategies for fetching lifelog data over date ranges.

This module provides different strategies for streaming lifelog data over date ranges,
each optimized for different scenarios:

- DailyStreamer: Fetches logs day-by-day, good for small ranges or when cache is mostly hit
- BulkStreamer: Fetches logs in bulk using date range API, efficient for large ranges
- HybridStreamer: Combines daily and bulk strategies based on gap analysis
"""

from .base import RangeStreamingStrategy
from .daily import DailyStreamer
from .bulk import BulkStreamer
from .hybrid import HybridStreamer

__all__ = [
    "RangeStreamingStrategy",
    "DailyStreamer", 
    "BulkStreamer",
    "HybridStreamer",
] 