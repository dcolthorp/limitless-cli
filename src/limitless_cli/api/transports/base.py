"""Base protocol for API transports."""

from __future__ import annotations

from typing import Any, Dict, Protocol


class Transport(Protocol):
    """Abstract transport — low-level single-request API."""

    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        ... 