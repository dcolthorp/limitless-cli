"""Daily streaming strategy - fetches logs day-by-day."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterator, List, Optional

from .base import RangeStreamingStrategy


class DailyStreamer(RangeStreamingStrategy):
    """Streaming strategy that fetches logs day-by-day.
    
    This strategy is optimal for:
    - Small date ranges
    - When most days are already cached
    - When you need precise control over each day's data
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
        """Stream logs by fetching each day individually."""
        
        tz_name = common.get("timezone", "UTC")
        execution_date = self._get_execution_date(tz_name)
        
        # Generate list of days to process
        days = [
            d for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
            if d <= execution_date or force_cache
        ]
        
        # Process days in reverse chronological order for cache efficiency
        days_rev = sorted(days, reverse=True)
        
        # Check if we need to probe for completeness
        if not force_cache:
            need_probe = self._should_probe_for_completeness(days_rev, execution_date)
            if need_probe:
                self._perform_completeness_probe(days_rev, common, execution_date, quiet)
        
        # Fetch logs for each day
        logs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        for day in days_rev:
            if self._should_skip_future_date(day, force_cache):
                continue
                
            logs, _ = self._fetch_day(day, common, quiet=quiet, force_cache=force_cache)
            logs_by_day[day] = logs
        
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
    
    def _fetch_day(
        self,
        day: date,
        common: Dict[str, Any],
        *,
        quiet: bool = False,
        force_cache: bool = False,
    ) -> tuple[List[Dict[str, Any]], Optional[date]]:
        """Fetch logs for a single day, consulting cache when permissible."""
        
        tz_name = common.get("timezone", "UTC")
        tz = self._get_tz(tz_name)
        execution_date = self._get_execution_date(tz_name)
        
        if day > execution_date and not force_cache:
            return [], None
        
        logs: List[Dict[str, Any]] = []
        max_date_in_logs: Optional[date] = None
        
        # Check cache first
        entry = self.backend.read(day)
        needs_fetch = True
        
        if entry is not None:
            if force_cache:
                logs = entry.logs
                max_date_in_logs = day if logs else None
                needs_fetch = False
            else:
                if day == execution_date:
                    needs_fetch = True  # always refresh today
                elif entry.confirmed_complete_up_to_date and entry.confirmed_complete_up_to_date > entry.data_date:
                    logs = entry.logs
                    max_date_in_logs = day if logs else None
                    needs_fetch = False
        elif force_cache:
            needs_fetch = False
        
        # Fetch from API if needed
        if needs_fetch:
            from ...core.utils import progress_print, eprint
            from ...api.client import ApiError
            
            progress_print(f"Fetching API for {day}…", quiet)
            api_params = dict(common)
            api_params.setdefault("timezone", tz_name)
            api_params["date"] = day.isoformat()
            
            try:
                fetched_logs = list(self._iter_api_lifelogs(api_params))
                logs = fetched_logs
                if logs:
                    max_date_in_logs = day
                self._save_logs(day, logs, execution_date, execution_date, quiet)
                if self.cache_manager:
                    self.cache_manager._mark_fetched(day)
            except ApiError as exc:
                eprint(f"API error for {day}: {exc}", self.verbose)
                logs = []
                max_date_in_logs = None
        
        return logs, max_date_in_logs
    
    def _should_probe_for_completeness(self, days: List[date], execution_date: date) -> bool:
        """Determine whether a completeness probe is necessary.

        We can fast-exit in the very common scenario where all requested days
        already carry a *confirmed_complete_up_to_date* stamp that is newer
        than the latest day in the range.  In that case we *know* the range is
        complete, so there is no need to perform the expensive full-cache scan
        (which opens every JSON file).
        """

        if not any(d < execution_date for d in days):
            # Range is entirely today/future – never probe.
            return False

        max_date_in_range = max(days)

        # -------- Optimistic short-circuit ------------------------------
        for d in days:
            entry = self.backend.read(d)
            if entry and entry.confirmed_complete_up_to_date and entry.confirmed_complete_up_to_date > max_date_in_range:
                # At least one day already confirms completeness beyond the
                # range – probing is unnecessary.
                return False

        # -------- Fallback to comprehensive check (may scan) ------------
        cache_data = self._scan_cache_directory(execution_date)

        # Check if we have any later cached day with data.
        has_later_cache = any(
            cd > max_date_in_range and has_data
            for cd, (has_data, _) in cache_data.items()
        )
        if has_later_cache:
            return False

        # See if any day in the past range lacks confirmation or data.
        for day in days:
            if day >= execution_date:
                continue
            if day not in cache_data:
                return True
            has_data, confirmed = cache_data[day]
            if not has_data or confirmed is None or confirmed < day:
                return True

        return False
    
    def _perform_completeness_probe(
        self,
        days: List[date],
        common: Dict[str, Any],
        execution_date: date,
        quiet: bool,
    ) -> None:
        """Perform a completeness probe by fetching one log from the day after the range."""
        from ...core.utils import eprint
        
        probe_date = max(days) + timedelta(days=1)
        if probe_date > execution_date:
            probe_date = execution_date
            
        eprint(f"[Cache] Probe for {probe_date}…", self.verbose)
        params = dict(common)
        params["date"] = probe_date.isoformat()
        params["limit"] = 1
        
        try:
            probe_logs = list(self._iter_api_lifelogs(params, max_results=1))
            if probe_logs:
                self._save_logs(probe_date, probe_logs, execution_date, execution_date, quiet)
        except Exception as exc:
            eprint(f"[Cache] Probe error: {exc}", self.verbose)
    
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
    
    def _get_tz(self, tz_name: str):
        """Get timezone object."""
        from ...core.utils import get_tz
        return get_tz(tz_name)
    
    def _scan_cache_directory(self, execution_date: date):
        """Scan cache directory for existing data."""
        return self.backend.scan(execution_date)
    
    def _get_global_latest_non_empty_date(self, execution_date: date):
        """Get the latest date with non-empty data across all cache."""
        cache_data = self._scan_cache_directory(execution_date)
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
        cache_data = self._scan_cache_directory(execution_date)
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