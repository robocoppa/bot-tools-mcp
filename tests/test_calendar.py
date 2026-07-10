"""Calendar tool tests. Hermetic: the CalDAV transport functions are mocked
(no Radicale), the SMTP transport is mocked (no mail leaves). The pure ICS
builders run for real (icalendar, no network).
"""

from datetime import datetime

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from bot_tools_mcp import caldav_client as cal
from bot_tools_mcp.email_smtp import SmtpConfig
from bot_tools_mcp.identity import Identity
from bot_tools_mcp.tools import calendar_tools

ENV = {
    "MAIL_DOMAIN": "example.com",
    "RADICALE_URL": "http://radicale:5232",
    "BOT_TOKEN_CLAUDETTE": "tok-claudette",
    "BOT_TOKEN_DONNA": "tok-donna",
    "RADICALE_PASS_CLAUDETTE": "rad-claudette",
    "RADICALE_PASS_DONNA": "rad-donna",
}
SMTP = SmtpConfig(host="smtp-relay.brevo.com", port=587, user="u", key="k")


class _FakeCtx:
    def __init__(self, bot):
        self._bot = bot

    async def get_state(self, key):  # async, like FastMCP's Context
        return {"bot": self._bot}.get(key)


def _tools(monkeypatch, **transport_stubs):
    """Register calendar tools with transport fns stubbed; return the tool dict
    and a dict recording the args each stubbed transport fn was called with."""
    calls = {}

    def _record(name, retval=None):
        def stub(url, bot, password, **kw):
            calls[name] = {"url": url, "bot": bot, "password": password, **kw}
            if isinstance(retval, Exception):
                raise retval
            return retval

        return stub

    monkeypatch.setattr(cal, "create_event", _record("create_event", transport_stubs.get("create_event", "uid-123")))
    monkeypatch.setattr(cal, "list_events", _record("list_events", transport_stubs.get("list_events", [])))
    monkeypatch.setattr(cal, "delete_event", _record("delete_event", None))
    monkeypatch.setattr(cal, "save_ics", _record("save_ics", None))

    sent = {}

    async def fake_send(msg, config):
        sent["msg"] = msg
        sent["config"] = config

    monkeypatch.setattr(calendar_tools, "send_message", fake_send)

    tools = calendar_tools.register(FastMCP("t"), Identity(ENV), SMTP)
    return tools, calls, sent


# --- per-bot auth flows through to the transport ---


async def test_create_event_uses_bot_creds_and_returns_id(monkeypatch):
    tools, calls, _ = _tools(monkeypatch)
    event_id = await tools["create_event"](
        _FakeCtx("claudette"),
        title="Standup",
        start="2026-07-10T15:00:00",
        end="2026-07-10T15:30:00",
    )
    assert event_id == "uid-123"
    assert calls["create_event"]["bot"] == "claudette"
    assert calls["create_event"]["password"] == "rad-claudette"
    assert calls["create_event"]["url"] == "http://radicale:5232"
    assert isinstance(calls["create_event"]["start"], datetime)


async def test_different_bot_uses_its_own_password(monkeypatch):
    tools, calls, _ = _tools(monkeypatch)
    await tools["create_event"](
        _FakeCtx("donna"), title="x", start="2026-07-10T15:00", end="2026-07-10T16:00"
    )
    assert calls["create_event"]["bot"] == "donna"
    assert calls["create_event"]["password"] == "rad-donna"


async def test_unauthenticated_context_refused(monkeypatch):
    tools, _, _ = _tools(monkeypatch)
    with pytest.raises(ToolError, match="no authenticated bot"):
        await tools["create_event"](
            _FakeCtx(None), title="x", start="2026-07-10T15:00", end="2026-07-10T16:00"
        )


# --- input validation ---


async def test_bad_datetime_is_rejected(monkeypatch):
    tools, _, _ = _tools(monkeypatch)
    with pytest.raises(ToolError, match="not a valid ISO-8601"):
        await tools["create_event"](
            _FakeCtx("claudette"), title="x", start="not-a-date", end="2026-07-10T16:00"
        )


async def test_z_suffix_datetime_accepted(monkeypatch):
    tools, calls, _ = _tools(monkeypatch)
    await tools["create_event"](
        _FakeCtx("claudette"), title="x", start="2026-07-10T15:00:00Z", end="2026-07-10T16:00:00Z"
    )
    assert calls["create_event"]["start"].tzinfo is not None


async def test_list_events_requires_both_or_neither_bounds(monkeypatch):
    tools, _, _ = _tools(monkeypatch)
    with pytest.raises(ToolError, match="both 'start' and 'end', or neither"):
        await tools["list_events"](_FakeCtx("claudette"), start="2026-07-10T00:00", end="")


