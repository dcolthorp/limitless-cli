"""Argument-parsing entry point for the ``limitless`` command-line tool."""

from __future__ import annotations

import inspect
import sys
import argparse

from ..core.constants import DEFAULT_TZ, API_DATETIME_FMT
from .commands import (
    handle_list,
    handle_get,
    handle_get_date,
    handle_week,
    handle_time_relative,
)
from ..mcp.server import run_server as handle_mcp


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level :pyclass:`argparse.ArgumentParser`."""

    parser = argparse.ArgumentParser(description="Limitless CLI – interact with the API")

    # ---------------- Common flags (inherited by all sub-parsers) ----------
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose debug output to stderr.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress messages.")
    parser.add_argument("--raw", action="store_true", help="Emit raw JSON instead of markdown.")
    parser.add_argument("--include-markdown", action=argparse.BooleanOptionalAction, default=True, help="Include markdown in output.")
    parser.add_argument("--include-headings", action=argparse.BooleanOptionalAction, default=True, help="Include headings in markdown output.")
    parser.add_argument("-fc", "--force-cache", action="store_true", help="Use cache only; skip API requests.")
    parser.add_argument("--timezone", type=str, help=f"Timezone for date calculations (default: {DEFAULT_TZ}).")
    parser.add_argument("--limit", type=int, help="Maximum number of results to return.")
    parser.add_argument("--version", action="version", version="%(prog)s 0.7.0")

    subs = parser.add_subparsers(dest="cmd", title="Commands", required=True)

    # ---------------- list ----------------
    p_list = subs.add_parser("list", help="List lifelogs for a date or datetime range.")
    p_list.add_argument("-p", "--parallel", type=int, default=5, help="Max days to fetch in parallel.")
    group = p_list.add_mutually_exclusive_group()
    group.add_argument("--date", type=str, metavar="YYYY-MM-DD", help="Single date to fetch.")
    group.add_argument("--start", type=str, metavar=API_DATETIME_FMT, help="Start datetime (requires --end).")
    p_list.add_argument("--end", type=str, metavar=API_DATETIME_FMT, help="End datetime (requires --start).")
    p_list.add_argument("--direction", choices=["asc", "desc"], default="desc", help="Sort direction.")
    p_list.set_defaults(func=handle_list)

    def _check_list(a):
        if a.start and not a.end:
            parser.error("argument --start requires --end")
        if a.end and not a.start:
            parser.error("argument --end requires --start")

    p_list.set_defaults(check=_check_list)

    # ---------------- get-lifelog-by-id ----------------
    p_get_id = subs.add_parser("get-lifelog-by-id", help="Retrieve a lifelog by its ID.")
    p_get_id.add_argument("id", type=str, help="Lifelog ID")
    p_get_id.set_defaults(func=handle_get)

    # ---------------- get (flexible date) ----------------
    p_get_date = subs.add_parser("get", help="Get logs for a flexible date spec (e.g. d-1, 7/15).")
    p_get_date.add_argument("date_spec", type=str, help="Date specification string")
    p_get_date.add_argument("-p", "--parallel", type=int, default=5, help="Max days to fetch in parallel.")
    p_get_date.set_defaults(func=handle_get_date)

    # ---------------- week ----------------
    p_week = subs.add_parser("week", help="Get logs for a specific ISO week number.")
    p_week.add_argument("week_spec", type=str, help="Week specification (N or YYYY-WNN)")
    p_week.add_argument("-p", "--parallel", type=int, default=5, help="Max days to fetch in parallel.")
    p_week.add_argument("--direction", choices=["asc", "desc"], help="Sort direction (asc default).")
    p_week.set_defaults(func=handle_week)

    # ---------------- relative period commands ----------------
    for per in [
        "today",
        "yesterday",
        "this-week",
        "last-week",
        "this-month",
        "last-month",
        "this-quarter",
        "last-quarter",
    ]:
        p_rel = subs.add_parser(per, help=f"Fetch logs for {per.replace('-', ' ')}.")
        p_rel.add_argument("-p", "--parallel", type=int, default=1, help="Max days to fetch in parallel.")
        p_rel.set_defaults(func=lambda a, per=per: handle_time_relative(a, per, quiet=getattr(a, "quiet", False)))

    # ---------------- mcp ----------------
    p_mcp = subs.add_parser("mcp", help="Start MCP server for AI integration.")
    p_mcp.set_defaults(func=lambda a: handle_mcp())

    return parser


def main() -> None:  # pragma: no cover
    """Parse CLI arguments and dispatch to command handlers."""

    parser = _build_parser()
    args = parser.parse_args()

    # Sub-command–specific validation
    if hasattr(args, "check") and callable(args.check):
        args.check(args)

    # Dispatch to handler
    if "quiet" in inspect.signature(args.func).parameters:
        args.func(args, quiet=args.quiet)
    else:
        args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main() 