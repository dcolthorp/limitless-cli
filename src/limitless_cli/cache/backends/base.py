"""Base classes and protocols for cache backends."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple


@dataclass(slots=True)
class CacheEntry:
    """Structured representation of one day's cached logs."""

    logs: List[Dict[str, Any]]
    data_date: date
    fetched_on_date: date
    confirmed_complete_up_to_date: Optional[date] = None


class CacheBackend(Protocol):
    """Minimal interface needed by :class:`CacheManager`."""

    def read(self, day: date) -> Optional[CacheEntry]:
        """Return cached entry for *day* or ``None`` if absent."""
        ...

    def write(self, entry: CacheEntry) -> None:
        """Persist *entry* atomically."""
        ...

    def scan(self, execution_date: date) -> Dict[date, Tuple[bool, Optional[date]]]:
        """Return a mapping ``{day: (has_logs, confirmed_up_to)}`` for all days 
        **≤ execution_date** currently present in the cache.
        """
        ...

    # The following helper is *optional* but used by the legacy CacheManager
    # code path for backwards compatibility.
    def path(self, day: date) -> Path:  # noqa: D401 – optional utility
        """Return a *debug* filesystem path for *day* if the backend is file-based.

        Non file-based implementations may return a dummy path; the value is
        never dereferenced when the backend handles its own I/O.
        """
        ... 