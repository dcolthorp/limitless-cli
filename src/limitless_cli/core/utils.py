"""General-purpose helper functions shared across the package."""

from __future__ import annotations

import sys
from typing import Any, Optional, Tuple

from datetime import datetime, date, timedelta, time
import os
import re
import calendar
from zoneinfo import ZoneInfo

from .constants import (
    API_DATE_FMT,
    API_DATETIME_FMT,
    API_KEY_ENV_VAR,
)

# ---------------------------------------------------------------------------
# Low-level I/O helpers
# ---------------------------------------------------------------------------

def eprint(msg: str, verbose: bool | None = None) -> None:
    """Write *msg* to stderr when *verbose* is truthy."""

    if verbose:
        print(msg, file=sys.stderr)


def progress_print(msg: str, quiet: bool = False) -> None:
    """Write *msg* to stderr unless *quiet* is True."""

    if not quiet:
        print(msg, file=sys.stderr)

# ---------------------------------------------------------------------------
# Stubbed functions – full implementations will be migrated in later tasks.
# ---------------------------------------------------------------------------

def get_tz(name: str) -> Any:  # pragma: no cover – to be replaced
    """Return a zoneinfo object for *name*.

    This is a thin wrapper around :pyclass:`zoneinfo.ZoneInfo` designed so we
    can centralize fall-backs and error handling.  The real logic will be moved
    over in a subsequent task.
    """

    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        print(
            f"Warning: Timezone '{name}' not found; falling back to UTC.",
            file=sys.stderr,
        )
        return ZoneInfo("UTC")


def get_api_key() -> str:
    """Return the Limitless API key from environment.

    Exits the program with a helpful error when the variable is missing so that
    downstream code does not have to sprinkle try/except blocks.
    """

    key = os.environ.get(API_KEY_ENV_VAR)
    if not key:
        print(f"Error: Missing {API_KEY_ENV_VAR}", file=sys.stderr)
        sys.exit(1)
    return key


# ---------------------------------------------------------------------------
# Parsing helpers – migrated from the original script
# ---------------------------------------------------------------------------

def parse_date(s: str) -> date:
    """Parse a YYYY-MM-DD string into a :pyclass:`datetime.date`."""

    try:
        return datetime.strptime(s, API_DATE_FMT).date()
    except ValueError as exc:
        print(f"Invalid date '{s}' (expected YYYY-MM-DD).", file=sys.stderr)
        raise exc


def parse_datetime(s: str, tz: ZoneInfo) -> datetime:
    """Parse a YYYY-MM-DD HH:MM:SS string in *tz*."""

    try:
        return datetime.strptime(s, API_DATETIME_FMT).replace(tzinfo=tz)
    except ValueError as exc:
        print(
            f"Invalid datetime '{s}' (expected YYYY-MM-DD HH:MM:SS).",
            file=sys.stderr,
        )
        raise exc


def parse_date_spec(spec: str, tz: ZoneInfo) -> Optional[date]:
    """Return a concrete date for flexible *spec* strings.

    Supports:
    1. Exact YYYY-MM-DD
    2. M/D or MM/DD (most recent past occurrence)
    3. Relative forms like ``d-7`` (days), ``w-2`` (weeks), ``m-3`` (months),
       ``y-1`` (years)
    """

    now_date = datetime.now(tz).date()

    # 1. YYYY-MM-DD
    try:
        return datetime.strptime(spec, API_DATE_FMT).date()
    except ValueError:
        pass

    # 2. M/D or MM/DD
    try:
        month_day = datetime.strptime(spec, "%m/%d")
        target_date = now_date.replace(month=month_day.month, day=month_day.day)
        if target_date > now_date:
            target_date = target_date.replace(year=now_date.year - 1)
        return target_date
    except ValueError:
        pass

    # 3. Relative d/w/m/y - N
    match = re.match(r"([dwmy])-(\d+)", spec.lower())
    if match:
        unit, num_str = match.groups()
        num = int(num_str)
        if unit == "d":
            return now_date - timedelta(days=num)
        if unit == "w":
            return now_date - timedelta(weeks=num)
        if unit == "m":
            # Month arithmetic – rough approximation.
            target_month = now_date.month - num
            target_year = now_date.year
            while target_month <= 0:
                target_month += 12
                target_year -= 1
            max_days = calendar.monthrange(target_year, target_month)[1]
            target_day = min(now_date.day, max_days)
            return date(target_year, target_month, target_day)
        if unit == "y":
            try:
                return now_date.replace(year=now_date.year - num)
            except ValueError:
                # Handle Feb-29 → Feb-28 when the target year is not leap.
                return now_date.replace(year=now_date.year - num, month=2, day=28)

    eprint(f"Invalid date specification: '{spec}'", True)
    return None


