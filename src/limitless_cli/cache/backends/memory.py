"""In-memory cache backend implementation for testing."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple

from .base import CacheBackend, CacheEntry


class InMemoryCacheBackend(CacheBackend):
    """Volatile cache – great for fast, isolated unit tests."""

    def __init__(self) -> None:  # noqa: D401 – keep trivial
        self._store: Dict[date, CacheEntry] = {}

    def read(self, day: date) -> Optional[CacheEntry]:
        entry = self._store.get(day)
        if entry is None:
            return None
        
        # Handle legacy format (plain list) and corrupted data
        try:
            if isinstance(entry, list):  # legacy format
                return CacheEntry(entry, day, day, None)
            elif isinstance(entry, str):  # corrupted data
                return None
            else:
                return entry
        except Exception:  # noqa: BLE001 – corrupted data; treat as missing
            return None

    def write(self, entry: CacheEntry) -> None:
        self._store[entry.data_date] = entry

    # ---------------------------------------------------------
    # Test utilities
    # ---------------------------------------------------------

    def reset(self) -> None:  # noqa: D401 – testing helper
        """Clear all cached entries (useful between unit tests)."""
        self._store.clear()

    def scan(self, execution_date: date) -> Dict[date, Tuple[bool, Optional[date]]]:
        result = {}
        for d, e in self._store.items():
            if d > execution_date:
                continue
            try:
                if isinstance(e, list):  # legacy format
                    result[d] = (bool(e), None)
                elif isinstance(e, str):  # corrupted data
                    continue  # skip corrupted entries
                else:  # normal CacheEntry
                    result[d] = (bool(e.logs), e.confirmed_complete_up_to_date)
            except Exception:  # noqa: BLE001 – corrupted data; skip
                continue
        return result

    # Dummy path for compatibility with legacy code paths
    def path(self, day: date) -> Path:  # type: ignore[override]
        return Path(f"/dev/null/{day.isoformat()}.json") 