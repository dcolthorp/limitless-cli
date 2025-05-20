#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Limitless CLI Utility – v0.7.0
"""

# This script fetches data synced from the limitless ai transcription device to their
# cloud service. The limitless device is synced to the cloud from time to time.
# This script fetches whatever has been synced to the cloud. Note that as a result,
# we could be fetching data for past dates that are actually _incomplete_, because
# the device isn't synced with the cloud.

# The only reliable way to know if a day is complete, is to have seen data for newer dates when
# we fetch the data from the cloud.

###############################################################################
# Caching Strategy and Rationale (v0.7.0+)
#
# This CLI caches API results by day. Each day's logs are stored in a JSON file
# under ~/.limitless/cache/YYYY/MM/YYYY-MM-DD.json.
#
# 1. Cache File Structure:
#    - Each cache file is a JSON object containing:
#      - "data_date": The date the logs belong to (string, "YYYY-MM-DD").
#      - "fetched_on_date": The date the script was run when this cache file
#                           was last written/updated (string, "YYYY-MM-DD").
#      - "logs": A list of log entry objects for the "data_date".
#      - "confirmed_complete_up_to_date": The most recent date (string, "YYYY-MM-DD")
#                                         for which non-empty logs exist, confirming
#                                         completeness of data up to this point.
#
# 2. Core Principle for Cache Validity (when not using --force-cache):
#    - Data for `target_day` equal to `execution_date` (i.e., "today") is always
#      considered potentially incomplete and will be re-fetched from the API.
#    - Data for `target_day` *before* `execution_date` (i.e., a past day) can only
#      be used from cache if it's "confirmed complete" by its own metadata.
#      This means the "confirmed_complete_up_to_date" field in the cache file
#      must exist and be greater than or equal to the "data_date".
#    - The `fetched_on_date` field in the cache is primarily for informational
#      purposes; the "confirmed_complete_up_to_date" field is the key determinant
#      for past day completeness.
#
# 3. "Smart Data Probe" Mechanism:
#    - The script performs at most one "Smart Data Probe" per execution when necessary:
#      a. A probe is only performed when ALL of these conditions are true:
#         - We're not using --force-cache
#         - We don't already have cache data for any date AFTER the requested range
#         - There are past days in the range being fetched (not just today/future)
#      b. The probe targets a date AFTER the requested range but before or equal to today.
#         For example, if fetching May 1-10 and today is May 16, it probes May 11.
#      c. The probe runs in a background thread in parallel with other fetches.
#      d. If the probe successfully fetches any data, that data is cached with
#         appropriate "confirmed_complete_up_to_date" metadata.
#      e. The purpose is to establish a "confirmed_complete_up_to_date" point
#         that's newer than our requested range, proving our range data is complete.
#
# 4. Cache Usage Decision (`fetch_day` logic, simplified):
#    - Let `execution_date` be the current script run date.
#    - If `target_day` cache exists:
#      - If `--force-cache`: Use it.
#      - Else if `target_day == execution_date`: Re-fetch from API.
#      - Else (`target_day < execution_date` - a past day):
#        - If `confirmed_complete_up_to_date` is not null and >= `data_date`: Use cache.
#        - Else (past day, not confirmed by its metadata or missing metadata):
#          - Re-fetch `target_day` from API.
#    - If `target_day` cache does not exist (and not `--force-cache`):
#      - Re-fetch `target_day` from API.
#    - When new data is fetched and cached for `target_day`, its `fetched_on_date` is
#      set to the current `execution_date` and "confirmed_complete_up_to_date" is
#      calculated by finding the latest date with non-empty logs across all cache files.
#
# 5. Range Fetching (`stream_range`):
#    - When fetching a date range, the script internally processes days in
#      *reverse chronological order* to optimize cache validation.
#    - Smart Data Probe runs in a parallel thread targeting a date just after the range.
#    - Existing cache data for dates after the requested range is detected automatically
#      to determine if a data probe is needed.
#    - Results are returned in the order specified by the direction parameter.
#
# 6. Migration of Old Cache Files (pre-v0.7.0):
#    - Old cache files are supported through format detection. Files in list format 
#      are treated as having the same `data_date` and `fetched_on_date` with no 
#      "confirmed_complete_up_to_date" field.
#    - Old cache files for past days will only be used if they can be validated
#      against the new metadata-based completeness check, which will cause most to
#      be re-fetched once to establish proper metadata.
#
# 7. Goal and Rationale:
#    - This strategy robustly ensures that cached data for past days is only used if
#      there's positive evidence (through cache metadata) that the sync to the
#      cloud for those past days was complete.
#    - It actively tries to establish the latest point of synced data using the probe.
#    - It correctly handles "today's" data as always needing a fresh look.
###############################################################################


from __future__ import annotations
import traceback # Added import
import concurrent.futures
import argparse
import os
import sys
import json
import requests
import time as _time_module
from datetime import datetime, date, timedelta, time
from pathlib import Path
from typing import Optional, Dict, Any, Iterator, List

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    print("Error: 'zoneinfo' module not found. Use Python 3.9+ or install 'tzdata'.", file=sys.stderr)
    sys.exit(1)

# ── Constants ────────────────────────────────────────────────────────────────
API_BASE_URL     = "https://api.limitless.ai"
API_VERSION      = "v1"
API_KEY_ENV_VAR  = "LIMITLESS_API_KEY"
DEFAULT_TZ       = "America/Detroit"
API_DATE_FMT     = "%Y-%m-%d"
API_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
CACHE_ROOT       = Path.home() / ".limitless" / "cache"
PAGE_LIMIT       = 10

# ── Utilities ────────────────────────────────────────────────────────────────
def eprint(msg: str, verbose: bool=False):
    if verbose:
        print(msg, file=sys.stderr)

def progress_print(msg: str, quiet: bool=False):
    if not quiet:
        print(msg, file=sys.stderr)

def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV_VAR)
    if not key:
        print(f"Error: Missing {API_KEY_ENV_VAR}", file=sys.stderr)
        sys.exit(1)
    return key

def get_tz(name: str=DEFAULT_TZ) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(f"Warning: Timezone '{name}' not found; falling back to UTC.", file=sys.stderr)
        return ZoneInfo("UTC")

def parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, API_DATE_FMT).date()
    except ValueError:
        print(f"Invalid date '{s}' (expected YYYY-MM-DD).", file=sys.stderr)
        sys.exit(1)

def parse_datetime(s: str, tz: ZoneInfo) -> datetime:
    try:
        return datetime.strptime(s, API_DATETIME_FMT).replace(tzinfo=tz)
    except ValueError:
        print(f"Invalid datetime '{s}' (expected YYYY-MM-DD HH:MM:SS).", file=sys.stderr)
        sys.exit(1)

def parse_date_spec(spec: str, tz: ZoneInfo) -> Optional[date]:
    """Parses flexible date specifications."""
    now_date = datetime.now(tz).date()

    # 1. YYYY-MM-DD
    try:
        return datetime.strptime(spec, API_DATE_FMT).date()
    except ValueError:
        pass

    # 2. M/D or MM/DD
    try:
        month_day = datetime.strptime(spec, "%m/%d")
        # Find the most recent past occurrence of this month/day
        target_date = now_date.replace(month=month_day.month, day=month_day.day)
        if target_date > now_date:
            target_date = target_date.replace(year=now_date.year - 1)
        return target_date
    except ValueError:
        pass

    # 3. Relative d/w/m/y - N
    import re
    match = re.match(r"([dwmy])-(\d+)", spec.lower())
    if match:
        unit, num_str = match.groups()
        num = int(num_str)
        if unit == 'd':
            return now_date - timedelta(days=num)
        elif unit == 'w':
            return now_date - timedelta(weeks=num)
        elif unit == 'm':
            # Approximate month subtraction (might cross year boundaries)
            target_month = now_date.month - num
            target_year = now_date.year
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            # Adjust day if it exceeds the number of days in the target month
            import calendar
            max_days = calendar.monthrange(target_year, target_month)[1]
            target_day = min(now_date.day, max_days)
            return date(target_year, target_month, target_day)
        elif unit == 'y':
            # Adjust for leap year if needed (going from Feb 29 back)
            try:
                return now_date.replace(year=now_date.year - num)
            except ValueError: # Target date doesn't exist (e.g. Feb 29 -> non-leap year)
                return now_date.replace(year=now_date.year - num, month=2, day=28)
        else: # Should not happen due to regex
             return None

    eprint(f"Invalid date specification: '{spec}'", True) # Use eprint with verbose flag
    return None

def parse_week_spec(spec: str) -> Optional[tuple[date, date]]:
    """Parses week specification (number or YYYY-WNN) and returns (start_date, end_date)."""
    import re
    now = datetime.now()
    current_year = now.year

    # 1. Integer week number (assume current year)
    if re.fullmatch(r"\d{1,2}", spec):
        try:
            week_num = int(spec)
            if not 1 <= week_num <= 53:
                raise ValueError("Week number out of range (1-53)")
            # Format as YYYY-WNN
            iso_week_str = f"{current_year}-W{week_num:02d}"
        except ValueError as e:
            eprint(f"Invalid week number: {e}", True)
            return None
    # 2. YYYY-WNN format
    elif re.fullmatch(r"\d{4}-W\d{2}", spec):
        iso_week_str = spec
        # Basic validation for week number range in YYYY-WNN format
        try:
             year_part, week_part = spec.split('-W')
             week_num = int(week_part)
             if not 1 <= week_num <= 53:
                 raise ValueError("Week number out of range (1-53) in ISO format")
        except ValueError as e:
             eprint(f"Invalid ISO week format: {e}", True)
             return None
    else:
        eprint(f"Invalid week specification format: '{spec}'", True)
        return None

    try:
        # %G is ISO year, %V is ISO week number, %u is ISO weekday (1=Mon, 7=Sun)
        # Get Monday of the specified week
        start_date = datetime.strptime(f"{iso_week_str}-1", "%G-W%V-%u").date()
        # Sunday is 6 days after Monday
        end_date = start_date + timedelta(days=6)
        return start_date, end_date
    except ValueError:
        # This might happen if the week number is invalid for the given year (e.g., week 53)
        eprint(f"Cannot determine dates for week specification: '{iso_week_str}'", True)
        return None

# ── HTTP & Pagination ────────────────────────────────────────────────────────
class ApiError(Exception):
    pass

class ApiClient:
    def __init__(self, api_key: Optional[str]=None, verbose: bool=False):
        self.key = api_key or get_api_key()
        self.verbose = verbose
        self.session = requests.Session()

    def _log(self, msg: str):
        eprint(f"[API] {msg}", self.verbose)

    def request(self, endpoint: str, params: Dict[str,Any]) -> Dict[str,Any]:
        url = f"{API_BASE_URL}/{API_VERSION}/{endpoint.lstrip('/')}"
        headers = {"X-API-Key": self.key, "Accept": "application/json"}
        self._log(f"GET {url} params={params}")
        retries = 3
        for attempt in range(1, retries+1):
            try:
                resp = self.session.get(url, headers=headers, params=params, timeout=300)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                status = getattr(e.response, "status_code", None)
                retryable = attempt < retries and (status is None or status >= 500 or status == 429)
                if retryable:
                    wait = None
                    if status == 429:
                        ra = e.response.headers.get("Retry-After")
                        if ra and ra.isdigit():
                            wait = int(ra)
                    if wait is None:
                        wait = 2 ** (attempt - 1)
                    self._log(f"Attempt {attempt} failed (status {status}); retrying in {wait}s...")
                    _time_module.sleep(wait)
                    continue
                print(f"API error: {e}", file=sys.stderr)
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    try:
                        print(json.dumps(e.response.json(), indent=2), file=sys.stderr)
                    except Exception:
                        print(e.response.text, file=sys.stderr)
                raise ApiError(str(e))
        raise ApiError("Unknown error")

    def paginated(self, endpoint: str, params: Dict[str,Any], max_results: Optional[int]=None) -> Iterator[Dict[str,Any]]:
        cursor = params.pop("cursor", None)
        fetched = 0
        first = True
        while True:
            if cursor:
                params["cursor"] = cursor
            data = self.request(endpoint, params)
            logs = data.get("data",{}).get("lifelogs", [])
            meta = data.get("meta",{}).get("lifelogs", {})
            cursor = meta.get("nextCursor")
            count = meta.get("count", len(logs))
            self._log(f"Fetched page: {count} items, total so far {fetched}")
            if not logs and not first:
                break
            if not logs and first:
                break
            for lg in logs:
                if max_results and fetched >= max_results:
                    return
                yield lg
                fetched += 1
                first = False
            if not cursor or (max_results and fetched >= max_results):
                break

class CacheManager:
    def __init__(self, client: ApiClient, root: Path=CACHE_ROOT):
        self.client = client
        self.root   = root

    def _path(self, d: date) -> Path:
        return self.root / f"{d:%Y/%m}" / f"{d.isoformat()}.json"

    def _read_cache_file(self, cache_path: Path, expected_data_date: date) -> tuple[List[Dict[str, Any]], date, date, Optional[date]]:
        """
        Reads a cache file, handling both new and old formats.
        Returns (logs, data_date, fetched_on_date, confirmed_complete_up_to_date).
        For old formats, fetched_on_date will be the same as data_date, and confirmed_complete_up_to_date will be None.
        """
        try:
            data = json.loads(cache_path.read_text())
            if isinstance(data, list): # Old format
                logs = data
                data_date_from_file = expected_data_date
                fetched_on_date_from_file = expected_data_date
                confirmed_complete_up_to_date = None
            else: # New format
                logs = data["logs"]
                data_date_from_file = parse_date(data["data_date"])
                fetched_on_date_from_file = parse_date(data["fetched_on_date"])
                confirmed_complete_up_to_date = None
                if "confirmed_complete_up_to_date" in data and data["confirmed_complete_up_to_date"]:
                    try:
                        confirmed_complete_up_to_date = parse_date(data["confirmed_complete_up_to_date"])
                    except Exception:
                        confirmed_complete_up_to_date = None
            return logs, data_date_from_file, fetched_on_date_from_file, confirmed_complete_up_to_date
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            eprint(f"[Cache] Failed to read or parse {cache_path}: {e}", self.client.verbose)
            if isinstance(e, (json.JSONDecodeError, KeyError)):
                if cache_path.exists():
                    cache_path.unlink(missing_ok=True)
            raise

    def _get_max_known_non_empty_data_date(self, current_data_date: date, logs_for_current_data_date: List[Dict[str, Any]], execution_date: date, quiet: bool) -> Optional[date]:
        """
        Scans all cache files and returns the latest data_date for which non-empty logs are known,
        including the current data_date if logs_for_current_data_date is non-empty.
        """
        max_confirmed_date: Optional[date] = None
        if logs_for_current_data_date:
            max_confirmed_date = current_data_date
        # Scan all cache files
        if self.root.exists():
            for year_dir in self.root.iterdir():
                if year_dir.is_dir() and year_dir.name.isdigit() and len(year_dir.name) == 4:
                    for month_dir in year_dir.iterdir():
                        if month_dir.is_dir() and month_dir.name.isdigit() and len(month_dir.name) == 2:
                            for cache_file_path in month_dir.glob("*.json"):
                                try:
                                    file_date_str = cache_file_path.stem
                                    file_data_date = datetime.strptime(file_date_str, API_DATE_FMT).date()
                                    if file_data_date > execution_date:
                                        continue
                                    logs, _, _, _ = self._read_cache_file(cache_file_path, file_data_date)
                                    if logs:
                                        if max_confirmed_date is None or file_data_date > max_confirmed_date:
                                            max_confirmed_date = file_data_date
                                except Exception:
                                    continue
        return max_confirmed_date

    def _write_cache_file(self, cache_path: Path, logs: List[Dict[str, Any]], data_date: date, fetched_on_date: date, execution_date: date, quiet: bool):
        """Writes a cache file in the new format, including confirmed_complete_up_to_date."""
        confirmed_complete_up_to_date = self._get_max_known_non_empty_data_date(data_date, logs, execution_date, quiet)
        data = {
            "data_date": data_date.isoformat(),
            "fetched_on_date": fetched_on_date.isoformat(),
            "logs": logs,
            "confirmed_complete_up_to_date": confirmed_complete_up_to_date.isoformat() if confirmed_complete_up_to_date else None,
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, indent=2))
            eprint(f"[Cache] wrote {cache_path}", self.client.verbose)
        except Exception as e:
            eprint(f"[Cache] failed to write cache for {data_date}: {e}", self.client.verbose)
            # Do not re-raise here, as a failed cache write shouldn't stop the flow of data if API fetch was successful.

    # _is_confirmed_by_later_cache method is now obsolete and removed.
    # Completeness is determined by the 'confirmed_complete_up_to_date' field within each cache file.

    def _perform_latest_data_probe(self, probe_day: date, common_params: Dict[str, Any], execution_date: date, quiet: bool = False) -> bool:
        """
        Fetches a minimal amount of data for probe_day to establish if any data exists.
        Writes to cache if successful and non-empty.
        Returns True if non-empty data was fetched and cached, False otherwise.
        """
        progress_print(f"[Cache] Performing smart data probe for {probe_day}...", quiet)
        probe_api_params = dict(common_params) # Create a copy to modify
        probe_api_params["date"] = probe_day.isoformat()
        probe_api_params["limit"] = 1 # Fetch just one log to confirm existence

        try:
            probe_logs = list(self.client.paginated("lifelogs", probe_api_params, max_results=1))

            if probe_logs:
                probe_cache_path = self._path(probe_day)
                current_execution_date = datetime.now(get_tz(common_params.get("timezone", DEFAULT_TZ))).date()
                self._write_cache_file(probe_cache_path, probe_logs, probe_day, current_execution_date, current_execution_date, quiet)
                progress_print(f"[Cache] Smart data probe for {probe_day} successful, found data.", quiet)
                return True
            else:
                progress_print(f"[Cache] Smart data probe for {probe_day} found no data.", quiet)
                return False
        except ApiError as e:
            eprint(f"[Cache] API error during smart data probe for {probe_day}: {e}", self.client.verbose)
            return False
        except Exception as e:
            eprint(f"[Cache] Unexpected error during smart data probe for {probe_day}: {e}", self.client.verbose)
            return False

    def fetch_day(self, day: date, common: Dict[str,Any], quiet: bool=False, force_cache: bool=False, 
                  probe_already_done: bool=False) -> tuple[List[Dict[str,Any]], Optional[date]]:
        """
        Fetches data for a specific day, using cache if appropriate.
        
        Args:
            day: The target day to fetch data for
            common: Common parameters for API requests
            quiet: Whether to suppress progress messages
            force_cache: Whether to force using cache only (no API fetch)
            probe_already_done: Whether a smart data probe has already been performed in this session
                               (to avoid redundant probes)
        
        Returns:
            Tuple of (list of log entries, max date in logs or None)
        """
        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()
        cache_path = self._path(day)

        logs_to_return: List[Dict[str, Any]] = []
        max_date_in_logs: Optional[date] = None
        needs_api_fetch = True

        if cache_path.exists():
            try:
                # _read_cache_file returns: logs, data_date, fetched_on_date, confirmed_complete_up_to_date
                cached_logs, data_date_from_file, _, confirmed_obj = self._read_cache_file(cache_path, day)
                
                if force_cache:
                    progress_print(f"Using cache (forced) for {day}", quiet)
                    logs_to_return = cached_logs
                    if logs_to_return: max_date_in_logs = data_date_from_file # Use actual data_date from cache
                    needs_api_fetch = False
                else: # Not force_cache
                    if day == execution_date:
                        progress_print(f"Cache for {day} (today) exists, but will be re-fetched", quiet)
                        needs_api_fetch = True # Always re-fetch today
                    elif day < execution_date: # Past day
                        if confirmed_obj is not None and confirmed_obj >= data_date_from_file:
                            progress_print(f"Using cache for {day} (past day, confirmed complete by its own metadata: up to {confirmed_obj})", quiet)
                            logs_to_return = cached_logs
                            if logs_to_return: max_date_in_logs = data_date_from_file # Use actual data_date from cache
                            needs_api_fetch = False
                        else:
                            # Past day, not confirmed by its own metadata or metadata missing (old cache)
                            progress_print(f"Cache for {day} (past day) is not confirmed complete by its metadata (confirmed_up_to: {confirmed_obj}); will re-fetch.", quiet)
                            needs_api_fetch = True
            except Exception: # Includes FileNotFoundError, JSONDecodeError, KeyError from _read_cache_file
                # _read_cache_file already printed error and may have deleted corrupt file
                if force_cache:
                    progress_print(f"Cache for {day} is corrupt/unreadable and --force-cache is set; returning empty.", quiet)
                    # logs_to_return is already [], max_date_in_logs is None
                    needs_api_fetch = False
                else: # Corrupt/unreadable, not force_cache, proceed to API fetch
                    needs_api_fetch = True
        elif force_cache: # Cache does not exist, but force_cache is true
            progress_print(f"No cache for {day} and --force-cache is set; returning empty.", quiet)
            needs_api_fetch = False
        # Else (no cache, not force_cache), needs_api_fetch remains True by default

        if needs_api_fetch:
            # Don't perform any probes in fetch_day, they're now handled in stream_range
            # as appropriate (probing for dates AFTER the target range, not execution_date)
            # probe_already_done is now always True when passed from stream_range
            
            progress_print(f"Fetching from API for {day}...", quiet)
            api_params = dict(common)
            api_params.setdefault("timezone", tz_name)
            api_params["date"] = day.isoformat()
            api_params.setdefault("limit", common.get("limit", PAGE_LIMIT))

            try:
                fetched_logs_list = list(self.client.paginated("lifelogs", api_params))
                logs_to_return = fetched_logs_list

                current_max_date_val = None
                if fetched_logs_list: # Only calculate max_date if logs were actually fetched
                    for lg in fetched_logs_list:
                        dstr = lg.get("date") or lg.get("created_at") or lg.get("timestamp")
                        if dstr:
                            try:
                                d_obj = datetime.strptime(dstr[:10], API_DATE_FMT).date()
                                if current_max_date_val is None or d_obj > current_max_date_val:
                                    current_max_date_val = d_obj
                            except ValueError:
                                pass # Ignore malformed dates in logs for max_date calculation
                    max_date_in_logs = current_max_date_val if current_max_date_val else day
                
                # Write to cache, including the new confirmed_complete_up_to_date field
                self._write_cache_file(cache_path, logs_to_return, day, execution_date, execution_date, quiet)

            except ApiError as e:
                eprint(f"API error fetching data for {day}: {e}. Returning empty list for this day.", self.client.verbose)
                logs_to_return = []
                max_date_in_logs = None
                # Do not write cache on API error to avoid storing an empty list that might be misleading
            except Exception as e:
                eprint(f"Unexpected error fetching data for {day}: {e}. Returning empty list.", self.client.verbose)
                logs_to_return = []
                max_date_in_logs = None

        return logs_to_return, max_date_in_logs

    def stream_range(self, start: date, end: date,
                     common: Dict[str,Any], max_results: Optional[int]=None, quiet: bool=False, force_cache: bool=False,
                     parallel: int = 1
    ) -> Iterator[Dict[str,Any]]:
        """
        Fetches and yields logs for a date range in the specified order.

        Args:
            start: Start date
            end: End date
            common: Common API params
            max_results: Max number of results
            quiet: Suppress progress
            force_cache: Use cache only
            parallel: Number of days to fetch in parallel (threaded). Default 1 (sequential).

        Internally processes days in reverse chronological order to optimize caching,
        but yields results in the order specified by common["direction"].
        """
        # --- THREADED PARALLEL PATH ---
        if parallel > 1:
            progress_print(f"Using ThreadPoolExecutor parallel fetching with {parallel} workers", quiet)
            
            # Use a simplified threaded approach that directly delegates to the sequential version
            # but runs multiple days in parallel
            days_collected = self._threaded_stream_range_wrapper(start, end, common, max_results, quiet, force_cache, parallel)
            
            # Return the results from the threaded wrapper
            for item in days_collected:
                yield item
            
            return
        # --- END THREADED PARALLEL PATH ---

        # --- ORIGINAL SEQUENTIAL LOGIC ---
        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()

        days_in_requested_range = []
        d = start
        while d <= end:
            days_in_requested_range.append(d)
            d += timedelta(days=1)
        
        valid_days_to_process = [day_val for day_val in days_in_requested_range if day_val <= execution_date or force_cache]
        
        if not valid_days_to_process:
            progress_print(f"No dates in range {start} to {end} (up to {execution_date} or forced) to process.", quiet)
            return iter([])

        # Process valid days in reverse chronological order internally for API calls
        # (or all if force_cache)
        days_to_fetch_internally = sorted(valid_days_to_process, reverse=True)
        
        if days_to_fetch_internally:
             progress_print(f"Effective range to process (internal reverse order): {days_to_fetch_internally[0]} to {days_to_fetch_internally[-1]}", quiet and not self.client.verbose)

        logs_by_day: Dict[date, List[Dict[str,Any]]] = {}
        
        # Check if we already have cache data for a date after the requested range
        # If so, we don't need to do a probe as we know the completeness of the range
        most_recent_cached_date = None
        if not force_cache:
            max_date_in_range = max(days_to_fetch_internally)
            # Find the most recent date with non-empty cache
            # New logic: scan all cached files newer than max_date_in_range
            most_recent_cached_date = None
            if not force_cache:
                for year_dir in self.root.iterdir():
                    if not (year_dir.is_dir() and year_dir.name.isdigit()):
                        continue
                    for month_dir in year_dir.iterdir():
                        for cache_path in month_dir.glob("*.json"):
                            try:
                                dstr = cache_path.stem
                                cache_date = datetime.strptime(dstr, API_DATE_FMT).date()
                                if cache_date <= max_date_in_range or cache_date > execution_date:
                                    continue
                                logs, _, _, _ = self._read_cache_file(cache_path, cache_date)
                                if logs:
                                    most_recent_cached_date = cache_date
                                    break
                            except Exception:
                                pass
                    if most_recent_cached_date:
                        break

        # Check if all days in the range already have cache with confirmed completeness
        all_days_have_complete_cache = True
        if not force_cache:
            for day_to_check in days_to_fetch_internally:
                if day_to_check == execution_date:
                    # Today always needs fresh data
                    all_days_have_complete_cache = False
                    break
                    
                cache_path = self._path(day_to_check)
                if not cache_path.exists():
                    all_days_have_complete_cache = False
                    break
                    
                try:
                    _, data_date_from_file, _, confirmed_obj = self._read_cache_file(cache_path, day_to_check)
                    if confirmed_obj is None or confirmed_obj < data_date_from_file:
                        all_days_have_complete_cache = False
                        break
                except Exception:
                    all_days_have_complete_cache = False
                    break
        
        # Only perform a probe if:
        # 1. We're not using force-cache
        # 2. We don't have cache data for dates after the requested range
        # 3. There's a date before execution_date in our range (not just today/future)
        # 4. Not all days in the range already have confirmed complete cache
        need_probe = not force_cache and most_recent_cached_date is None and any(d < execution_date for d in days_to_fetch_internally) and not all_days_have_complete_cache
        
        # Run the data probe in a separate thread if needed
        probe_thread = None
        probe_done = False
        
        if need_probe:
            # Find a date to probe that's after our range but before execution_date
            # Prefer a date right after our range if possible
            probe_date = None
            max_date_in_range = max(days_to_fetch_internally)
            
            if max_date_in_range < execution_date:
                # Start with date after our range
                probe_date = max_date_in_range + timedelta(days=1)
                # If that's still in the future, use execution_date
                if probe_date > execution_date:
                    probe_date = execution_date
                
                progress_print(f"Will probe for completeness using date {probe_date}", quiet)
                
                # Import threading for parallel probe
                import threading
                
                def probe_thread_func():
                    nonlocal probe_done
                    self._perform_latest_data_probe(probe_date, common, execution_date, quiet)
                    probe_done = True
                
                probe_thread = threading.Thread(target=probe_thread_func)
                probe_thread.start()
        
        # Process all days
        for day_to_fetch in days_to_fetch_internally:
            # If day_to_fetch is beyond execution_date, force_cache must be true for it to be in this list.
            # fetch_day will correctly handle this due to its internal force_cache check.
            logs, _ = self.fetch_day(day_to_fetch, common, quiet=quiet, force_cache=force_cache,
                                    probe_already_done=True)  # Always set probe_already_done=True since we handle it here
            logs_by_day[day_to_fetch] = logs
        
        # Wait for probe thread to complete if it was started
        if probe_thread:
            probe_thread.join()
        
        output_order_days = []
        if common.get("direction", "desc") == "desc":
            output_order_days = sorted(days_in_requested_range, reverse=True)
        else:
            output_order_days = sorted(days_in_requested_range)

        count = 0
        for day_to_yield in output_order_days:
            if day_to_yield in logs_by_day:
                for lg in logs_by_day[day_to_yield]:
                    if max_results is not None and count >= max_results:
                        return
                    yield lg
                    count += 1
            elif force_cache:
                pass
            # else: # Not force_cache and day not in logs_by_day (e.g. future date not processed)
            #     This case should be fine, it just means no logs for that day to yield.
            #     eprint(f"[Cache] Warning: Day {day_to_yield} was in output order but not found in fetched logs_by_day.", self.client.verbose)

    def _threaded_stream_range_wrapper(self, start, end, common, max_results, quiet, force_cache, parallel):
        """
        Wrapper to run the threaded parallel fetcher and yield results.
        Uses ThreadPoolExecutor instead of asyncio for parallelism.
        """
        tz_name = common.get("timezone", DEFAULT_TZ)
        tz = get_tz(tz_name)
        execution_date = datetime.now(tz).date()

        days_in_requested_range = []
        d = start
        while d <= end:
            days_in_requested_range.append(d)
            d += timedelta(days=1)
        
        valid_days_to_process = [day_val for day_val in days_in_requested_range if day_val <= execution_date or force_cache]
        if not valid_days_to_process:
            progress_print(f"No dates in range {start} to {end} (up to {execution_date} or forced) to process.", quiet)
            return []
            
        days_to_fetch_internally = sorted(valid_days_to_process, reverse=True)
        if days_to_fetch_internally:
            progress_print(f"Effective range to process (internal reverse order): {days_to_fetch_internally[0]} to {days_to_fetch_internally[-1]}", quiet)

        # Need to do a probe first if needed
        most_recent_cached_date = None
        if not force_cache and self.root.exists():
            max_date_in_range = max(days_to_fetch_internally)
            # Find the most recent date with non-empty cache
            for year_dir in self.root.iterdir():
                if not (year_dir.is_dir() and year_dir.name.isdigit()):
                    continue
                for month_dir in year_dir.iterdir():
                    for cache_path in month_dir.glob("*.json"):
                        try:
                            dstr = cache_path.stem
                            cache_date = datetime.strptime(dstr, API_DATE_FMT).date()
                            if cache_date <= max_date_in_range or cache_date > execution_date:
                                continue
                            logs, _, _, _ = self._read_cache_file(cache_path, cache_date)
                            if logs:
                                most_recent_cached_date = cache_date
                                break
                        except Exception:
                            pass
                if most_recent_cached_date:
                    break

        # Check if all days in the range already have cache with confirmed completeness
        all_days_have_complete_cache = True
        if not force_cache:
            for day_to_check in days_to_fetch_internally:
                if day_to_check == execution_date:
                    # Today always needs fresh data
                    all_days_have_complete_cache = False
                    break
                    
                cache_path = self._path(day_to_check)
                if not cache_path.exists():
                    all_days_have_complete_cache = False
                    break
                    
                try:
                    _, data_date_from_file, _, confirmed_obj = self._read_cache_file(cache_path, day_to_check)
                    if confirmed_obj is None or confirmed_obj < data_date_from_file:
                        all_days_have_complete_cache = False
                        break
                except Exception:
                    all_days_have_complete_cache = False
                    break
        
        # Only perform a probe if needed
        need_probe = not force_cache and most_recent_cached_date is None and any(d < execution_date for d in days_to_fetch_internally) and not all_days_have_complete_cache
        
        # Run the data probe
        if need_probe:
            max_date_in_range = max(days_to_fetch_internally)
            if max_date_in_range < execution_date:
                probe_date = max_date_in_range + timedelta(days=1)
                if probe_date > execution_date:
                    probe_date = execution_date
                
                progress_print(f"[thread] Performing probe for {probe_date}", quiet)
                # Execute probe directly rather than in another thread to simplify
                self._perform_latest_data_probe(probe_date, common, execution_date, quiet)

        logs_by_day = {}

        # Define a worker function for ThreadPoolExecutor
        def fetch_one_day(day):
            try:
                progress_print(f"[thread] Fetching for {day}...", quiet)
                logs, _ = self.fetch_day(day, common, quiet=quiet, force_cache=force_cache, probe_already_done=True)
                return (day, logs)
            except Exception as e:
                eprint(f"[thread] Error in fetch_day for {day}: {e}", self.client.verbose)
                return (day, [])

        # Collect all logs from all days
        all_logs = []
        day_count = len(days_to_fetch_internally)
        
        progress_print(f"[thread] Starting parallel fetch for {day_count} days with {parallel} workers", quiet)
        
        # Use ThreadPoolExecutor to fetch days in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
            results = list(executor.map(fetch_one_day, days_to_fetch_internally))
            for day, logs in results:
                logs_by_day[day] = logs
                progress_print(f"[thread] Got {len(logs)} logs for {day}", quiet)

        # Organize results in the requested order
        if common.get("direction", "desc") == "desc":
            output_order_days = sorted(days_in_requested_range, reverse=True)
        else:
            output_order_days = sorted(days_in_requested_range)
            
        # Collect all logs in the proper order
        result_logs = []
        count = 0
        
        for day_to_yield in output_order_days:
            if day_to_yield in logs_by_day:
                day_logs = logs_by_day[day_to_yield]
                progress_print(f"[thread] Adding {len(day_logs)} logs for {day_to_yield}", quiet)
                for lg in day_logs:
                    if max_results is not None and count >= max_results:
                        progress_print(f"[thread] Reached max results limit of {max_results}", quiet)
                        return result_logs
                    result_logs.append(lg)
                    count += 1
        
        progress_print(f"[thread] Returning {len(result_logs)} total logs", quiet)
        return result_logs
                
    # Keep the old async implementation commented out for reference
    """
    def _async_stream_range_wrapper(self, start, end, common, max_results, quiet, force_cache, parallel):
        # Original async implementation removed but kept for reference
        pass
    """

# ── Time‑range Calculations ─────────────────────────────────────────────────
def get_time_range(period: str, tz: ZoneInfo) -> tuple[datetime,datetime]:
    now = datetime.now(tz)
    today = now.date()
    if period == "today":
        return (
            datetime.combine(today, time.min, tzinfo=tz),
            datetime.combine(today, time.max, tzinfo=tz),
        )
    if period == "yesterday":
        d = today - timedelta(days=1)
        return (
            datetime.combine(d, time.min, tzinfo=tz),
            datetime.combine(d, time.max, tzinfo=tz),
        )
    if period in ("this-week","last-week"):
        start_of_this = today - timedelta(days=today.weekday())
        start = start_of_this if period=="this-week" else start_of_this - timedelta(days=7)
        end = start + timedelta(days=6)
        return (
            datetime.combine(start, time.min, tzinfo=tz),
            datetime.combine(end, time.max, tzinfo=tz),
        )
    if period in ("this-month","last-month"):
        if period == "this-month":
            first = now.replace(day=1)
        else:
            if now.month == 1:
                first = now.replace(year=now.year-1, month=12, day=1)
            else:
                first = now.replace(month=now.month-1, day=1)
        if first.month == 12:
            nxt = first.replace(year=first.year+1, month=1, day=1)
        else:
            nxt = first.replace(month=first.month+1, day=1)
        last = (nxt - timedelta(days=1)).date()
        return (
            datetime.combine(first.date(), time.min, tzinfo=tz),
            datetime.combine(last, time.max, tzinfo=tz),
        )
    if period in ("this-quarter","last-quarter"):
        q = (now.month-1)//3 + 1
        if period == "this-quarter":
            m = 3*(q-1)+1
            start = now.replace(month=m, day=1)
        else:
            if q == 1:
                start = now.replace(year=now.year-1, month=10, day=1)
            else:
                m = 3*(q-2)+1
                start = now.replace(month=m, day=1)
        if start.month+3 > 12:
            nxt = start.replace(year=start.year+1, month=1, day=1)
        else:
            nxt = start.replace(month=start.month+3, day=1)
        last = (nxt - timedelta(days=1)).date()
        return (
            datetime.combine(start.date(), time.min, tzinfo=tz),
            datetime.combine(last, time.max, tzinfo=tz),
        )
    raise ValueError(f"Unknown period: {period}")

# ── Output Helpers ───────────────────────────────────────────────────────────
def stream_json(gen: Iterator[Dict[str,Any]]):
    sys.stdout.write("[")
    first = True
    for lg in gen:
        if not first:
            sys.stdout.write(",")
        json.dump(lg, sys.stdout, separators=(",",":"))
        first = False
    sys.stdout.write("]\n")
    sys.stdout.flush()

def print_markdown(gen: Iterator[Dict[str,Any]]):
    for lg in gen:
        md = lg.get("markdown") or lg.get("data",{}).get("markdown","")
        if md:
            print(md)

# ── Command Handlers ────────────────────────────────────────────────────────
def handle_list(args, quiet=False):
    progress_print("Starting data fetch...", quiet)
    client = ApiClient(verbose=args.verbose)
    parallel = getattr(args, "parallel", 1)
    common = {
        "timezone": args.timezone or DEFAULT_TZ,
        "direction": args.direction,
        **({"includeMarkdown":"false"} if not args.include_markdown else {}),
        **({"includeHeadings":"false"} if not args.include_headings else {}),
    }
    if args.date or (args.start and args.end):
        tz = get_tz(common["timezone"])
        if args.date:
            sd = ed = parse_date(args.date)
        else:
            sd = parse_datetime(args.start, tz).date()
            ed = parse_datetime(args.end, tz).date()
        cm = CacheManager(client)
        force_cache = getattr(args, "force_cache", False)
        progress_print(f"Processing logs from {sd} to {ed}...", quiet)
        gen = cm.stream_range(sd, ed, common, max_results=args.limit, quiet=quiet, force_cache=force_cache, parallel=parallel)
    else:
        progress_print("Fetching logs (unbounded date range)...", quiet)
        gen = client.paginated("lifelogs", common, max_results=args.limit)
    if args.raw:
        stream_json(gen)
    else:
        print_markdown(gen)
    # progress_print("Fetch complete.", quiet)

def handle_get(args):
    client = ApiClient(verbose=args.verbose)
    params: Dict[str,Any] = {}
    if not args.include_markdown:
        params["includeMarkdown"] = "false"
    if not args.include_headings:
        params["includeHeadings"] = "false"
    eprint(f"Fetching lifelog ID '{args.id}'...", args.verbose)
    result = client.request(f"lifelogs/{args.id}", params)
    if args.raw:
        print(json.dumps(result, indent=2))
    else:
        md = result.get("markdown") or result.get("data",{}).get("markdown")
        if md:
            print(md)
        else:
            print(json.dumps(result, indent=2))

def handle_time_relative(args, period, quiet=False):
    tz = get_tz(args.timezone or DEFAULT_TZ)
    try:
        start_dt, end_dt = get_time_range(period, tz)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    args.start = start_dt.strftime(API_DATETIME_FMT)
    args.end   = end_dt.strftime(API_DATETIME_FMT)
    args.date  = None
    args.direction = "asc"
    args.timezone = tz.key
    handle_list(args, quiet=quiet)

def handle_get_date(args, quiet=False):
    """Handler for the 'get' command that fetches logs for a specific date spec."""
    tz = get_tz(args.timezone or DEFAULT_TZ)
    target_date = parse_date_spec(args.date_spec, tz)

    if not target_date:
        print(f"Error: Invalid date specification '{args.date_spec}'", file=sys.stderr)
        sys.exit(1)

    # Modify args in place to be suitable for handle_list for a single date
    args.date = target_date.isoformat()
    args.start = None
    args.end = None
    args.direction = getattr(args, 'direction', 'desc') # Allow overriding default if needed, but usually desc for single day

    # Clear any potentially conflicting args from other commands (though unlikely with required subcommands)
    if hasattr(args, 'id'): delattr(args, 'id')

    progress_print(f"Fetching logs for date: {args.date}", quiet)
    handle_list(args, quiet=quiet)

def handle_week(args, quiet=False):
    """Handler for the 'week' command that fetches logs for a specific week spec."""
    tz = get_tz(args.timezone or DEFAULT_TZ)
    week_dates = parse_week_spec(args.week_spec)

    if not week_dates:
        print(f"Error: Invalid week specification '{args.week_spec}'", file=sys.stderr)
        sys.exit(1)

    start_date, end_date = week_dates

    # Combine dates with min/max times and timezone for the API range
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt   = datetime.combine(end_date, time.max, tzinfo=tz)

    # Modify args in place to be suitable for handle_list for the week range
    args.start = start_dt.strftime(API_DATETIME_FMT)
    args.end   = end_dt.strftime(API_DATETIME_FMT)
    args.date  = None # Ensure single date flag is not set
    args.direction = getattr(args, 'direction', 'asc') # Default to ascending for week view

    # Clear any potentially conflicting args
    if hasattr(args, 'id'): delattr(args, 'id')

    progress_print(f"Fetching logs for week: {args.week_spec} ({start_date} to {end_date})", quiet)
    handle_list(args, quiet=quiet)

# ── CLI Setup ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Limitless CLI - Interact with the API")

    # Common arguments moved to the main parser
    parser.add_argument("-v","--verbose", action="store_true", help="Enable verbose output for debugging.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress messages to stderr.")
    parser.add_argument("--raw", action="store_true", help="Output raw JSON instead of formatted markdown.")
    parser.add_argument("--include-markdown", action=argparse.BooleanOptionalAction, default=True, help="Include markdown in the output.")
    parser.add_argument("--include-headings", action=argparse.BooleanOptionalAction, default=True, help="Include headings in the markdown output.")
    parser.add_argument("-fc", "--force-cache", action="store_true", help="Force use of cache only; do not fetch from API.")
    parser.add_argument("--timezone", type=str, help=f"Timezone for date calculations (default: {DEFAULT_TZ}).")
    parser.add_argument("--limit", type=int, help="Maximum number of results to return.")
    parser.add_argument("--version", action="version", version="%(prog)s 0.7.0")
    # parser.add_argument("-p", "--parallel", type=int, default=5, help="Number of days to fetch in parallel (async, requires aiohttp).") # Moved to subparsers

    # Subcommands are now optional - CHANGED BACK TO REQUIRED (must provide a command)
    subs = parser.add_subparsers(dest="cmd", title="Commands", required=True)

    # --- list command --- (common args removed, inherited from main parser)
    p_list = subs.add_parser("list", help="List lifelogs within a specified range or for a specific date.")
    p_list.add_argument("-p", "--parallel", type=int, default=5, help="Number of days to fetch in parallel (async, requires aiohttp).")
    list_group = p_list.add_mutually_exclusive_group()
    list_group.add_argument("--date", type=str, metavar="YYYY-MM-DD", help="Fetch logs for a single specific date.")
    list_group.add_argument("--start", type=str, metavar=API_DATETIME_FMT, help="Start datetime for fetching logs (requires --end).")
    p_list.add_argument("--end", type=str, metavar=API_DATETIME_FMT, help="End datetime for fetching logs (requires --start).")
    p_list.add_argument("--direction", choices=["asc","desc"], default="desc", help="Sort direction for logs.")
    p_list.set_defaults(func=handle_list)
    # Require start/end together if one is specified
    p_list.add_argument_group('start/end constraint').add_argument("constraints", help=argparse.SUPPRESS, action='store_const', const=True)
    # Basic validation (more robust validation happens in handler)
    def check_list_args(args):
        if args.start and not args.end:
            parser.error("argument --start requires --end")
        if args.end and not args.start:
            parser.error("argument --end requires --start")
    p_list.set_defaults(check=check_list_args)

    # --- get-lifelog-by-id command --- (RENAMED from 'get')
    p_get_id = subs.add_parser("get-lifelog-by-id", help="Get a specific lifelog by its ID.")
    p_get_id.add_argument("id", type=str, help="The ID of the lifelog to retrieve.")
    p_get_id.set_defaults(func=handle_get) # Still uses original handle_get

    # --- get command (New) ---
    p_get_date = subs.add_parser("get", help="Get logs for a specific date using flexible format (YYYY-MM-DD, M/D, d-N, w-N, etc.). Inherits common flags like --raw, --limit.")
    p_get_date.add_argument("date_spec", type=str, help="The date specification (e.g., 2024-07-15, 7/15, d-1, w-2).")
    p_get_date.add_argument("-p", "--parallel", type=int, default=5, help="Number of days to fetch in parallel (async, requires aiohttp).")
    # Optional: Add direction override if needed, otherwise defaults to desc in handler
    # p_get_date.add_argument("--direction", choices=["asc","desc"], help="Sort direction for logs (defaults to desc for single day).")
    p_get_date.set_defaults(func=handle_get_date)

    # --- week command (New) ---
    p_week = subs.add_parser("week", help="Get logs for a specific week number (e.g., 7) or ISO week (e.g., 2024-W07). Inherits common flags.")
    p_week.add_argument("week_spec", type=str, help="The week specification (number or YYYY-WNN).")
    p_week.add_argument("-p", "--parallel", type=int, default=5, help="Number of days to fetch in parallel (async, requires aiohttp).")
    # Optional: Allow overriding direction for week view
    p_week.add_argument("--direction", choices=["asc","desc"], help="Sort direction for logs (defaults to asc for week view).")
    p_week.set_defaults(func=handle_week)

    # --- Relative time period commands --- (common args removed)
    periods = ["today","yesterday","this-week","last-week",
               "this-month","last-month","this-quarter","last-quarter"]
    for per in periods:
        p_time = subs.add_parser(per, help=f"Fetch logs for {per.replace('-', ' ')}.")
        p_time.add_argument("-p", "--parallel", type=int, default=5, help="Number of days to fetch in parallel (async, requires aiohttp).")
        # No other args needed here, they are inherited from main
        p_time.set_defaults(func=lambda args, per=per: handle_time_relative(args, per, quiet=getattr(args, "quiet", False)))

    # Use parse_known_args to handle the optional positional potentially conflicting with subcommands - REVERTED
    # args, unknown = parser.parse_known_args()
    args = parser.parse_args()


    # --- Argument Processing Logic --- (Simplified back to standard subcommand dispatch)

    # Run subcommand argument checks if defined
    if hasattr(args, 'check') and callable(args.check):
        args.check(args)

    # Execute the subcommand function
    import inspect
    if "quiet" in inspect.signature(args.func).parameters:
        args.func(args, quiet=args.quiet)
    else:
        args.func(args)

    # -- Old complex logic removed --

if __name__=="__main__":
    try:
        import requests
    except ImportError:
        print("Error: install requests (`pip install requests`)", file=sys.stderr)
        sys.exit(1)
    main()


"""
==========================
Limitless API Documentation
==========================

