"""Filesystem-based cache backend implementation."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ...core.constants import API_DATE_FMT, CACHE_ROOT
from ...core.utils import parse_date
from .base import CacheBackend, CacheEntry


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