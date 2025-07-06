"""Bulk streaming strategy - fetches logs using date range API parameters."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, Iterator, List, Optional

from ...core.constants import API_DATE_FMT, PAGE_LIMIT
from ...core.utils import progress_print
from .base import RangeStreamingStrategy


class BulkStreamer(RangeStreamingStrategy):
    """Streaming strategy that fetches logs in bulk using date range API parameters.
    
    This strategy is optimal for:
    - Large date ranges
    - When most days need fresh data
    - When API efficiency is more important than cache efficiency
    """
    
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
        """Stream logs by fetching the entire range in one bulk API call."""
        
        tz_name = common.get("timezone", "UTC")
        execution_date = self._get_execution_date(tz_name)
        
        if start > execution_date:
            return
            
        effective_end = min(end, execution_date)
        
        # Prepare API parameters for bulk fetch
        params = dict(common)
        params.pop("date", None)  # Remove per-day date parameter
        params["start"] = f"{start.isoformat()} 00:00:00"
        params["end"] = f"{effective_end.isoformat()} 23:59:59"
        params.setdefault("limit", common.get("limit", PAGE_LIMIT))
        
        if not quiet:
            progress_print(f"[Bulk] Fetching {start} → {effective_end}…", quiet)
        
        # Fetch logs and group by day
        logs_by_day: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
        fetched = 0
        
        for log in self._iter_api_lifelogs(params, max_results=max_results):
            # Extract date from log
            dstr = log.get("date") or log.get("created_at") or log.get("timestamp")
            if not dstr:
                continue
                
            try:
                d_obj = self._parse_date(dstr[:10])
            except ValueError:
                continue
                
            # Filter logs to requested range
            if d_obj < start or d_obj > effective_end:
                continue
                
            logs_by_day[d_obj].append(log)
            fetched += 1
            
            if max_results is not None and fetched >= max_results:
                break
        
        # Cache the results by day
        self._cache_results_by_day(logs_by_day, start, effective_end, execution_date, quiet)
        
        # Apply post-run confirmation upgrades
        latest_non_empty = max((d for d, l in logs_by_day.items() if l), default=None)
        if latest_non_empty:
            self._post_run_upgrade_confirmations(latest_non_empty, execution_date, quiet)
        
        # Yield logs in requested order
        direction = common.get("direction", "desc")
        ordered_logs = self._order_logs_by_direction(logs_by_day, direction)
        
        count = 0
        for log in ordered_logs:
            if max_results is not None and count >= max_results:
                break
            yield log
            count += 1
    
    def _parse_date(self, date_str: str) -> date:
        """Parse date string using API date format."""
        from datetime import datetime
        return datetime.strptime(date_str, API_DATE_FMT).date()
    
    def _cache_results_by_day(
        self,
        logs_by_day: Dict[date, List[Dict[str, Any]]],
        start: date,
        end: date,
        execution_date: date,
        quiet: bool,
    ) -> None:
        """Cache the bulk results by individual day."""
        for day_cursor in (start + timedelta(days=n) for n in range((end - start).days + 1)):
            if day_cursor > execution_date:
                continue
                
            day_logs = logs_by_day.get(day_cursor, [])
            self._save_logs(day_cursor, day_logs, execution_date, execution_date, quiet)
            if self.cache_manager:
                self.cache_manager._mark_fetched(day_cursor)
    
    def _post_run_upgrade_confirmations(
        self, final_max_date: date, execution_date: date, quiet: bool = False
    ) -> None:
        """Upgrade confirmation stamps for fetched days."""
        if self.cache_manager:
            # Delegate to cache manager for session tracking
            self.cache_manager._post_run_upgrade_confirmations(final_max_date, execution_date, quiet)
        else:
            # Fallback implementation without session tracking
            from ...core.utils import eprint
            global_latest = self._get_global_latest_non_empty_date(execution_date)
            effective_max = global_latest if global_latest and global_latest > final_max_date else final_max_date
    
    def _get_global_latest_non_empty_date(self, execution_date: date):
        """Get the latest date with non-empty data across all cache."""
        cache_data = self.backend.scan(execution_date)
        latest: Optional[date] = None
        for d, (has_data, _) in cache_data.items():
            if has_data and (latest is None or d > latest):
                latest = d
        return latest
    
    def _save_logs(
        self,
        day: date,
        logs: List[Dict[str, Any]],
        fetched_on_date: date,
        execution_date: date,
        quiet: bool,
    ) -> None:
        """Save logs to cache."""
        from ..backends import CacheEntry
        
        confirmed = self._get_max_known_non_empty_data_date(day, execution_date, quiet)
        entry = CacheEntry(logs, day, fetched_on_date, confirmed)
        self.backend.write(entry)
    
    def _get_max_known_non_empty_data_date(
        self,
        current_date: date,
        execution_date: date,
        quiet: bool,
    ) -> Optional[date]:
        """Get the most recent cached date after current_date that has data."""
        max_date: Optional[date] = None
        cache_data = self.backend.scan(execution_date)
        for d, (has_data, _) in cache_data.items():
            if d <= current_date:
                continue
            if has_data and (max_date is None or d > max_date):
                max_date = d
        return max_date
    
    def _iter_api_lifelogs(
        self, params: Dict[str, Any], *, max_results: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Yield raw lifelog dictionaries via the high-level API's paginator."""
        # Accessing a protected member is acceptable internally for adapter
        paginate = getattr(self.api, "_paginate")  # type: ignore[attr-defined]
        yield from paginate("lifelogs", params, max_results=max_results)  # type: ignore[misc] 