## Authentication

All API requests require authentication using an API key.

Include your API key in the `X-API-Key` header with each request:

```bash
curl -H "X-API-Key: YOUR_API_KEY" https://api.limitless.ai/v1/lifelogs
```

You can obtain an API key from the Developer settings in your Limitless account.

---

## Endpoints

**Note:** The Developer API is currently in beta and only supports Pendant data. More endpoints will be added soon.

### GET /v1/lifelogs

Returns a list of lifelog entries based on specified time range or date.

#### Query Parameters

| Parameter         | Type      | Description                                                                                  |
|-------------------|-----------|----------------------------------------------------------------------------------------------|
| timezone          | string    | IANA timezone specifier. If missing, UTC is used. Optional.                                  |
| date              | string    | Will return all entries beginning on a date in the given timezone (YYYY-MM-DD).              |
| start             | string    | Start datetime in modified ISO-8601 format (YYYY-MM-DD or YYYY-MM-DD HH:mm:SS).             |
| end               | string    | End datetime in modified ISO-8601 format (YYYY-MM-DD or YYYY-MM-DD HH:mm:SS).               |
| cursor            | string    | Cursor for pagination to retrieve the next set of lifelogs. Optional.                        |
| direction         | string    | Sort direction for lifelogs. Allowed values: asc, desc. Default: desc                        |
| includeMarkdown   | boolean   | Whether to include markdown content in the response. Default: true                           |
| includeHeadings   | boolean   | Whether to include headings in the response. Default: true                                   |
| limit             | integer   | Maximum number of lifelogs to return. (Max value is 10; use the cursor parameter for pagination). Default: 3 |

