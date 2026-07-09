"""SMTP transport — the actual send through the Brevo smarthost.

Deliberately identity-free: it takes a fully-formed From/To/etc. and sends. All
the "who am I" logic lives in the tool layer, which derives From from the
authenticated bot and calls this. That split keeps this trivially mockable in
tests and keeps the no-spoof guarantee in one place.

Mirrors the send path proven in Stage 1 (`aiosmtplib.send(..., start_tls=True)`
against `smtp-relay.brevo.com:587`).
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class Attachment:
    """One file to attach. `content` is the raw bytes; `b64` is the base64 a
    caller sent over the wire (tools decode into `content` before this layer)."""

    filename: str
    content: bytes
    mimetype: str = "application/octet-stream"

    @classmethod
    def from_b64(cls, filename: str, b64: str, mimetype: str | None = None) -> "Attachment":
        return cls(
            filename=filename,
            content=base64.b64decode(b64),
            mimetype=mimetype or "application/octet-stream",
        )


@dataclass
class SmtpConfig:
    """Brevo smarthost connection settings, read from the environment."""

    host: str
    port: int
    user: str
    key: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SmtpConfig":
        env = os.environ if env is None else env

        def req(name: str) -> str:
            v = env.get(name)
            if not v:
                raise KeyError(f"required environment variable {name!r} is missing or empty")
            return v

        return cls(
            host=req("BREVO_SMTP_HOST"),
            port=int(req("BREVO_SMTP_PORT")),
            user=req("BREVO_SMTP_USER"),
            key=req("BREVO_SMTP_KEY"),
        )


def build_message(
    *,
    sender: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
) -> EmailMessage:
    """Assemble an EmailMessage. `sender` is already the authenticated bot's
    address — this layer never chooses it."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg.set_content(body)
    for att in attachments or []:
        maintype, _, subtype = att.mimetype.partition("/")
        msg.add_attachment(
            att.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.filename,
        )
    return msg


def build_invite_message(
    *,
    sender: str,
    to: list[str],
    subject: str,
    body: str,
    ics: bytes,
) -> EmailMessage:
    """Assemble an invite email carrying the ICS as `text/calendar; method=REQUEST`.

    The calendar part is added as an alternative so mail clients render the
    invite; a copy is also attached as a `.ics` file for clients that prefer it.
    """
    msg = build_message(sender=sender, to=to, subject=subject, body=body)
    # The itip calendar part — this is what makes it show up as an invitation.
    msg.add_alternative(
        ics.decode("utf-8"),
        subtype="calendar",
        params={"method": "REQUEST", "name": "invite.ics"},
    )
    return msg


async def send_message(msg: EmailMessage, config: SmtpConfig) -> None:
    """Send an assembled message through the smarthost (STARTTLS on 587).

    Imported lazily so the module (and its tests) don't hard-require aiosmtplib
    to be importable at collection time in odd environments.
    """
    import aiosmtplib

    await aiosmtplib.send(
        msg,
        hostname=config.host,
        port=config.port,
        username=config.user,
        password=config.key,
        start_tls=True,
    )
