"""Limitless CLI – programmatic API and command-line interface for the
Limitless lifelog service.

The public API is **experimental** and may change before a formal v1.0.0
release.
"""

from __future__ import annotations

__all__: list[str] = ["main", "__version__"]
__version__: str = "0.7.0"

# The real CLI entry point will live in ``limitless_cli.cli.entry``.  We import
# it lazily here so that ``python -m limitless_cli`` and console‐script entry
# points can resolve the function without extra indirection once the refactor
# is complete.
try:
    from .cli.entry import main  # noqa: F401 – re-export
except ModuleNotFoundError:
    # During the initial skeleton phase, cli.entry may not yet exist.
    def main() -> None:  # type: ignore[misc]
        """Placeholder CLI until the submodule is implemented."""

        import sys

        print(
            "Limitless CLI package skeleton created. CLI implementation pending.",
            file=sys.stderr,
        )
        sys.exit(1) 