"""Command handler functions for Limitless CLI.

Each handler corresponds to a sub-command (e.g. `list`, `get`, `week`).  The
functions will be migrated verbatim from *limitless.py* in subsequent tasks.
"""

from __future__ import annotations

from datetime import datetime, time
import sys
import json as _json

from typing import Any

from ..api.client import ApiClient
from ..cache.manager import CacheManager
from ..core.constants import DEFAULT_TZ, API_DATETIME_FMT
from ..core.utils import (
    eprint,
    progress_print,
    get_tz,
    parse_date,
    parse_datetime,
    parse_date_spec,
    parse_week_spec,
    get_time_range,
)
from ..output.formatters import stream_json, print_markdown  # noqa: F401

__all__: list[str] = [
    "handle_list",
    "handle_get",
    "handle_get_date",
    "handle_week",
]


# ---------------------------------------------------------------------------
# Stub implementations – raise for now so we remember to port logic.
# ---------------------------------------------------------------------------

def handle_list(args: Any, quiet: bool = False) -> None:  # noqa: ANN401
    """Fetch and print lifelogs for a date or datetime range."""

    client = ApiClient(verbose=args.verbose)
    from ..api.high_level import LimitlessAPI

    api = LimitlessAPI(client)
    parallel = getattr(args, "parallel", 1)

    common: dict[str, Any] = {
        "timezone": args.timezone or DEFAULT_TZ,
        "direction": args.direction,
        **({"includeMarkdown": "false"} if not args.include_markdown else {}),
        **({"includeHeadings": "false"} if not args.include_headings else {}),
    }

    if args.date or (args.start and args.end):
        tz = get_tz(common["timezone"])
        if args.date:
            start_date = end_date = parse_date(args.date)
        else:
            start_date = parse_datetime(args.start, tz).date()
            end_date = parse_datetime(args.end, tz).date()

        cm = CacheManager(api=api, verbose=args.verbose)
        force_cache = getattr(args, "force_cache", False)
        if not quiet:
            progress_print(f"Processing logs from {start_date} to {end_date}…", quiet)

        gen = cm.stream_range(
            start_date,
            end_date,
            common,
            max_results=args.limit,
            quiet=quiet,
            force_cache=force_cache,
            parallel=parallel,
        )
    else:
        if not quiet:
            progress_print("Fetching logs (unbounded date range)…", quiet)
        gen = client.paginated("lifelogs", common, max_results=args.limit)

    if args.raw:
        stream_json(gen)
    else:
        print_markdown(gen)


def handle_get(args: Any) -> None:  # noqa: ANN401
    """Fetch an individual lifelog entry by ID."""

    client = ApiClient(verbose=args.verbose)
    params: dict[str, Any] = {}
    if not args.include_markdown:
        params["includeMarkdown"] = "false"
    if not args.include_headings:
        params["includeHeadings"] = "false"

    eprint(f"Fetching lifelog ID '{args.id}'…", args.verbose)
    result = client.request(f"lifelogs/{args.id}", params)

    if args.raw:
        print(_json.dumps(result, indent=2))
    else:
        md = result.get("markdown") or result.get("data", {}).get("markdown")
        if md:
            print(md)
        else:
            print(_json.dumps(result, indent=2))


def handle_get_date(args: Any, quiet: bool = False) -> None:  # noqa: ANN401
    """Support flexible single-date specifications (e.g. d-1, 7/15)."""

    tz = get_tz(args.timezone or DEFAULT_TZ)
    target_date_opt = parse_date_spec(args.date_spec, tz)

    if target_date_opt is None:
        print(f"Error: Invalid date specification '{args.date_spec}'", file=sys.stderr)
        sys.exit(1)

    target_date = target_date_opt
    args.date = target_date.isoformat()
    args.start = None
    args.end = None
    args.direction = getattr(args, "direction", "desc")
    if hasattr(args, "id"):
        delattr(args, "id")

    if not quiet:
        progress_print(f"Fetching logs for date: {args.date}", quiet)
    handle_list(args, quiet=quiet)


def handle_week(args: Any, quiet: bool = False) -> None:  # noqa: ANN401
    """Fetch logs for a given ISO week number (N or YYYY-WNN)."""

    tz = get_tz(args.timezone or DEFAULT_TZ)
    week_dates_opt = parse_week_spec(args.week_spec)

    if week_dates_opt is None:
        print(f"Error: Invalid week specification '{args.week_spec}'", file=sys.stderr)
        sys.exit(1)

    start_date, end_date = week_dates_opt
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt = datetime.combine(end_date, time.max, tzinfo=tz)

    args.start = start_dt.strftime(API_DATETIME_FMT)
    args.end = end_dt.strftime(API_DATETIME_FMT)
    args.date = None
    args.direction = getattr(args, "direction", "asc")
    if hasattr(args, "id"):
        delattr(args, "id")

    if not quiet:
        progress_print(
            f"Fetching logs for week: {args.week_spec} ({start_date} to {end_date})",
            quiet,
        )
    handle_list(args, quiet=quiet)


def handle_time_relative(args: Any, period: str, quiet: bool = False) -> None:  # noqa: ANN401
    """Helper for relative period commands like 'today' or 'last-week'."""

    tz = get_tz(args.timezone or DEFAULT_TZ)
    try:
        start_dt, end_dt = get_time_range(period, tz)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    args.start = start_dt.strftime(API_DATETIME_FMT)
    args.end = end_dt.strftime(API_DATETIME_FMT)
    args.date = None
    args.direction = "asc"
    args.timezone = tz.key
    handle_list(args, quiet=quiet) 