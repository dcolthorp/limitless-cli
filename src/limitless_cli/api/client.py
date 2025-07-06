"""HTTP client wrapper for the Limitless public REST API.

Provides convenient helpers for JSON decoding, automatic retries, and
cursor-based pagination while respecting API rate-limit semantics.
"""

from __future__ import annotations

import requests
import json
import sys
import time as _time_module
from typing import Any, Dict, Iterator, Optional

from ..core.constants import API_BASE_URL, API_VERSION
from ..core.utils import eprint, get_api_key

__all__: list[str] = ["ApiError", "ApiClient"]


class ApiError(Exception):
    """Raised when the Limitless API returns an error response."""


class ApiClient:
    """HTTP wrapper around the Limitless REST API (fully migrated)."""

    def __init__(self, api_key: Optional[str] = None, verbose: bool = False):
        self.key = api_key or get_api_key()
        self.verbose = verbose
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        eprint(f"[API] {msg}", self.verbose)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    def request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a GET request and decode the JSON payload.

        Retries automatically on HTTP 5xx or 429 responses (with exponential
        back-off) up to three attempts, mirroring the behaviour of the original
        script.
        """

        url = f"{API_BASE_URL}/{API_VERSION}/{endpoint.lstrip('/')}"
        headers = {"X-API-Key": self.key, "Accept": "application/json"}
        self._log(f"GET {url} params={params}")

        retries = 3
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, headers=headers, params=params, timeout=300)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                status = getattr(exc.response, "status_code", None)
                retryable = attempt < retries and (
                    status is None or status >= 500 or status == 429
                )
                if retryable:
                    wait = 0  # type: int
                    if status == 429 and getattr(exc, "response", None) is not None:
                        ra_hdrs = exc.response.headers if exc.response else {}
                        ra = ra_hdrs.get("Retry-After") if isinstance(ra_hdrs, dict) else None
                        if ra and str(ra).isdigit():
                            wait = int(ra)
                    if wait == 0:
                        wait = 2 ** (attempt - 1)
                    self._log(
                        f"Attempt {attempt} failed (status {status}); retrying in {wait}s..."
                    )
                    _time_module.sleep(wait)
                    continue

                # Non-retryable error – surface with extra context
                print(f"API error: {exc}", file=sys.stderr)
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    try:
                        print(json.dumps(exc.response.json(), indent=2), file=sys.stderr)
                    except Exception:
                        print(exc.response.text, file=sys.stderr)
                raise ApiError(str(exc)) from exc

        # Exhausted retries
        raise ApiError("Unknown error")

    def paginated(
        self,
        endpoint: str,
        params: Dict[str, Any],
        max_results: Optional[int] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield items across paginated responses.

        Transparently handles Limitless "nextCursor" mechanics and enforces
        *max_results* when provided.
        """

        cursor = params.pop("cursor", None)
        fetched = 0
        first = True
        while True:
            if cursor:
                params["cursor"] = cursor
            data = self.request(endpoint, params)
            logs = data.get("data", {}).get("lifelogs", [])
            meta = data.get("meta", {}).get("lifelogs", {})
            cursor = meta.get("nextCursor")
            count = meta.get("count", len(logs))
            self._log(f"Fetched page: {count} items, total so far {fetched}")

            if not logs and not first:
                break
            if not logs and first:
                break

            for lg in logs:
                if max_results and fetched >= max_results:
                    return
                yield lg
                fetched += 1
                first = False

            if not cursor or (max_results and fetched >= max_results):
                break 