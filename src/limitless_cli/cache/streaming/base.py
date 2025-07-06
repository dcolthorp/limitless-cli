"""Base protocol for range streaming strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, Iterator, List, Optional

from ...api.high_level import LimitlessAPI
from ..backends import CacheBackend


class RangeStreamingStrategy(ABC):
    """Abstract base class for streaming lifelog data over date ranges.
    
    Each strategy implements a different approach to fetching and caching
    lifelog data over a date range, optimized for different scenarios.
    """
    
    def __init__(
        self,
        api: LimitlessAPI,
        backend: CacheBackend,
        *,
        verbose: bool = False,
        cache_manager: Optional[Any] = None,
    ):
        """Initialize the strategy with API client and cache backend.
        
        Args:
            api: The API client for fetching data
            backend: The cache backend for storing/retrieving data
            verbose: Whether to enable verbose logging
            cache_manager: Optional CacheManager instance for session tracking
        """
        self.api = api
        self.backend = backend
        self.verbose = verbose
        self.cache_manager = cache_manager
    
    @abstractmethod
    def stream_range(
        self,
        start: date,
        end: date,
        common: Dict[str, Any],
        *,
        max_results: Optional[int] = None,
        quiet: bool = False,
        force_cache: bool = False,
    ) -> Iterator[Dict[str, Any]]:
        """Stream logs over the specified date range.
        
        Args:
            start: Start date (inclusive)
            end: End date (inclusive) 
            common: Common parameters for API calls
            max_results: Maximum number of results to return
            quiet: Whether to suppress progress output
            force_cache: Whether to force cache usage
            
        Yields:
            Log dictionaries from the API
        """
        pass
    
    def _get_execution_date(self, tz_name: str) -> date:
        """Get the current execution date in the specified timezone."""
        from datetime import datetime
        from ...core.utils import get_tz
        
        tz = get_tz(tz_name)
        return datetime.now(tz).date()
    
    def _should_skip_future_date(self, day: date, force_cache: bool) -> bool:
        """Check if a future date should be skipped."""
        if day > self._get_execution_date("UTC"):
            return not force_cache
        return False
    
    def _order_logs_by_direction(
        self,
        logs_by_day: Dict[date, List[Dict[str, Any]]],
        direction: str = "desc"
    ) -> List[Dict[str, Any]]:
        """Order logs by the specified direction (asc/desc)."""
        order = sorted(logs_by_day.keys(), reverse=(direction == "desc"))
        result = []
        for day in order:
            result.extend(logs_by_day[day])
        return result 