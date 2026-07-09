"""send_email tests. Hermetic: the SMTP transport is mocked, nothing leaves.

The tests that matter most here are the no-spoof ones — a bot's From is derived
from its authenticated identity, and there is no parameter through which a caller
can send as anyone else.
"""

from email.message import EmailMessage

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from bot_tools_mcp.email_smtp import (
    Attachment,
    SmtpConfig,
    build_message,
)
from bot_tools_mcp.identity import Identity
from bot_tools_mcp.tools import email_tools

ENV = {
    "MAIL_DOMAIN": "example.com",
    "BOT_TOKEN_CLAUDETTE": "tok-claudette",
    "BOT_TOKEN_DONNA": "tok-donna",
}
SMTP = SmtpConfig(host="smtp-relay.brevo.com", port=587, user="u", key="k")


class _FakeCtx:
    """Stands in for the request Context: get_state returns the authed bot."""

    def __init__(self, bot):
        self._bot = bot

    def get_state(self, key):
        return {"bot": self._bot}.get(key)


def _make_tool(monkeypatch):
    """Register send_email and stub the transport; return (tool, captured)."""
    captured = {}

    async def fake_send(msg: EmailMessage, config: SmtpConfig):
        captured["msg"] = msg
        captured["config"] = config

    monkeypatch.setattr(email_tools, "send_message", fake_send)
    tool = email_tools.register(FastMCP("t"), Identity(ENV), SMTP)
    return tool, captured


# --- the no-spoof guarantee ---


async def test_from_is_the_authenticated_bot(monkeypatch):
    tool, cap = _make_tool(monkeypatch)
    await tool(_FakeCtx("claudette"), to=["alice@example.com"], subject="s", body="b")
    assert cap["msg"]["From"] == "claudette@example.com"


async def test_different_bot_gets_its_own_from(monkeypatch):
    tool, cap = _make_tool(monkeypatch)
    await tool(_FakeCtx("donna"), to=["alice@example.com"], subject="s", body="b")
    assert cap["msg"]["From"] == "donna@example.com"


async def test_no_from_parameter_exists(monkeypatch):
    # Passing from-ish kwargs must be a TypeError, not a silent override.
    tool, _ = _make_tool(monkeypatch)
    for spoof_kwarg in ("from_", "sender", "as_bot"):
        with pytest.raises(TypeError):
            await tool(
                _FakeCtx("claudette"),
                to=["alice@example.com"],
                subject="s",
                body="b",
                **{spoof_kwarg: "donna@example.com"},
            )


async def test_unauthenticated_context_is_refused(monkeypatch):
    tool, _ = _make_tool(monkeypatch)
    with pytest.raises(ToolError, match="no authenticated bot"):
        await tool(_FakeCtx(None), to=["alice@example.com"], subject="s", body="b")


# --- recipients / body / cc ---


async def test_recipients_and_cc_are_joined(monkeypatch):
    tool, cap = _make_tool(monkeypatch)
    result = await tool(
        _FakeCtx("claudette"),
        to=["a@example.com", "b@example.com"],
        subject="hi",
        body="text",
        cc=["c@example.com"],
    )
    msg = cap["msg"]
    assert msg["To"] == "a@example.com, b@example.com"
    assert msg["Cc"] == "c@example.com"
    assert "sent from claudette@example.com" in result


@pytest.mark.parametrize("bad_to", [[], ["  "], [""], None])
async def test_empty_recipient_list_is_rejected(monkeypatch, bad_to):
    tool, _ = _make_tool(monkeypatch)
    with pytest.raises(ToolError, match="'to' must contain at least one address"):
        await tool(_FakeCtx("claudette"), to=bad_to, subject="s", body="b")


# --- attachments ---


async def test_attachment_is_decoded_and_attached(monkeypatch):
    import base64

    tool, cap = _make_tool(monkeypatch)
    payload = b"hello,world\n"
    await tool(
        _FakeCtx("claudette"),
        to=["a@example.com"],
        subject="s",
        body="b",
        attachments=[
            {
                "filename": "data.csv",
                "content_b64": base64.b64encode(payload).decode(),
                "mimetype": "text/csv",
            }
        ],
    )
    parts = [p for p in cap["msg"].iter_attachments()]
    assert len(parts) == 1
    assert parts[0].get_filename() == "data.csv"
    assert parts[0].get_content_type() == "text/csv"
    assert parts[0].get_payload(decode=True) == payload


async def test_malformed_attachment_is_rejected(monkeypatch):
    tool, _ = _make_tool(monkeypatch)
    with pytest.raises(ToolError, match="attachment #0 is malformed"):
        await tool(
            _FakeCtx("claudette"),
            to=["a@example.com"],
            subject="s",
            body="b",
            attachments=[{"filename": "x"}],  # no content_b64
        )


# --- fail-loud transport error ---


async def test_send_failure_is_surfaced_not_swallowed(monkeypatch):
    async def boom(msg, config):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(email_tools, "send_message", boom)
    tool = email_tools.register(FastMCP("t"), Identity(ENV), SMTP)
    with pytest.raises(ToolError, match="email send failed via smtp-relay.brevo.com:587"):
        await tool(_FakeCtx("claudette"), to=["a@example.com"], subject="s", body="b")


# --- pure helpers ---


def test_build_message_sets_headers_and_body():
    msg = build_message(sender="claudette@example.com", to=["a@example.com"], subject="s", body="b")
    assert msg["From"] == "claudette@example.com"
    assert msg.get_content().strip() == "b"


def test_smtp_config_from_env_requires_all_vars():
    with pytest.raises(KeyError, match="BREVO_SMTP_HOST"):
        SmtpConfig.from_env({})


def test_smtp_config_from_env_reads_all():
    cfg = SmtpConfig.from_env(
        {
            "BREVO_SMTP_HOST": "h",
            "BREVO_SMTP_PORT": "587",
            "BREVO_SMTP_USER": "u",
            "BREVO_SMTP_KEY": "k",
        }
    )
    assert (cfg.host, cfg.port, cfg.user, cfg.key) == ("h", 587, "u", "k")


def test_attachment_from_b64_roundtrips():
    import base64

    att = Attachment.from_b64("f.bin", base64.b64encode(b"\x00\x01").decode(), "application/x")
    assert att.content == b"\x00\x01"
    assert att.mimetype == "application/x"
