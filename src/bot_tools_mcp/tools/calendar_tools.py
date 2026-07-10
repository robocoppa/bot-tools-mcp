"""Calendar tools — Radicale (CalDAV), scoped per bot.

Every op runs as the authenticated bot: username = bot name, password =
`RADICALE_PASS_<BOT>` (Stage 2 `owner_only`, so a bot only ever sees its own
calendar). The calendar's collection path is a UUID, so the transport discovers
it rather than hardcoding — see `caldav_client`.

The synchronous caldav client runs in a worker thread (`asyncio.to_thread`) so
these async tools never block the event loop.

`send_calendar_invite` both saves the event to the bot's calendar AND emails the
`.ics` (method=REQUEST) via the same Brevo path `send_email` uses — the From is
the bot's own address, derived from identity.
"""

from __future__ import annotations

import asyncio

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from bot_tools_mcp import caldav_client as cal
from bot_tools_mcp._util import parse_iso, to_tool_error
from bot_tools_mcp.email_smtp import SmtpConfig, build_invite_message, send_message
from bot_tools_mcp.identity import Identity
from bot_tools_mcp.server import bot_creds


def register(mcp: FastMCP, identity: Identity, smtp: SmtpConfig | None = None):
    """Attach the calendar tools; return them as a dict for direct unit testing.

    `smtp` is injectable; defaults to env at startup (invites need email).
    """
    smtp_config = smtp or SmtpConfig.from_env()
    url = identity.radicale_url()

    async def _run(fn, *args, **kwargs):
        """Run a sync CalDAV transport op in a thread, surfacing failures loud."""
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as exc:
            raise to_tool_error(exc) from exc

    @mcp.tool
    async def create_event(
        ctx: Context,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> str:
        """Create an event on the calling bot's calendar.

        `start`/`end` are ISO-8601 datetimes. Returns an opaque `event_id` you
        pass to `delete_event`.
        """
        bot, pw = await bot_creds(ctx, identity.radicale_password)
        s, e = parse_iso(start, "start"), parse_iso(end, "end")
        return await _run(
            cal.create_event, url, bot, pw,
            title=title, start=s, end=e, description=description, location=location,
        )

    @mcp.tool
    async def list_events(ctx: Context, start: str = "", end: str = "") -> list[dict]:
        """List the calling bot's events, optionally within [start, end] (ISO-8601).

        Each event carries an `event_id` usable with `delete_event`.
        """
        bot, pw = await bot_creds(ctx, identity.radicale_password)
        s = parse_iso(start, "start") if start else None
        e = parse_iso(end, "end") if end else None
        if (s is None) != (e is None):
            raise ToolError("provide both 'start' and 'end', or neither")
        events = await _run(cal.list_events, url, bot, pw, start=s, end=e)
        return [vars(ev) for ev in events]

    @mcp.tool
    async def delete_event(ctx: Context, event_id: str) -> str:
        """Delete an event from the calling bot's calendar by its `event_id`."""
        if not event_id or not event_id.strip():
            raise ToolError("'event_id' is required")
        bot, pw = await bot_creds(ctx, identity.radicale_password)
        await _run(cal.delete_event, url, bot, pw, event_id=event_id.strip())
        return f"deleted {event_id}"

    @mcp.tool
    async def send_calendar_invite(
        ctx: Context,
        to: list[str],
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
    ) -> str:
        """Invite people to an event: save it to the bot's calendar AND email the
        `.ics` invitation (method=REQUEST) from the bot's own address.

        `to` is the attendee list; `start`/`end` are ISO-8601.
        """
        bot, pw = await bot_creds(ctx, identity.radicale_password)
        attendees = [a.strip() for a in (to or []) if a and a.strip()]
        if not attendees:
            raise ToolError("'to' must contain at least one attendee")
        organizer = identity.from_address(bot)
        s, e = parse_iso(start, "start"), parse_iso(end, "end")

        _uid, ics = cal.build_invite_ics(
            organizer=organizer, attendees=attendees, title=title,
            start=s, end=e, description=description, location=location,
        )
        # 1. save to the bot's calendar
        await _run(cal.save_ics, url, bot, pw, ics=ics)
        # 2. email the invite — send_message names the smarthost on failure; we
        #    prefix so the bot knows the event WAS saved even if the mail failed.
        msg = build_invite_message(
            sender=organizer, to=attendees,
            subject=f"Invitation: {title}",
            body=description or f"You're invited to {title}.",
            ics=ics,
        )
        try:
            await send_message(msg, smtp_config)
        except Exception as exc:
            raise ToolError(f"invite saved but {exc}") from exc
        return f"invited {', '.join(attendees)} to {title!r} (from {organizer})"

    return {
        "create_event": create_event,
        "list_events": list_events,
        "delete_event": delete_event,
        "send_calendar_invite": send_calendar_invite,
    }
