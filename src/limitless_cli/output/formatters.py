"""Output formatting utilities migrated from the monolithic script."""

from __future__ import annotations

import json
import sys
from typing import Iterator, Dict, Any

__all__: list[str] = ["stream_json", "print_markdown"]


def stream_json(gen: Iterator[Dict[str, Any]]) -> None:
    """Write an iterator of JSON-able dicts as a compact JSON array."""

    sys.stdout.write("[")
    first = True
    for item in gen:
        if not first:
            sys.stdout.write(",")
        json.dump(item, sys.stdout, separators=(",", ":"))
        first = False
    sys.stdout.write("]\n")
    sys.stdout.flush()


def print_markdown(gen: Iterator[Dict[str, Any]]) -> None:
    """Extract and print the markdown field of each lifelog."""

    for item in gen:
        md = item.get("markdown") or item.get("data", {}).get("markdown", "")
        if md:
            print(md) 