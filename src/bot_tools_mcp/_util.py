"""Small shared helpers used across tool modules and transports."""

from __future__ import annotations

import posixpath
from datetime import datetime

from fastmcp.exceptions import ToolError


class BackendError(RuntimeError):
    """One base for every backend-I/O failure (SMTP, CalDAV, Nextcloud).

    Transports raise this (or a subclass) with a human message that names the
    failing host/operation. The tool layer catches this single type and turns it
    into a `ToolError` — see `to_tool_error`.
    """


def require_env(env: dict[str, str], name: str) -> str:
    """Fetch a required env var, failing loud if missing or empty.

    The single source of truth for "an unfilled placeholder must never
    authenticate or configure anyone."
    """
    value = env.get(name)
    if not value:
        raise KeyError(f"required environment variable {name!r} is missing or empty")
    return value


def to_tool_error(exc: Exception) -> ToolError:
    """Coerce a backend exception into a ToolError, passing existing ones through.

    The one place the "surface backend failures loudly as ToolErrors" rule lives,
    shared by every tool module.
    """
    return exc if isinstance(exc, ToolError) else ToolError(str(exc))


def safe_path(path: str) -> str:
    """Normalize a bot-supplied file path to a clean relative path, or raise.

    Rejects absolute paths and any `..` traversal so a bot can never escape its
    own root. Returns a normalized relative path (no leading slash). Input
    validation, so it lives here beside `parse_iso`, not in a transport.
    """
    if path is None or not path.strip():
        raise ToolError("'path' is required")
    raw = path.strip()
    if raw.startswith("/") or raw.startswith("\\"):
        raise ToolError(f"'path' must be relative, not absolute: {path!r}")
    # normpath collapses './' and resolves segments; then reject any surviving '..'.
    normalized = posixpath.normpath(raw)
    if ".." in normalized.split("/") or normalized.startswith("/"):
        raise ToolError(f"'path' must not escape the bot's root: {path!r}")
    return normalized


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
