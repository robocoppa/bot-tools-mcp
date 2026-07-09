"""The `send_email` tool.

The one thing that makes this trustworthy: **`from` is not a parameter.** The
sender is derived from the authenticated bot (resolved by the auth middleware,
read here via `current_bot`). A bot cannot ask to send as anyone else.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError

from bot_tools_mcp.email_smtp import (
    Attachment,
    SmtpConfig,
    build_message,
    send_message,
)
from bot_tools_mcp.identity import Identity
from bot_tools_mcp.server import current_bot


def register(mcp: FastMCP, identity: Identity, smtp: SmtpConfig | None = None):
    """Attach `send_email` to the app and return the tool coroutine.

    `smtp` is injectable for tests; in production it's read from the environment
    once at startup so a missing SMTP var fails at boot, not on first send. The
    returned function is the same one registered — handy for calling directly in
    unit tests with a fake Context.
    """
    smtp_config = smtp or SmtpConfig.from_env()

    async def send_email(
        ctx: Context,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        attachments: list[dict] | None = None,
    ) -> str:
        """Send an email as the calling bot.

        The From address is the bot's own `<bot>@<domain>` — it is NOT a
        parameter and cannot be overridden. `to`/`cc` are lists of addresses.
        Each attachment is `{"filename": str, "content_b64": str,
        "mimetype"?: str}`. Returns a short confirmation.
        """
        bot = current_bot(ctx)
        sender = identity.from_address(bot)

        recipients = _clean_addresses(to, "to")
        cc_list = _clean_addresses(cc, "cc") if cc else None
        atts = _decode_attachments(attachments)

        msg = build_message(
            sender=sender,
            to=recipients,
            subject=subject,
            body=body,
            cc=cc_list,
            attachments=atts,
        )
        try:
            await send_message(msg, smtp_config)
        except Exception as exc:  # fail loud, name the smarthost, don't swallow
            raise ToolError(
                f"email send failed via {smtp_config.host}:{smtp_config.port}: {exc}"
            ) from exc

        return f"sent from {sender} to {', '.join(recipients)}"

    mcp.tool(send_email)
    return send_email


def _clean_addresses(addrs: list[str] | None, field_name: str) -> list[str]:
    """Reject empty recipient lists and blank entries early."""
    cleaned = [a.strip() for a in (addrs or []) if a and a.strip()]
    if not cleaned:
        raise ToolError(f"{field_name!r} must contain at least one address")
    return cleaned


def _decode_attachments(attachments: list[dict] | None) -> list[Attachment]:
    """Turn wire-format attachment dicts into Attachment objects."""
    out: list[Attachment] = []
    for i, a in enumerate(attachments or []):
        try:
            out.append(
                Attachment.from_b64(
                    filename=a["filename"],
                    b64=a["content_b64"],
                    mimetype=a.get("mimetype"),
                )
            )
        except (KeyError, ValueError) as exc:
            raise ToolError(f"attachment #{i} is malformed: {exc}") from exc
    return out