#### Response

Returns a 200 status code with the following response body:

```json
{
  "data": {
    "lifelogs": [
      {
        "id": "string",
        "title": "string",
        "markdown": "string",
        "startTime": "ISO-8601 string",
        "endTime": "ISO-8601 string",
        "contents": [
          {
            "type": "heading1" | "heading2" | "blockquote",
            "content": "string",
            "startTime": "ISO-8601 string",
            "endTime": "ISO-8601 string",
            "startOffsetMs": "timestamp in milliseconds",
            "endOffsetMs": "timestamp in milliseconds",
            "children": [],
            "speakerName": "string",
            "speakerIdentifier": "user" | null
          }
        ]
      }
    ]
  },
  "meta": {
    "lifelogs": {
      "nextCursor": "string",
      "count": 0
    }
  }
}
```

#### Example Request

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://api.limitless.ai/v1/lifelogs?date=2025-03-11&timezone=America/Los_Angeles"
```

#### Example Code (TypeScript)

```typescript
const params = new URLSearchParams({
  date: '2025-03-11',
  timezone: 'America/Los_Angeles'
});
const response = await fetch(`https://api.limitless.ai/v1/lifelogs?${params}`, {
  method: 'GET',
  headers: {
    'X-API-Key': 'YOUR_API_KEY',
  },
});
```

#### Example Code (Python)

```python
import requests

