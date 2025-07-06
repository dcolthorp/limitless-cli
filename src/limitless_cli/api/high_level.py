"""Typed, convenience wrapper around the low-level :pyclass:`ApiClient`.

The existing :pymod:`limitless_cli.api.client` module exposes a *thin* HTTP
wrapper.  This file builds on top of it to provide **Pythonic**, typed methods
that map 1-to-1 to the public REST API operations documented in
:doc:`../../docs/api_reference`.

The design separates *transport* (HTTP vs. mock) from *business logic* via a
simple :class:`Transport` protocol, enabling easy in-memory mocks for unit
testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Literal, Optional, Protocol, TypedDict, cast

from .client import ApiClient  # Low-level HTTP implementation

__all__: list[str] = [
    "Transport",
    "HTTPTransport",
    "MockTransport",
    "LimitlessAPI",
    "Lifelog",
    "ContentNode",
]


# ---------------------------------------------------------------------------
# TypedDict JSON schemas for stronger typing
# ---------------------------------------------------------------------------


ContentNodeType = Literal[
    "heading1",
    "heading2",
    "heading3",
    "blockquote",
    "paragraph",
    "transcript",
]


class ContentNodeJSON(TypedDict, total=False):
    type: ContentNodeType
    content: str
    startTime: str
    endTime: str
    startOffsetMs: int
    endOffsetMs: int
    speakerName: str
    speakerIdentifier: Optional[str]
    children: List["ContentNodeJSON"]


class LifelogJSON(TypedDict, total=False):
    id: str
    title: str
    markdown: str
    startTime: str
    endTime: str
    contents: List[ContentNodeJSON]
    # convenience field present in mocks
    date: str


class ResponseJSON(TypedDict):
    data: Dict[str, Any]
    meta: Dict[str, Any]


class Transport(Protocol):
    """Abstract transport — low-level single-request API."""

    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ...


class HTTPTransport(ApiClient):
    """Concrete transport that *is* the existing :class:`ApiClient`."""

    # Nothing to add – it already implements the methods.


class MockTransport(Transport):
    """In-memory fake suitable for deterministic unit tests."""

    def __init__(self, fixtures: Dict[str, List[ResponseJSON]]):
        # Map endpoint -> list of payloads (paginated). Index is simulated cursor.
        self.fixtures = fixtures
        self.request_log: List[tuple[str, Dict[str, Any]]] = []

    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        self.request_log.append((endpoint, params))
        pages = self.fixtures.get(endpoint, [])
        idx = 0
        cursor = params.get("cursor")
        if cursor is not None and str(cursor).isdigit():
            idx = int(cursor)
        if idx < len(pages):
            return cast(Dict[str, Any], pages[idx])
        return cast(Dict[str, Any], {"data": {"lifelogs": []}, "meta": {"lifelogs": {"nextCursor": None}}})


# ---------------------------------------------------------------------------
# In-memory, behaviour-accurate transport (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryTransport(Transport):
    """Lightweight simulation of the Limitless lifelogs API.

    Only implements the ``/lifelogs`` endpoint sufficient for unit testing
    cache logic.  Additional endpoints can be added on demand.
    """

    def __init__(self, lifelogs: Optional[List[LifelogJSON]] = None):
        self._lifelogs: List[LifelogJSON] = lifelogs[:] if lifelogs else []

    # ----------------------- seeding helpers --------------------

    def seed(self, *logs: LifelogJSON) -> None:  # noqa: D401 – util
        """Append one or more lifelog JSON objects to the in-memory store."""

        self._lifelogs.extend(logs)

    # ----------------------- Transport API ----------------------

    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
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


# ---------------------------------------------------------------------------
# Typed response models (subset – expand as needed)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ContentNode:
    type: ContentNodeType
    content: str
    startTime: str
    endTime: str


@dataclass(slots=True)
class Lifelog:
    id: str
    title: str
    startTime: str
    endTime: str
    markdown: Optional[str]
    contents: List[ContentNode]

    @staticmethod
    def from_json(obj: Dict[str, Any]) -> "Lifelog":  # noqa: D401 – factory
        return Lifelog(
            id=str(obj.get("id", "")),
            title=obj.get("title", ""),
            startTime=obj.get("startTime", ""),
            endTime=obj.get("endTime", ""),
            markdown=obj.get("markdown"),
            contents=[
                ContentNode(
                    type=c.get("type", "paragraph"),
                    content=c.get("content", ""),
                    startTime=c.get("startTime", ""),
                    endTime=c.get("endTime", ""),
                )
                for c in obj.get("contents", [])
            ],
        )


# ---------------------------------------------------------------------------
# High-level service wrapper
# ---------------------------------------------------------------------------


class LimitlessAPI:
    """Typed convenience layer over the Limitless REST API."""

    def __init__(self, transport: Transport | None = None):
        self.transport: Transport = transport or HTTPTransport()

    # --------------------- internal helpers --------------------

    def _paginate(
        self,
        endpoint: str,
        base_params: Dict[str, Any],
        *,
        max_results: Optional[int] = None,
    ) -> Iterable[Dict[str, Any]]:
        """Internal generator handling Limitless cursor pagination."""

        cursor: Optional[str] = None
        fetched = 0
        first = True
        while True:
            params = dict(base_params)
            if cursor:
                params["cursor"] = cursor

            payload = self.transport.request(endpoint, params)
            logs = payload.get("data", {}).get("lifelogs", [])
            meta = payload.get("meta", {}).get("lifelogs", {})
            cursor = meta.get("nextCursor")

            if not logs and not first:
                break
            if not logs and first:
                break

            for lg in logs:
                if max_results is not None and fetched >= max_results:
                    return
                yield lg
                fetched += 1
                first = False

            if not cursor or (max_results is not None and fetched >= max_results):
                break

    # --------------------- public API --------------------------

    def lifelogs(
        self,
        *,
        date_: Optional[date] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timezone: str | None = None,
        limit: int | None = None,
        **extra: Any,
    ) -> List[Lifelog]:
        """Return lifelogs for a date or range."""

        params: Dict[str, Any] = {"includeMarkdown": True, "includeHeadings": True}
        if timezone:
            params["timezone"] = timezone
        if date_:
            params["date"] = date_.isoformat()
        if start:
            params["start"] = start.strftime("%Y-%m-%d %H:%M:%S")
        if end:
            params["end"] = end.strftime("%Y-%m-%d %H:%M:%S")
        if limit is not None:
            params["limit"] = limit
        params.update(extra)

        logs_iter = self._paginate("lifelogs", params, max_results=limit)
        return [Lifelog.from_json(lg) for lg in logs_iter] 