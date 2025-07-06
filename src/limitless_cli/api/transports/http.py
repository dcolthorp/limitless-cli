"""HTTP transport implementation using the existing ApiClient."""

from __future__ import annotations

from ..client import ApiClient
from .base import Transport


class HTTPTransport(ApiClient, Transport):
    """Concrete transport that *is* the existing :class:`ApiClient`."""

    # Nothing to add – it already implements the methods. 