response = requests.get('https://api.limitless.ai/v1/lifelogs', params={
  'date': '2025-03-11',
  'timezone': 'America/Los_Angeles'
}, headers={'X-API-Key': 'YOUR_API_KEY'})
```

---

### GET /v1/lifelogs/{lifelog_id}

Returns a specific lifelog entry by ID.

#### Path Parameters

| Parameter     | Type    | Description                                 |
|---------------|---------|---------------------------------------------|
| lifelog_id    | string  | The ID of the lifelog entry to retrieve.    |

#### Query Parameters

| Parameter         | Type      | Description                                               |
|-------------------|-----------|-----------------------------------------------------------|
| includeMarkdown   | boolean   | Whether to include markdown content in the response. Default: true |
| includeHeadings   | boolean   | Whether to include headings in the response. Default: true         |

#### Response

Returns a 200 status code with the following response body:

```json
{
  "data": {
    "lifelog": {
      "id": "string",
      "title": "string",
      "markdown": "string",
      "startTime": "ISO-8601 string",
      "endTime": "ISO-8601 string",
      "contents": [
        {
          "type": "heading1" | "heading2" | "blockquote",
          "content": "string",
          "startTime": "ISO-8601 string",
          "endTime": "ISO-8601 string",
          "startOffsetMs": "timestamp in milliseconds",
          "endOffsetMs": "timestamp in milliseconds",
          "children": [],
          "speakerName": "string",
          "speakerIdentifier": "user" | null
        }
      ]
    }
  }
}
```

#### Example Request

```bash
curl -H "X-API-Key: YOUR_API_KEY" \
  "https://api.limitless.ai/v1/lifelogs/123"
