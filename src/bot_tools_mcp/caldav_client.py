"""CalDAV transport — talks to Radicale as a given bot.

Identity-free in spirit: the caller passes the bot's username + password (derived
by the tool layer from the authenticated bot). This layer connects, **discovers**
the bot's one calendar (its collection path is a UUID assigned by Radicale's web
UI, so it is never hardcoded), and does the raw event I/O.

caldav's synchronous client is used and run in a worker thread by the tool layer,
so the async tools never block the event loop. `require_tls=False` because the
internal Radicale URL is plain `http://radicale:5232` on `ollama-net`.

An `event_id` is the event's iCalendar **UID** — an opaque, stable handle the bot
gets back from create/list and passes to delete. The bot never constructs a path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent


@dataclass
class CalEvent:
    """A calendar event in the shape tools return to bots."""

    event_id: str  # the iCal UID — opaque handle for delete
    title: str
    start: str  # ISO 8601
    end: str  # ISO 8601
    description: str = ""
    location: str = ""


class CalDavError(RuntimeError):
    """Raised when a CalDAV operation fails; message names the server."""


def _connect(url: str, bot: str, password: str):
    """Open a DAVClient as `bot` and return its Principal.

    Imported lazily so the module imports without a live caldav in odd envs.
    """
    import caldav

    try:
        client = caldav.DAVClient(
            url=url,
            username=bot,
            password=password,
            require_tls=False,
        )
        return client.principal()
    except Exception as exc:  # noqa: BLE001 — surface any connect failure loudly
        raise CalDavError(f"CalDAV connect to {url} as {bot!r} failed: {exc}") from exc


def _discover_calendar(url: str, bot: str, password: str):
    """Return the bot's one calendar. owner_only means it sees only its own."""
    principal = _connect(url, bot, password)
    calendars = principal.calendars()
    if not calendars:
        raise CalDavError(f"bot {bot!r} has no calendar on {url}")
    # Each bot has exactly one calendar (Pattern A). If somehow more, take the
    # first stably — but that's a provisioning smell worth surfacing.
    return calendars[0]


def _build_vevent(
    *,
    uid: str,
    title: str,
    start: datetime,
    end: datetime,
    description: str = "",
    location: str = "",
    organizer: str | None = None,
    attendees: list[str] | None = None,
    method: str | None = None,
) -> bytes:
    """Assemble a VEVENT (wrapped in a VCALENDAR) as iCalendar bytes."""
    cal = ICalendar()
    cal.add("prodid", "-//bot-tools-mcp//EN")
    cal.add("version", "2.0")
    if method:
        cal.add("method", method)

    ev = IEvent()
    ev.add("uid", uid)
    ev.add("summary", title)
    ev.add("dtstart", start)
    ev.add("dtend", end)
    ev.add("dtstamp", datetime.now(timezone.utc))
    if description:
        ev.add("description", description)
    if location:
        ev.add("location", location)
    if organizer:
        ev.add("organizer", f"mailto:{organizer}")
    for a in attendees or []:
        ev.add("attendee", f"mailto:{a}")

    cal.add_component(ev)
    return cal.to_ical()


def _event_to_calevent(event) -> CalEvent:
    """Map a caldav Event to our CalEvent shape."""
    ical = event.icalendar_instance
    for comp in ical.walk("VEVENT"):
        return CalEvent(
            event_id=str(comp.get("uid", "")),
            title=str(comp.get("summary", "")),
            start=_ical_dt(comp.get("dtstart")),
            end=_ical_dt(comp.get("dtend")),
            description=str(comp.get("description", "")),
            location=str(comp.get("location", "")),
        )
    raise CalDavError("event has no VEVENT component")


def _ical_dt(prop) -> str:
    """ISO-format an icalendar date/datetime property (or '' if absent)."""
    if prop is None:
        return ""
    dt = getattr(prop, "dt", prop)
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


# --- the operations the tool layer calls (sync; wrapped in a thread there) ---


def create_event(
    url: str,
    bot: str,
    password: str,
    *,
    title: str,
    start: datetime,
    end: datetime,
    description: str = "",
    location: str = "",
) -> str:
    """Create an event on the bot's calendar; return its opaque event_id (UID)."""
    calendar = _discover_calendar(url, bot, password)
    uid = f"{uuid.uuid4()}@bot-tools-mcp"
    ical = _build_vevent(
        uid=uid,
        title=title,
        start=start,
        end=end,
        description=description,
        location=location,
    )
    try:
        calendar.save_event(ical.decode())
    except Exception as exc:  # noqa: BLE001
        raise CalDavError(f"save_event on {url} as {bot!r} failed: {exc}") from exc
    return uid


def list_events(
    url: str,
    bot: str,
    password: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[CalEvent]:
    """List events on the bot's calendar, optionally within [start, end]."""
    calendar = _discover_calendar(url, bot, password)
    try:
        if start and end:
            found = calendar.search(start=start, end=end, event=True, expand=False)
        else:
            found = calendar.events()
    except Exception as exc:  # noqa: BLE001
        raise CalDavError(f"list events on {url} as {bot!r} failed: {exc}") from exc
    return [_event_to_calevent(e) for e in found]


def delete_event(url: str, bot: str, password: str, *, event_id: str) -> None:
    """Delete the event with this UID from the bot's calendar."""
    calendar = _discover_calendar(url, bot, password)
    try:
        event = calendar.event_by_uid(event_id)
    except Exception as exc:  # noqa: BLE001
        raise CalDavError(
            f"event {event_id!r} not found on {url} for {bot!r}: {exc}"
        ) from exc
    try:
        event.delete()
    except Exception as exc:  # noqa: BLE001
        raise CalDavError(f"delete of {event_id!r} on {url} failed: {exc}") from exc


def build_invite_ics(
    *,
    organizer: str,
    attendees: list[str],
    title: str,
    start: datetime,
    end: datetime,
    description: str = "",
    location: str = "",
) -> tuple[str, bytes]:
    """Build a REQUEST-method VEVENT for an invite. Returns (uid, ics_bytes)."""
    uid = f"{uuid.uuid4()}@bot-tools-mcp"
    ics = _build_vevent(
        uid=uid,
        title=title,
        start=start,
        end=end,
        description=description,
        location=location,
        organizer=organizer,
        attendees=attendees,
        method="REQUEST",
    )
    return uid, ics


def save_ics(url: str, bot: str, password: str, *, ics: bytes) -> None:
    """Save a pre-built ICS (e.g. an invite) to the bot's calendar."""
    calendar = _discover_calendar(url, bot, password)
    try:
        calendar.save_event(ics.decode())
    except Exception as exc:  # noqa: BLE001
        raise CalDavError(f"save invite on {url} as {bot!r} failed: {exc}") from exc
