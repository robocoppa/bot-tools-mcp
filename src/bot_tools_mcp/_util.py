"""Small shared helpers used across tool modules."""

from __future__ import annotations

from datetime import datetime

from fastmcp.exceptions import ToolError


def parse_iso(value: str, field_name: str) -> datetime:
    """Parse an ISO-8601 datetime a bot passed in; raise a clear ToolError if bad.

    Accepts a trailing 'Z' (UTC) which `datetime.fromisoformat` rejects on older
    Pythons — normalize it to +00:00.
    """
    if not value or not value.strip():
        raise ToolError(f"{field_name!r} is required (ISO-8601 datetime)")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ToolError(
            f"{field_name!r} is not a valid ISO-8601 datetime: {value!r}"
        ) from exc