def parse_week_spec(spec: str) -> Optional[Tuple[date, date]]:
    """Convert a week *spec* (N or YYYY-WNN) into (start_date, end_date)."""

    now = datetime.now()
    current_year = now.year

    # 1. Integer week number (assume current year)
    if re.fullmatch(r"\d{1,2}", spec):
        week_num = int(spec)
        if not 1 <= week_num <= 53:
            eprint("Week number out of range (1-53)", True)
            return None
        iso_week_str = f"{current_year}-W{week_num:02d}"
    # 2. YYYY-WNN format
    elif re.fullmatch(r"\d{4}-W\d{2}", spec):
        iso_week_str = spec
        year_part, week_part = spec.split("-W")
        week_num = int(week_part)
        if not 1 <= week_num <= 53:
            eprint("Week number out of range (1-53) in ISO format", True)
            return None
    else:
        eprint(f"Invalid week specification format: '{spec}'", True)
        return None

    try:
        start_date = datetime.strptime(f"{iso_week_str}-1", "%G-W%V-%u").date()
        end_date = start_date + timedelta(days=6)
        return start_date, end_date
    except ValueError:
        eprint(f"Cannot determine dates for week specification: '{iso_week_str}'", True)
        return None


# ---------------------------------------------------------------------------
# Higher-level time range helper
# ---------------------------------------------------------------------------

def get_time_range(period: str, tz: ZoneInfo) -> Tuple[datetime, datetime]:
    """Return (start, end) datetimes representing *period*.

    Supported periods: today, yesterday, this-week, last-week, this-month,
    last-month, this-quarter, last-quarter.
    """

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

    if period in ("this-week", "last-week"):
        start_of_this = today - timedelta(days=today.weekday())
        start = start_of_this if period == "this-week" else start_of_this - timedelta(days=7)
        end = start + timedelta(days=6)
        return (
            datetime.combine(start, time.min, tzinfo=tz),
            datetime.combine(end, time.max, tzinfo=tz),
        )

    if period in ("this-month", "last-month"):
        if period == "this-month":
            first = now.replace(day=1)
        else:
            if now.month == 1:
                first = now.replace(year=now.year - 1, month=12, day=1)
            else:
                first = now.replace(month=now.month - 1, day=1)

        if first.month == 12:
            nxt = first.replace(year=first.year + 1, month=1, day=1)
        else:
            nxt = first.replace(month=first.month + 1, day=1)
        last = (nxt - timedelta(days=1)).date()
        return (
            datetime.combine(first.date(), time.min, tzinfo=tz),
            datetime.combine(last, time.max, tzinfo=tz),
        )

    if period in ("this-quarter", "last-quarter"):
        q = (now.month - 1) // 3 + 1
        if period == "this-quarter":
            m = 3 * (q - 1) + 1
            start = now.replace(month=m, day=1)
        else:
            if q == 1:
                start = now.replace(year=now.year - 1, month=10, day=1)
            else:
                m = 3 * (q - 2) + 1
                start = now.replace(month=m, day=1)

        if start.month + 3 > 12:
            nxt = start.replace(year=start.year + 1, month=1, day=1)
        else:
            nxt = start.replace(month=start.month + 3, day=1)
        last = (nxt - timedelta(days=1)).date()
        return (
            datetime.combine(start.date(), time.min, tzinfo=tz),
            datetime.combine(last, time.max, tzinfo=tz),
        )

    raise ValueError(f"Unknown period: {period}") 