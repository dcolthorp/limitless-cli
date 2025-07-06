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
from .transports import Transport, HTTPTransport, MockTransport, InMemoryTransport

__all__: list[str] = [
    "Transport",
    "HTTPTransport",
    "MockTransport",
    "InMemoryTransport",
    "LimitlessAPI",
    "Lifelog",
    "ContentNode",
    "LifelogJSON",
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