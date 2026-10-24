"""Small shared helpers for concise user-facing UI text."""

from __future__ import annotations


def counted(count: int, singular: str, plural: str | None = None) -> str:
    """Format a count with a natural singular or plural noun."""
    noun = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {noun}"
