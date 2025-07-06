"""In-memory transport implementation for testing."""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict

from .base import Transport


class ContentNodeJSON(TypedDict, total=False):
    """Type hint for content node JSON structure."""
    type: str
    content: str
    startTime: str
    endTime: str
    startOffsetMs: int
    endOffsetMs: int
    speakerName: str
    speakerIdentifier: str
    children: List["ContentNodeJSON"]


class LifelogJSON(TypedDict, total=False):
    """Type hint for lifelog JSON structure."""
    id: str
    title: str
    markdown: str
    startTime: str
    endTime: str
    contents: List[ContentNodeJSON]
    date: str


class InMemoryTransport(Transport):
    """Lightweight simulation of the Limitless lifelogs API.

    Only implements the ``/lifelogs`` endpoint sufficient for unit testing
    cache logic.  Additional endpoints can be added on demand.
    """

    def __init__(self, verbose: bool = False):
        self._lifelogs: list[LifelogJSON] = []
        self._content_nodes: dict[str, ContentNodeJSON] = {}
        self.verbose = verbose
        self.request_log: list[tuple[str, dict[str, Any]]] = []

    # ----------------------- seeding helpers --------------------

    def seed(self, *logs: LifelogJSON) -> None:  # noqa: D401 – util
        """Append one or more lifelog JSON objects to the in-memory store."""

        self._lifelogs.extend(logs)

    @property
    def requests_made(self) -> int:
        """Return the number of requests made to this transport."""
        return len(self.request_log)

    # ----------------------- test helpers ----------------------

    def reset(self) -> None:  # noqa: D401 – testing utility
        """Clear all stored logs and recorded requests (testing convenience)."""
        self._lifelogs.clear()
        self.request_log.clear()

    # ----------------------- Transport API ----------------------

    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        """Simulate a low-level Limitless API request (lifelogs only)."""

        # Track the call for assertions in unit-tests
        self.request_log.append((endpoint, dict(params)))

        if endpoint != "lifelogs":
            return {}

        # Copy params defensively
        p = dict(params)

        # --------------- filtering ---------------
        subset = self._lifelogs
        date_str = p.get("date")
        if date_str:
            subset = [lg for lg in subset if lg.get("date", lg.get("created_at", ""))[:10] == date_str]
        else:
            start = p.get("start")
            end = p.get("end")
            if start or end:
                s_dt = start[:10] if start else None
                e_dt = end[:10] if end else None
                subset = [
                    lg
                    for lg in subset
                    if (s_dt is None or lg.get("date", lg.get("created_at", ""))[:10] >= s_dt)
                    and (e_dt is None or lg.get("date", lg.get("created_at", ""))[:10] <= e_dt)
                ]

        direction = p.get("direction", "desc").lower()
        subset.sort(key=lambda lg: lg.get("date", lg.get("created_at", "")), reverse=direction == "desc")

        # --------------- pagination ---------------
        limit = int(p.get("limit", 3))
        cursor_raw = p.get("cursor")
        start_idx = int(cursor_raw) if cursor_raw and str(cursor_raw).isdigit() else 0
        page = subset[start_idx : start_idx + limit]
        next_cursor = start_idx + limit if start_idx + limit < len(subset) else None

        return {
            "data": {"lifelogs": page},
            "meta": {"lifelogs": {"nextCursor": str(next_cursor) if next_cursor is not None else None, "count": len(page)}},
        } 