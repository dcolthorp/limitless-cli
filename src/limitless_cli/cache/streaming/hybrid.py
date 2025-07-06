"""Hybrid streaming strategy - combines daily and bulk strategies based on gap analysis."""

from __future__ import annotations

import concurrent.futures
from datetime import date, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ...core.constants import HYBRID_BULK_MIN_DAYS, HYBRID_BULK_RATIO, HYBRID_MAX_WORKERS
from ...core.utils import eprint
from ...api.high_level import LimitlessAPI
from ..backends import CacheBackend
from .base import RangeStreamingStrategy
from .daily import DailyStreamer
from .bulk import BulkStreamer


class HybridStreamer(RangeStreamingStrategy):
    """Streaming strategy that combines daily and bulk strategies based on gap analysis.
    
    This strategy analyzes the requested range to identify gaps that need fresh data,
    then uses the most efficient strategy for each gap:
    - Bulk strategy for large consecutive gaps
    - Daily strategy for small gaps or individual days
    
    This strategy is optimal for:
    - Mixed scenarios where some days are cached and others need fresh data
    - Large ranges with sparse data needs
    - When you want to balance API efficiency with cache efficiency
    """
    
    def __init__(
        self,
        api: LimitlessAPI,
        backend: CacheBackend,
        *,
        verbose: bool = False,
        cache_manager: Optional[Any] = None,
    ):
        """Initialize the hybrid strategy with sub-strategies."""
        super().__init__(api, backend, verbose=verbose, cache_manager=cache_manager)
        self.daily_streamer = DailyStreamer(api, backend, verbose=verbose, cache_manager=cache_manager)
        self.bulk_streamer = BulkStreamer(api, backend, verbose=verbose, cache_manager=cache_manager)
    
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
        """Stream logs using hybrid strategy based on gap analysis."""
        
        tz_name = common.get("timezone", "UTC")
        execution_date = self._get_execution_date(tz_name)
        
        if start > execution_date:
            return
            
        effective_end = min(end, execution_date)
        
        # Analyze cache to determine what needs fetching
        cache_data = self.backend.scan(execution_date)
        plan = self._plan_hybrid_fetch(start, effective_end, execution_date, cache_data)
        
        logs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        
        if not plan:
            # No gaps need fetching, use cached data
            current = start
            while current <= effective_end:
                entry = self.backend.read(current)
                if entry:
                    logs_by_day[current] = entry.logs
                current += timedelta(days=1)
        else:
            # Execute the plan to fetch gaps
            logs_by_day.update(self._execute_hybrid_plan(plan, common, quiet))
            
            # Fill in any remaining days from cache
            current = start
            while current <= effective_end:
                if current not in logs_by_day:
                    entry = self.backend.read(current)
                    if entry:
                        logs_by_day[current] = entry.logs
                current += timedelta(days=1)
        
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
    
    def _plan_hybrid_fetch(
        self,
        start: date,
        end: date,
        execution_date: date,
        cache_data: Dict[date, Tuple[bool, Optional[date]]],
    ) -> List[Tuple[date, date, str]]:
        """Plan the hybrid fetch by identifying gaps and assigning strategies."""
        
        # Identify days that need API fetching
        needs_api: List[date] = []
        current = start
        while current <= end and current <= execution_date:
            needs = False
            if current == execution_date:
                needs = True  # Always refresh today
            elif current not in cache_data:
                needs = True  # No cache entry
            else:
                has_data, confirmed = cache_data[current]
                if confirmed is None or confirmed <= current:
                    needs = True  # Unconfirmed or stale
            if needs:
                needs_api.append(current)
            current += timedelta(days=1)
        
        if not needs_api:
            return []
        
        # Group consecutive days into gaps
        gaps: List[Tuple[date, date]] = []
        gap_start = needs_api[0]
        gap_end = gap_start
        
        for day in needs_api[1:]:
            if day == gap_end + timedelta(days=1):
                gap_end = day
            else:
                gaps.append((gap_start, gap_end))
                gap_start = day
                gap_end = day
        gaps.append((gap_start, gap_end))
        
        # Assign strategy to each gap
        total_days = (end - start).days + 1
        plan: List[Tuple[date, date, str]] = []
        
        for gap_start, gap_end in gaps:
            gap_days = (gap_end - gap_start).days + 1
            ratio = gap_days / total_days if total_days else 0
            
            # Use bulk strategy for large gaps or high ratios
            strategy = "bulk" if (
                gap_days >= HYBRID_BULK_MIN_DAYS or 
                ratio >= HYBRID_BULK_RATIO
            ) else "daily"
            
            plan.append((gap_start, gap_end, strategy))
        
        return plan
    
    def _execute_hybrid_plan(
        self,
        plan: List[Tuple[date, date, str]],
        common: Dict[str, Any],
        quiet: bool,
    ) -> Dict[date, List[Dict[str, Any]]]:
        """Execute the hybrid plan by fetching each gap with the appropriate strategy."""
        
        def execute_gap(gap: Tuple[date, date, str]) -> Dict[date, List[Dict[str, Any]]]:
            """Execute a single gap using the specified strategy."""
            gap_start, gap_end, strategy = gap
            local: Dict[date, List[Dict[str, Any]]] = {}
            
            try:
                if strategy == "bulk":
                    # Use bulk strategy for this gap
                    for log in self.bulk_streamer.stream_range(
                        gap_start, gap_end, common, quiet=True
                    ):
                        # Extract and validate date
                        dstr = log.get("date") or log.get("created_at") or log.get("timestamp")
                        if not dstr:
                            continue
                        try:
                            d_obj = self._parse_date(dstr[:10])
                        except ValueError:
                            continue
                        if gap_start <= d_obj <= gap_end:
                            local.setdefault(d_obj, []).append(log)
                else:
                    # Use daily strategy for this gap
                    current = gap_start
                    while current <= gap_end:
                        logs, _ = self.daily_streamer._fetch_day(
                            current, common, quiet=True, force_cache=False
                        )
                        local[current] = logs
                        current += timedelta(days=1)
                        
            except Exception as exc:
                eprint(f"[Hybrid] Gap {gap_start}-{gap_end} error: {exc}", self.verbose)
            
            return local
        
        # Execute all gaps
        logs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        
        if len(plan) == 1:
            # Single gap, execute directly
            logs_by_day.update(execute_gap(plan[0]))
        else:
            # Multiple gaps, execute in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=HYBRID_MAX_WORKERS) as ex:
                for result in ex.map(execute_gap, plan):
                    logs_by_day.update(result)
        
        return logs_by_day
    
    def _parse_date(self, date_str: str) -> date:
        """Parse date string using API date format."""
        from datetime import datetime
        from ...core.constants import API_DATE_FMT
        return datetime.strptime(date_str, API_DATE_FMT).date()
    
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