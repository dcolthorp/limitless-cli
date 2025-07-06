"""Cache backend abstractions and reference implementations.

This module defines *interfaces* (using ``typing.Protocol``) that allow the
:class:`~limitless_cli.cache.manager.CacheManager` to operate independently of
how cache data are **persisted**.  The default implementation uses the local
filesystem, replicating the behaviour of the original, monolithic
``CacheManager``.  However, alternative back-ends – such as an in-memory
variant for unit-tests or a SQLite-powered persistent store – can be written by
conforming to the :class:`CacheBackend` protocol.

The manager only needs three high-level operations:

1. *read*   – obtain a day's cached logs (if any)
2. *write*  – persist logs plus metadata for a given day
3. *scan*   – quickly enumerate what days are present in the cache and whether
              they are confirmed complete

By funnelling all file-system interaction through this small surface area we
can unit-test the caching logic deterministically (e.g. against an in-memory
back-end) and we can add new storage engines without touching the algorithm.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from ..core.constants import API_DATE_FMT, CACHE_ROOT, DEFAULT_TZ
from ..core.utils import get_tz, parse_date

__all__: list[str] = [
    "CacheEntry",
    "CacheBackend",
    "FilesystemCacheBackend",
    "InMemoryCacheBackend",
]


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


# ---------------------------------------------------------------------------
# Filesystem implementation (parity with original behaviour)
# ---------------------------------------------------------------------------


class FilesystemCacheBackend(CacheBackend):
    """Drop-in replacement that stores JSON files on disk.

    Directory layout matches the original script so existing caches continue
    to work::

        ~/.limitless/cache/2024/07/2024-07-06.json
    """

    _WRITE_LOCK = threading.Lock()

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or CACHE_ROOT.expanduser()

    # ----------------------- Helpers -----------------------
    def _path(self, d: date) -> Path:
        return self.root / f"{d:%Y/%m}" / f"{d.isoformat()}.json"

    # Expose for compatibility
    def path(self, day: date) -> Path:  # type: ignore[override]
        return self._path(day)

    def _from_payload(self, payload: Any, expected_date: date) -> CacheEntry:
        if isinstance(payload, list):  # legacy format (just an array)
            return CacheEntry(payload, expected_date, expected_date, None)
        return CacheEntry(
            payload["logs"],
            parse_date(payload["data_date"]),
            parse_date(payload["fetched_on_date"]),
            parse_date(payload["confirmed_complete_up_to_date"])
            if payload.get("confirmed_complete_up_to_date")
            else None,
        )

    def _to_payload(self, entry: CacheEntry) -> Dict[str, Any]:
        return {
            "data_date": entry.data_date.isoformat(),
            "fetched_on_date": entry.fetched_on_date.isoformat(),
            "logs": entry.logs,
            "confirmed_complete_up_to_date": entry.confirmed_complete_up_to_date.isoformat()
            if entry.confirmed_complete_up_to_date
            else None,
        }

    # ----------------------- API ---------------------------
    def read(self, day: date) -> Optional[CacheEntry]:  # noqa: D401 – keep signature minimal
        path = self._path(day)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
            return self._from_payload(payload, day)
        except Exception:  # noqa: BLE001 – corrupt file; treat as missing
            path.unlink(missing_ok=True)
            return None

    def write(self, entry: CacheEntry) -> None:
        path = self._path(entry.data_date)
        payload = self._to_payload(entry)
        with self._WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(path)

    def scan(self, execution_date: date) -> Dict[date, Tuple[bool, Optional[date]]]:
        result: Dict[date, Tuple[bool, Optional[date]]] = {}
        if not self.root.exists():
            return result
        for year_dir in self.root.iterdir():
            if not (year_dir.is_dir() and year_dir.name.isdigit() and len(year_dir.name) == 4):
                continue
            for month_dir in year_dir.iterdir():
                if not (month_dir.is_dir() and month_dir.name.isdigit() and len(month_dir.name) == 2):
                    continue
                for cache_file_path in month_dir.glob("*.json"):
                    try:
                        d = datetime.strptime(cache_file_path.stem, API_DATE_FMT).date()
                        if d > execution_date:
                            continue
                        payload = json.loads(cache_file_path.read_text())
                        entry = self._from_payload(payload, d)
                        result[d] = (bool(entry.logs), entry.confirmed_complete_up_to_date)
                    except Exception:  # noqa: BLE001 – ignore unreadable files
                        continue
        return result


# ---------------------------------------------------------------------------
# In-memory implementation (useful for unit tests)
# ---------------------------------------------------------------------------


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