```

#### Example Code (TypeScript)

```typescript
const response = await fetch('https://api.limitless.ai/v1/lifelogs/123', {
  method: 'GET',
  headers: {
    'X-API-Key': 'YOUR_API_KEY',
  },
});
```

#### Example Code (Python)

```python
import requests

response = requests.get('https://api.limitless.ai/v1/lifelogs/123', headers={'X-API-Key': 'YOUR_API_KEY'})
```

---

## OpenAPI Specification

openapi: 3.0.3
info:
  title: Limitless Developer API
  description: API for accessing lifelogs, providing transparency and portability to user data.
  version: 1.0.0
servers:
  - url: https://api.limitless.ai/
    description: Production server

tags:
  - name: Lifelogs
    description: Operations related to lifelogs data

components:
  schemas:
    ContentNode:
      type: object
      properties:
        type:
          type: string
          description: Type of content node (e.g., heading1, heading2, heading3, blockquote). More types might be added.
        content:
          type: string
          description: Content of the node.
        startTime:
          type: string
          format: date-time
          description: ISO format in given timezone.
        endTime:
          type: string
          format: date-time
          description: ISO format in given timezone.
        startOffsetMs:
          type: integer
          description: Milliseconds after start of this entry.
        endOffsetMs:
          type: integer
          description: Milliseconds after start of this entry.
        children:
          type: array
          items:
            $ref: "#/components/schemas/ContentNode"
          description: Child content nodes.
        speakerName:
          type: string
          description: Speaker identifier, present for certain node types (e.g., blockquote).
          nullable: true
        speakerIdentifier:
          type: string
          description: Speaker identifier, when applicable. Set to "user" when the speaker has been identified as the user.
          enum: ["user"]
          nullable: true

    Lifelog:
      type: object
      properties:
        id:
          type: string
          description: Unique identifier for the entry.
        title:
          type: string
          description: Title of the entry. Equal to the first heading1 node.
        markdown:
          type: string
          description: Raw markdown content of the entry.
          nullable: true
        contents:
          type: array
          items:
            $ref: "#/components/schemas/ContentNode"
          description: List of ContentNodes.
        startTime:
          type: string
          format: date-time
          description: ISO format in given timezone.
        endTime:
          type: string
          format: date-time
          description: ISO format in given timezone.

    MetaLifelogs:
      type: object
      properties:
        nextCursor:
          type: string
          description: Cursor for pagination to retrieve the next set of lifelogs.
          nullable: true
        count:
          type: integer
          description: Number of lifelogs in the current response.

    Meta:
      type: object
      properties:
        lifelogs:
          $ref: "#/components/schemas/MetaLifelogs"

    LifelogsResponseData:
      type: object
      properties:
        lifelogs:
          type: array
          items:
            $ref: "#/components/schemas/Lifelog"

    LifelogsResponse:
      type: object
      properties:
        data:
          $ref: "#/components/schemas/LifelogsResponseData"
        meta:
          $ref: "#/components/schemas/Meta"

paths:
  /v1/lifelogs:
    get:
      operationId: getLifelogs
      summary: Returns a list of lifelogs.
      description: Returns a list of lifelogs based on specified time range or date.
      tags:
        - Lifelogs
      parameters:
        - in: query
          name: timezone
          schema:
            type: string
          description: IANA timezone specifier. If missing, UTC is used.
        - in: query
          name: date
          schema:
            type: string
            format: date
          description: Will return all entries beginning on a date in the given timezone (YYYY-MM-DD).
        - in: query
          name: start
          schema:
            type: string
            format: date-time
          description: Start datetime in modified ISO-8601 format (YYYY-MM-DD or YYYY-MM-DD HH:mm:SS). Timezones/offsets will be ignored.
        - in: query
          name: end
          schema:
            type: string
            format: date-time
          description: End datetime in modified ISO-8601 format (YYYY-MM-DD or YYYY-MM-DD HH:mm:SS). Timezones/offsets will be ignored.
        - in: query
          name: cursor
          schema:
            type: string
          description: Cursor for pagination to retrieve the next set of entries.
        - in: query
          name: direction
          schema:
            type: string
            enum: ["asc", "desc"]
            default: "desc"
          description: Sort direction for entries.
        - in: query
          name: includeMarkdown
          schema:
            type: boolean
            default: true
          description: Whether to include markdown content in the response.
        - in: query
          name: includeHeadings
          schema:
            type: boolean
            default: true
          description: Whether to include headings in the response.
        - in: query
          name: limit
          schema:
            type: integer
          description: Maximum number of entries to return.
      responses:
        "200":
          description: Successful response with entries.
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/LifelogsResponse"
"""
# info:
#   title: Limitless Developer API
#   description: API for accessing lifelogs, providing transparency and portability to user data.
#   version: 1.0.0
# servers:
#   - url: https://api.limitless.ai/
#     description: Production server

# tags:
#   - name: Lifelogs
#     description: Operations related to lifelogs data

# components:
#   schemas:
#     ContentNode
#       type: object
#       properties:
#         type:
#           type: string # type: ignore
#           description: Type of content node (e.g., heading1, heading2, heading3, blockquote). More types might be added.
#         content:
#           type: string
#           description: Content of the node.
#         startTime:
#           type: string
#           format: date-time
#           description: ISO format in given timezone.
#         endTime:
#           type: string
#           format: date-time
#           description: ISO format in given timezone.
#         startOffsetMs:
#           type: integer
#           description: Milliseconds after start of this entry.
#         endOffsetMs:
#           type: integer
#           description: Milliseconds after start of this entry.
#         children:
#           type: array
#           items:
#             $ref: "#/components/schemas/ContentNode"
#           description: Child content nodes.
#         speakerName:
#           type: string
#           description: Speaker identifier, present for certain node types (e.g., blockquote).
#           nullable: true
#         speakerIdentifier:
#           type: string
#           description: Speaker identifier, when applicable. Set to "user" when the speaker has been identified as the user.
#           enum: ["user"]
#           nullable: true

#     Lifelog:
#       type: object
#       properties:
#         id:
#           type: string
#           description: Unique identifier for the entry.
#         title:
#           type: string
#           description: Title of the entry. Equal to the first heading1 node.
#         markdown:
#           type: string
#           description: Raw markdown content of the entry.
#           nullable: true
#         contents:
#           type: array
#           items:
#             $ref: "#/components/schemas/ContentNode"
#           description: List of ContentNodes.
#         startTime:
#           type: string
#           format: date-time
#           description: ISO format in given timezone.
#         endTime:
#           type: string
#           format: date-time
#           description: ISO format in given timezone.

#     MetaLifelogs:
#       type: object
#       properties:
#         nextCursor:
#           type: string
#           description: Cursor for pagination to retrieve the next set of lifelogs.
#           nullable: true
#         count:
#           type: integer
#           description: Number of lifelogs in the current response.

#     Meta:
#       type: object
#       properties:
#         lifelogs:
#           $ref: "#/components/schemas/MetaLifelogs"

#     LifelogsResponseData:
#       type: object
#       properties:
#         lifelogs:
#           type: array
#           items:
#             $ref: "#/components/schemas/Lifelog"

#     LifelogsResponse:
#       type: object
#       properties:
#         data:
#           $ref: "#/components/schemas/LifelogsResponseData"
#         meta:
#           $ref: "#/components/schemas/Meta"

# paths:
#   /v1/lifelogs:
#     get:
#       operationId: getLifelogs
#       summary: Returns a list of lifelogs.
#       description: Returns a list of lifelogs based on specified time range or date.
#       tags:
#         - Lifelogs
#       parameters:
#         - in: query
#           name: timezone
#           schema:
#             type: string
#           description: IANA timezone specifier. If missing, UTC is used.
#         - in: query
#           name: date
#           schema:
#             type: string
#             format: date
#           description: Will return all entries beginning on a date in the given timezone (YYYY-MM-DD).
#         - in: query
#           name: start
#           schema:
#             type: string
#             format: date-time
#           description: Start datetime in modified ISO-8601 format (YYYY-MM-DD or YYYY-MM-DD HH:mm:SS). Timezones/offsets will be ignored.
#         - in: query
#           name: end
#           schema:
#             type: string
#             format: date-time
#           description: End datetime in modified ISO-8601 format (YYYY-MM-DD or YYYY-MM-DD HH:mm:SS). Timezones/offsets will be ignored.
#         - in: query
#           name: cursor
#           schema:
#             type: string
#           description: Cursor for pagination to retrieve the next set of entries.
#         - in: query
#           name: direction
#           schema:
#             type: string
#             enum: ["asc", "desc"]
#             default: "desc"
#           description: Sort direction for entries.
#         - in: query
#           name: includeMarkdown
#           schema:
#             type: boolean
#             default: true
#           description: Whether to include markdown content in the response.
#         - in: query
#           name: includeHeadings
#           schema:
#             type: boolean
#             default: true
#           description: Whether to include headings in the response.
#         - in: query
#           name: limit
#           schema:
#             type: integer
#           description: Maximum number of entries to return.
#       responses:
#         "200":
#           description: Successful response with entries.
#           content:
#             application/json:
#               schema:
#                 $ref: "#/components/schemas/LifelogsResponse"