async def test_delete_event_requires_id(monkeypatch):
    tools, _, _ = _tools(monkeypatch)
    with pytest.raises(ToolError, match="'event_id' is required"):
        await tools["delete_event"](_FakeCtx("claudette"), event_id="  ")


# --- event_id round-trip: create returns an id delete accepts ---


async def test_event_id_round_trips_create_to_delete(monkeypatch):
    tools, calls, _ = _tools(monkeypatch)
    event_id = await tools["create_event"](
        _FakeCtx("claudette"), title="x", start="2026-07-10T15:00", end="2026-07-10T16:00"
    )
    await tools["delete_event"](_FakeCtx("claudette"), event_id=event_id)
    assert calls["delete_event"]["event_id"] == event_id


async def test_list_events_returns_dicts(monkeypatch):
    ev = cal.CalEvent(event_id="uid-9", title="Sync", start="2026-07-10T15:00:00",
                      end="2026-07-10T15:30:00", description="d", location="Zoom")
    tools, _, _ = _tools(monkeypatch, list_events=[ev])
    result = await tools["list_events"](_FakeCtx("claudette"))
    assert result == [
        {"event_id": "uid-9", "title": "Sync", "start": "2026-07-10T15:00:00",
         "end": "2026-07-10T15:30:00", "description": "d", "location": "Zoom"}
    ]


# --- invite: saves to calendar AND emails a REQUEST .ics from the bot ---


async def test_send_calendar_invite_saves_and_emails(monkeypatch):
    tools, calls, sent = _tools(monkeypatch)
    result = await tools["send_calendar_invite"](
        _FakeCtx("claudette"),
        to=["alice@example.com"],
        title="Design review",
        start="2026-07-10T15:00:00",
        end="2026-07-10T16:00:00",
        location="Jitsi",
    )
    # saved to claudette's calendar
    assert calls["save_ics"]["bot"] == "claudette"
    assert calls["save_ics"]["password"] == "rad-claudette"
    # emailed from claudette, to the attendee, as a REQUEST calendar part
    msg = sent["msg"]
    assert msg["From"] == "claudette@example.com"
    assert msg["To"] == "alice@example.com"
    payload = msg.as_string()
    assert "text/calendar" in payload
    assert 'method="REQUEST"' in payload
    assert "alice@example.com" in result


async def test_invite_requires_an_attendee(monkeypatch):
    tools, _, _ = _tools(monkeypatch)
    with pytest.raises(ToolError, match="at least one attendee"):
        await tools["send_calendar_invite"](
            _FakeCtx("claudette"), to=[], title="x",
            start="2026-07-10T15:00", end="2026-07-10T16:00",
        )


async def test_invite_reports_email_failure_loud(monkeypatch):
    # The event WAS saved; the email failed — the message must say both, and
    # send_message's SmtpError already names the smarthost.
    from bot_tools_mcp.email_smtp import SmtpError

    tools, _, _ = _tools(monkeypatch)

    async def boom(msg, config):
        raise SmtpError(f"email send failed via {config.host}:{config.port}: refused")

    monkeypatch.setattr(calendar_tools, "send_message", boom)
    with pytest.raises(ToolError, match="invite saved but email send failed via smtp-relay.brevo.com:587"):
        await tools["send_calendar_invite"](
            _FakeCtx("claudette"), to=["a@example.com"], title="x",
            start="2026-07-10T15:00", end="2026-07-10T16:00",
        )


# --- transport error surfaces as ToolError ---


async def test_transport_error_becomes_tool_error(monkeypatch):
    tools, _, _ = _tools(monkeypatch, create_event=cal.CalDavError("save_event failed"))
    with pytest.raises(ToolError, match="save_event failed"):
        await tools["create_event"](
            _FakeCtx("claudette"), title="x", start="2026-07-10T15:00", end="2026-07-10T16:00"
        )


# --- pure ICS builders (real icalendar) ---


def test_build_invite_ics_is_request_with_attendees():
    uid, ics = cal.build_invite_ics(
        organizer="claudette@example.com",
        attendees=["a@example.com", "b@example.com"],
        title="Sync",
        start=datetime(2026, 7, 10, 15, 0),
        end=datetime(2026, 7, 10, 15, 30),
    )
    assert uid.endswith("@bot-tools-mcp")
    assert b"METHOD:REQUEST" in ics
    assert b"ORGANIZER:mailto:claudette@example.com" in ics
    assert ics.count(b"ATTENDEE") == 2
