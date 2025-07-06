"""Mock transport implementation for testing."""

from __future__ import annotations

from typing import Any, Dict, List, cast

from .base import Transport


class ResponseJSON:
    """Type hint for response JSON structure."""
    pass


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