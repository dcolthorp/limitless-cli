"""Filesystem-backed cache manager for Limitless lifelog data.

Features
• Stores each day’s logs in a structured JSON file under the user’s home
  directory (``~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json``).
• Adds metadata to guarantee data-completeness checks for historical ranges.
• Supports three fetch strategies—per-day, bulk, and hybrid—to balance speed
  and API efficiency.
• Includes a lightweight “smart probe” that verifies completeness by fetching
  a single log on the day after a requested range.
• Thread-safe cache writes and optional multi-threaded retrieval for faster
  back-fills.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import traceback
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from ..core.constants import (
    API_DATE_FMT,
    DEFAULT_TZ,
    PAGE_LIMIT,
    FETCH_STRATEGY,
    HYBRID_BULK_MIN_DAYS,
    HYBRID_BULK_RATIO,
    HYBRID_MAX_WORKERS,
    USE_BULK_RANGE_PAGINATION,
    CACHE_ROOT,
)
from ..core.utils import (
    eprint,
    progress_print,
    get_tz,
    parse_date,
)
from ..api.client import ApiError
from ..api.high_level import LimitlessAPI
from .backend import CacheBackend, FilesystemCacheBackend, CacheEntry

__all__: list[str] = ["CacheManager"]


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------


class CacheManager:
    """High-level helper that orchestrates caching & fetching lifelogs."""

    # ---------------------------------------------------------------------
    # Construction helpers
    # ---------------------------------------------------------------------
    def __init__(
        self,
        api: LimitlessAPI | None = None,
        backend: CacheBackend | None = None,
        *,
        verbose: bool | None = None,
        client_legacy: Any | None = None,  # backwards compatibility
    ):
        # If caller passed an ApiClient (legacy), wrap it in LimitlessAPI
        if client_legacy and not api:
            # defer import here to avoid circular
            from ..api.client import ApiClient

            if isinstance(client_legacy, ApiClient):
                api = LimitlessAPI(client_legacy)  # type: ignore[arg-type]

        self.api = api or LimitlessAPI()
        self.backend = backend or FilesystemCacheBackend()

        if verbose is None:
            transport = getattr(self.api, "transport", None)
            verbose = bool(getattr(transport, "verbose", False))
        self.verbose: bool = verbose

        # Internal bookkeeping (unchanged)
        self._cache_scan_cache: dict[str, Dict[date, Tuple[bool, Optional[date]]]] = {}
        self._cache_scan_lock = threading.Lock()
        self._cache_write_lock = threading.Lock()
        self._fetched_this_session: Set[date] = set()

    # ---------------------------------------------------------------------
    # Internal path helpers
    # ---------------------------------------------------------------------
    def _path(self, d: date) -> Path:
        return self.backend.path(d)

    # ---------------------------------------------------------------------
    # Cache file helpers
    # ---------------------------------------------------------------------
    def _read_cache_file(
        self, cache_path: Path, expected_data_date: date
    ) -> Tuple[List[Dict[str, Any]], date, date, Optional[date]]:
        """Read a cache file, supporting both legacy and current formats."""

        try:
            data = json.loads(cache_path.read_text())
            if isinstance(data, list):  # legacy
                logs = data
                data_date_from_file = expected_data_date
                fetched_on_date_from_file = expected_data_date
                confirmed_date = None
            else:
                logs = data["logs"]
                data_date_from_file = parse_date(data["data_date"])
                fetched_on_date_from_file = parse_date(data["fetched_on_date"])
                confirmed_date = (
                    parse_date(data["confirmed_complete_up_to_date"])
                    if data.get("confirmed_complete_up_to_date")
                    else None
                )
            return logs, data_date_from_file, fetched_on_date_from_file, confirmed_date
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as exc:
            eprint(f"[Cache] Failed to read {cache_path}: {exc}", self.verbose)
            if isinstance(exc, (json.JSONDecodeError, KeyError)) and cache_path.exists():
                cache_path.unlink(missing_ok=True)
            raise

    def _save_logs(
        self,
        day: date,
        logs: List[Dict[str, Any]],
        fetched_on_date: date,
        execution_date: date,
        quiet: bool,
    ) -> None:
        """Persist *logs* for *day* via the configured backend."""

        confirmed = self._get_max_known_non_empty_data_date(day, execution_date, quiet)
        entry = CacheEntry(logs, day, fetched_on_date, confirmed)
        with self._cache_write_lock:
            self.backend.write(entry)
            with self._cache_scan_lock:
                self._cache_scan_cache.clear()

    # Backwards-compat alias so legacy call sites continue to work
    def _write_cache_file(
        self,
        _unused_path: Path,  # kept for signature compatibility
        logs: List[Dict[str, Any]],
        data_date: date,
        fetched_on_date: date,
        execution_date: date,
        quiet: bool,
    ) -> None:  # noqa: D401 – delegate
        self._save_logs(data_date, logs, fetched_on_date, execution_date, quiet)

    # ---------------------------------------------------------------------
    # Cache directory scanning helpers
    # ---------------------------------------------------------------------
    def _scan_cache_directory(
        self, execution_date: date
    ) -> Dict[date, Tuple[bool, Optional[date]]]:
        """Return {date: (has_logs, confirmed_up_to)} for dates ≤ *execution_date*."""

        cache_key = f"scan_{execution_date.isoformat()}"
        with self._cache_scan_lock:
            if cache_key in self._cache_scan_cache:
                return self._cache_scan_cache[cache_key]

        result = self.backend.scan(execution_date)
        with self._cache_scan_lock:
            self._cache_scan_cache[cache_key] = result
        return result

    def _get_global_latest_non_empty_date(self, execution_date: date) -> Optional[date]:
        cache_data = self._scan_cache_directory(execution_date)
        latest: Optional[date] = None
        for d, (has_data, _) in cache_data.items():
            if has_data and (latest is None or d > latest):
                latest = d
        return latest

    def _get_max_known_non_empty_data_date(
        self,
        current_date: date,
        execution_date: date,
        quiet: bool,
    ) -> Optional[date]:
        """Return most recent cached date *after* *current_date* that has data."""

        max_date: Optional[date] = None
        cache_data = self._scan_cache_directory(execution_date)
        for d, (has_data, _) in cache_data.items():
            if d <= current_date:
                continue
            if has_data and (max_date is None or d > max_date):
                max_date = d
        return max_date

    # ---------------------------------------------------------------------
    # Smart probe helper
    # ---------------------------------------------------------------------
    def _perform_latest_data_probe(
        self,
        probe_day: date,
        common_params: Dict[str, Any],
        execution_date: date,
        quiet: bool = False,
    ) -> bool:
        eprint(f"[Cache] Probe for {probe_day}…", self.verbose)
        params = dict(common_params)
        params["date"] = probe_day.isoformat()
        params["limit"] = 1
        try:
            probe_logs = list(self._iter_api_lifelogs(params, max_results=1))
            if probe_logs:
                path = self._path(probe_day)
                self._write_cache_file(path, probe_logs, probe_day, execution_date, execution_date, quiet)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            eprint(f"[Cache] Probe error: {exc}", self.verbose)
            return False

    # ---------------------------------------------------------------------
    # Public fetch helpers
    # ---------------------------------------------------------------------
    def fetch_day(
        self,
        day: date,
        common: Dict[str, Any],
        *,
        quiet: bool = False,
        force_cache: bool = False,
        probe_already_done: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Optional[date]]:
        """Return logs for *day*, consulting cache when permissible."""

        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()

        if day > execution_date and not force_cache:
            eprint(f"[Fetch] Skipping future date {day}", self.verbose)
            return [], None

        logs: List[Dict[str, Any]] = []
        max_date_in_logs: Optional[date] = None

        # ---------------- Cache lookup ----------------
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

        # ---------------- API fetch -------------------
        if needs_fetch:
            progress_print(f"Fetching API for {day}…", quiet)
            api_params = dict(common)
            api_params.setdefault("timezone", tz_name)
            api_params["date"] = day.isoformat()
            api_params.setdefault("limit", common.get("limit", PAGE_LIMIT))
            try:
                fetched_logs = list(self._iter_api_lifelogs(api_params))
                logs = fetched_logs
                if logs:
                    max_date_in_logs = day
                self._save_logs(day, logs, execution_date, execution_date, quiet)
                self._mark_fetched(day)
            except ApiError as exc:
                eprint(f"API error for {day}: {exc}", self.verbose)
                logs = []
                max_date_in_logs = None

        return logs, max_date_in_logs

    # ---------------------------------------------------------------------
    # Range streaming helpers
    # ---------------------------------------------------------------------
    def stream_range(
        self,
        start: date,
        end: date,
        common: Dict[str, Any],
        *,
        max_results: Optional[int] = None,
        quiet: bool = False,
        force_cache: bool = False,
        parallel: int = 1,
    ) -> Iterator[Dict[str, Any]]:
        """Yield logs over *start*…*end* inclusive in requested order."""

        strategy = "BULK" if USE_BULK_RANGE_PAGINATION else FETCH_STRATEGY
        if strategy == "BULK" and not force_cache:
            yield from self._stream_range_bulk(start, end, common, max_results, quiet)
            return
        if strategy == "HYBRID" and not force_cache:
            yield from self._stream_range_hybrid(start, end, common, max_results, quiet)
            return

        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()

        days = [d for d in (start + timedelta(days=i) for i in range((end - start).days + 1)) if d <= execution_date]
        days_rev = sorted(days, reverse=True)

        cache_data = self._scan_cache_directory(execution_date) if not force_cache else {}
        need_probe = self._should_probe_for_completeness(days_rev, execution_date, cache_data, force_cache)

        if need_probe:
            probe_date = max(days_rev) + timedelta(days=1)
            if probe_date > execution_date:
                probe_date = execution_date
            self._perform_latest_data_probe(probe_date, common, execution_date, quiet)

        logs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        for d in days_rev:
            logs, _ = self.fetch_day(d, common, quiet=quiet, force_cache=force_cache, probe_already_done=True)
            logs_by_day[d] = logs

        latest_non_empty = max((d for d, l in logs_by_day.items() if l), default=None)
        if latest_non_empty:
            self._post_run_upgrade_confirmations(latest_non_empty, execution_date, quiet)

        order = sorted(days, reverse=(common.get("direction", "desc") == "desc"))
        count = 0
        for d in order:
            for lg in logs_by_day.get(d, []):
                if max_results is not None and count >= max_results:
                    return
                yield lg
                count += 1

    # ---------------------------------------------------------------------
    # Confirmation / probe helpers
    # ---------------------------------------------------------------------
    def _should_probe_for_completeness(
        self,
        days: List[date],
        execution_date: date,
        cache_data: Dict[date, Tuple[bool, Optional[date]]],
        force_cache: bool,
    ) -> bool:
        if force_cache:
            return False
        if not any(d < execution_date for d in days):
            return False
        max_date_in_range = max(days)
        has_later_cache = any(cd > max_date_in_range and has_data for cd, (has_data, _) in cache_data.items())
        if has_later_cache:
            return False
        for day in days:
            if day >= execution_date:
                continue
            if day not in cache_data:
                return True
            has_data, confirmed = cache_data[day]
            if not has_data or confirmed is None or confirmed < day:
                return True
        return False

    # ---------------------------------------------------------------------
    # Post-run stamp upgrade
    # ---------------------------------------------------------------------
    def _post_run_upgrade_confirmations(
        self, final_max_date: date, execution_date: date, quiet: bool = False
    ) -> None:
        global_latest = self._get_global_latest_non_empty_date(execution_date)
        effective_max = global_latest if global_latest and global_latest > final_max_date else final_max_date
        for d in list(self._fetched_this_session):
            if d == effective_max or d > effective_max:
                continue
            path = self._path(d)
            if not path.exists():
                continue
            try:
                logs, _, fetched_on, confirmed = self._read_cache_file(path, d)
                if confirmed is None or confirmed < effective_max:
                    self._write_cache_file(path, logs, d, fetched_on, execution_date, quiet)
                    eprint(f"[Cache] Confirmation upgraded for {d} → {effective_max}", self.verbose)
            except Exception:
                continue

    # ---------------------------------------------------------------------
    # Hybrid and bulk helpers (identical to original script)
    # ---------------------------------------------------------------------
    def _stream_range_bulk(
        self,
        start: date,
        end: date,
        common: Dict[str, Any],
        max_results: Optional[int],
        quiet: bool,
    ) -> Iterator[Dict[str, Any]]:
        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()
        if start > execution_date:
            return
        effective_end = min(end, execution_date)
        params = dict(common)
        params.pop("date", None)
        params["start"] = f"{start.isoformat()} 00:00:00"
        params["end"] = f"{effective_end.isoformat()} 23:59:59"
        params.setdefault("limit", common.get("limit", PAGE_LIMIT))
        if not quiet:
            progress_print(f"[Bulk] Fetching {start} → {effective_end}…", quiet)
        logs_by_day: Dict[date, List[Dict[str, Any]]] = defaultdict(list)
        fetched = 0
        for lg in self._iter_api_lifelogs(params, max_results=max_results):
            dstr = lg.get("date") or lg.get("created_at") or lg.get("timestamp")
            if not dstr:
                continue
            try:
                d_obj = datetime.strptime(dstr[:10], API_DATE_FMT).date()
            except ValueError:
                continue
            if d_obj < start or d_obj > effective_end:
                continue
            logs_by_day[d_obj].append(lg)
            fetched += 1
            if max_results is not None and fetched >= max_results:
                break
        for day_cursor in (start + timedelta(days=n) for n in range((effective_end - start).days + 1)):
            if day_cursor > execution_date:
                continue
            self._write_cache_file(
                self._path(day_cursor),
                logs_by_day.get(day_cursor, []),
                day_cursor,
                execution_date,
                execution_date,
                quiet,
            )
            self._mark_fetched(day_cursor)
        latest_non_empty = max((d for d, l in logs_by_day.items() if l), default=None)
        if latest_non_empty:
            self._post_run_upgrade_confirmations(latest_non_empty, execution_date, quiet)
        order = sorted(logs_by_day.keys(), reverse=(common.get("direction", "desc") == "desc"))
        for d in order:
            for lg in logs_by_day[d]:
                yield lg

    # ---------------------------------------------------------------------
    # Hybrid strategy helpers
    # ---------------------------------------------------------------------
    def _plan_hybrid_fetch(
        self,
        start: date,
        end: date,
        execution_date: date,
        cache_data: Dict[date, Tuple[bool, Optional[date]]],
    ) -> List[Tuple[date, date, str]]:
        needs_api: List[date] = []
        current = start
        while current <= end and current <= execution_date:
            needs = False
            if current == execution_date:
                needs = True
            elif current not in cache_data:
                needs = True
            else:
                has_data, confirmed = cache_data[current]
                if confirmed is None or confirmed <= current:
                    needs = True
            if needs:
                needs_api.append(current)
            current += timedelta(days=1)
        if not needs_api:
            return []
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
        total_days = (min(end, execution_date) - start).days + 1
        plan: List[Tuple[date, date, str]] = []
        for g_start, g_end in gaps:
            gap_days = (g_end - g_start).days + 1
            ratio = gap_days / total_days if total_days else 0
            strategy = "bulk" if gap_days >= HYBRID_BULK_MIN_DAYS or ratio >= HYBRID_BULK_RATIO else "daily"
            plan.append((g_start, g_end, strategy))
        return plan

    def _stream_range_hybrid(
        self,
        start: date,
        end: date,
        common: Dict[str, Any],
        max_results: Optional[int],
        quiet: bool,
    ) -> Iterator[Dict[str, Any]]:
        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()
        if start > execution_date:
            return
        cache_data = self._scan_cache_directory(execution_date)
        plan = self._plan_hybrid_fetch(start, end, execution_date, cache_data)
        logs_by_day: Dict[date, List[Dict[str, Any]]] = {}
        if not plan:
            current = start
            while current <= min(end, execution_date):
                entry = self.backend.read(current)
                if entry:
                    logs_by_day[current] = entry.logs
                current += timedelta(days=1)
        else:
            def execute_gap(gap: Tuple[date, date, str]) -> Dict[date, List[Dict[str, Any]]]:
                g_start, g_end, strategy = gap
                local: Dict[date, List[Dict[str, Any]]] = {}
                try:
                    if strategy == "bulk":
                        for lg in self._stream_range_bulk(g_start, g_end, common, None, True):  # quiet=True
                            dstr = lg.get("date") or lg.get("created_at") or lg.get("timestamp")
                            if not dstr:
                                continue
                            try:
                                d_obj = datetime.strptime(dstr[:10], API_DATE_FMT).date()
                            except ValueError:
                                continue
                            if g_start <= d_obj <= g_end:
                                local.setdefault(d_obj, []).append(lg)
                    else:
                        current = g_start
                        while current <= g_end:
                            day_logs, _ = self.fetch_day(current, common, quiet=True, probe_already_done=True)
                            local[current] = day_logs
                            current += timedelta(days=1)
                except Exception as exc:
                    eprint(f"[Hybrid] Gap {g_start}-{g_end} error: {exc}", self.verbose)
                return local

            # Fetch logs from API for all identified gaps
            if len(plan) == 1:
                logs_by_day.update(execute_gap(plan[0]))
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=HYBRID_MAX_WORKERS) as ex:
                    for res in ex.map(execute_gap, plan):
                        logs_by_day.update(res)
            
            # **FIX**: After fetching, iterate over the *entire* range again
            # and fill in any days from the cache that were not part of the API fetch.
            current = start
            while current <= min(end, execution_date):
                if current not in logs_by_day:
                    entry = self.backend.read(current)
                    if entry:
                        logs_by_day[current] = entry.logs
                current += timedelta(days=1)

        latest_non_empty = max((d for d, l in logs_by_day.items() if l), default=None)
        if latest_non_empty:
            self._post_run_upgrade_confirmations(latest_non_empty, execution_date, quiet)
        order = sorted(logs_by_day.keys(), reverse=(common.get("direction", "desc") == "desc"))
        count = 0
        for d in order:
            for lg in logs_by_day.get(d, []):
                if max_results is not None and count >= max_results:
                    return
                yield lg
                count += 1

    # ---------------------------------------------------------------------
    # Misc helpers
    # ---------------------------------------------------------------------
    def _mark_fetched(self, d: date) -> None:
        self._fetched_this_session.add(d) 

    # ---------------------------------------------------------------------
    # API helpers
    # ---------------------------------------------------------------------

    def _iter_api_lifelogs(
        self, params: Dict[str, Any], *, max_results: Optional[int] = None
    ) -> Iterator[Dict[str, Any]]:
        """Yield raw lifelog dictionaries via the high-level API's paginator."""

        # Accessing a protected member is acceptable internally for adapter
        paginate = getattr(self.api, "_paginate")  # type: ignore[attr-defined]
        yield from paginate("lifelogs", params, max_results=max_results)  # type: ignore[misc] 