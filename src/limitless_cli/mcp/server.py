"""FastMCP server implementation for Limitless CLI.

This module provides an MCP server that exposes commands for fetching
Limitless AI transcription logs by date or shorthand (today, yesterday).
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastmcp import FastMCP

from ..api.high_level import LimitlessAPI
from ..cache.manager import CacheManager
from ..core.constants import DEFAULT_TZ
from ..core.utils import get_tz, parse_date

__all__ = ["create_server", "run_server"]


def create_server() -> FastMCP:
    """Create and configure the FastMCP server with Limitless CLI tools."""
    
    server = FastMCP(
        name="limitless-cli",
        version="0.7.0"
    )
    
    @server.tool
    def fetch_day(
        date_spec: str,
        timezone: str = DEFAULT_TZ,
        include_markdown: bool = True,
        include_headings: bool = True,
        raw: bool = False
    ):
        """Fetch Limitless AI logs for a specific date.
        
        Args:
            date_spec: Date specification - either YYYY-MM-DD format or shorthand ('today', 'yesterday')
            timezone: Timezone for date calculations (default: UTC)
            include_markdown: Include markdown content in results
            include_headings: Include headings in markdown output
            raw: Return raw JSON instead of formatted results
            
        Returns:
            Dictionary containing the logs and metadata for the requested date
        """
        try:
            # Parse date specification
            tz = get_tz(timezone)
            target_date = _parse_date_spec(date_spec, tz)
            
            if target_date is None:
                return {
                    "error": f"Invalid date specification: {date_spec}",
                    "valid_formats": ["YYYY-MM-DD", "today", "yesterday"]
                }
            
            # Set up API and cache manager
            api = LimitlessAPI()
            cache_manager = CacheManager(api=api, verbose=False)
            
            # Prepare common parameters
            common_params = {
                "timezone": timezone,
                "direction": "desc",
            }
            
            if not include_markdown:
                common_params["includeMarkdown"] = "false"
            if not include_headings:
                common_params["includeHeadings"] = "false"
            
            # Fetch logs for the target date
            logs, max_date = cache_manager.fetch_day(
                target_date,
                common_params,
                quiet=True,
                force_cache=False
            )
            
            # Format response
            result = {
                "date": target_date.isoformat(),
                "timezone": timezone,
                "logs_count": len(logs),
                "logs": logs if raw else _format_logs_for_display(logs),
                "max_date_in_logs": max_date.isoformat() if max_date else None
            }
            
            return result
            
        except Exception as exc:
            return {
                "error": f"Failed to fetch logs: {str(exc)}",
                "date_spec": date_spec,
                "timezone": timezone
            }
    
    return server


def _parse_date_spec(date_spec: str, tz):
    """Parse a date specification string into a date object.
    
    Args:
        date_spec: Date specification - YYYY-MM-DD, 'today', or 'yesterday'
        tz: Timezone object for relative date calculations
        
    Returns:
        Parsed date object or None if invalid
    """
    date_spec = date_spec.strip().lower()
    
    if date_spec == "today":
        return datetime.now(tz).date()
    elif date_spec == "yesterday":
        return (datetime.now(tz).date() - timedelta(days=1))
    else:
        # Try to parse as YYYY-MM-DD
        try:
            return parse_date(date_spec)
        except (ValueError, TypeError):
            return None


def _format_logs_for_display(logs):
    """Format raw log entries for better display in MCP clients.
    
    Args:
        logs: Raw log entries from the API
        
    Returns:
        Formatted log entries with key fields highlighted
    """
    formatted_logs = []
    
    for log in logs:
        formatted_log = {
            "id": log.get("id"),
            "title": log.get("title", ""),
            "start_time": log.get("startTime", ""),
            "end_time": log.get("endTime", ""),
            "markdown": log.get("markdown", ""),
        }
        
        # Include content summary if available
        contents = log.get("contents", [])
        if contents:
            formatted_log["content_summary"] = {
                "sections": len(contents),
                "first_section_type": contents[0].get("type", "") if contents else "",
                "preview": contents[0].get("content", "")[:200] + "..." if contents and contents[0].get("content") else ""
            }
        
        formatted_logs.append(formatted_log)
    
    return formatted_logs


def run_server() -> None:
    """Run the MCP server using stdio transport."""
    server = create_server()
    
    try:
        # Run the server with stdio transport (standard for MCP)
        server.run()
    except KeyboardInterrupt:
        print("\nMCP server stopped.", file=sys.stderr)
    except Exception as exc:
        print(f"MCP server error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_server() 