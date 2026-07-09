# bot-tools-mcp

A small shared **MCP server** that gives a fleet of LAN bots real-world tools —
send email, manage a calendar, create and share documents and spreadsheets —
with **zero Google** and **per-bot identity**. One always-on service (your Unraid
box); each bot calls it over the LAN with its own bearer token, and the token
*is* the bot's identity.

It's a sibling service to the rest of the stack, not part of any one bot. The
bots stay thin; the tools, credentials, and identity model live here in one place.

## Why a shared server (and why per-bot tokens)

The alternative — baking SMTP creds, CalDAV logins, and Nextcloud passwords into
every bot on every laptop — spreads secrets everywhere and makes "who sent this?"
unanswerable. Instead:

- **One place holds the backend credentials.** Bots never see the Brevo SMTP key
  or the Nextcloud passwords; they hold only their own opaque token.
- **The token is the identity.** A request carries `Authorization: Bearer <token>`;
  the server resolves that to exactly one bot and derives everything from it — the
  `From` address it sends mail as, the calendar it writes to, the files it owns.
- **A bot can only ever act as itself.** There is deliberately **no** `from`,
  `user`, or `as` parameter on any tool. You cannot ask to send "as someone else,"
  because the sender isn't an input — it's the authenticated token.

So a leaked token exposes exactly one bot, and every action is attributable.

## Architecture

```
each laptop, per bot                       Unraid box (always on)
┌────────────────────────┐                ┌───────────────────────────────────┐
│ bot (Hermes/OpenClaw)  │  Bearer token  │ bot-tools-mcp  :9110/mcp          │
│  mcp_servers: [...]    │ ──────JSON────► │  • auth middleware: token → bot   │
│                        │  streamable-    │      (reject unknown token)       │
│                        │     HTTP        │  • tool dispatch, identity in ctx │
└────────────────────────┘                │        ┌──────┬─────────┬───────┐ │
                                          │        ▼      ▼         ▼       │ │
                                          │     email  calendar   docs/    │ │
                                          │    (Brevo)(Radicale) sheets    │ │
                                          │                    (Nextcloud) │ │
                                          └───────────────────────────────────┘
```

LAN-only — the bots are laptops on the same network, so they reach the server
directly at `http://192.168.1.11:9110/mcp`. No VPN, no public exposure.

## The backends

Each is a self-hosted, no-Google replacement, wired up in its own deploy stage:

| Capability | Backend | How the bot is scoped |
|---|---|---|
| Email | [Brevo](https://www.brevo.com/) free SMTP smarthost | `From` = `<bot>@<domain>`, derived from the token |
| Calendar | [Radicale](https://radicale.org/) (CalDAV) | per-bot login, `owner_only` — a bot sees only its own calendar |
| Docs / sheets | [Nextcloud](https://nextcloud.com/) + Collabora | one Nextcloud user per bot — a bot touches only its own files |

## The tools (v1 contract)

`from`/owner is never a parameter — it's the authenticated bot.

| Tool | Backend |
|---|---|
| `send_email` | Brevo |
| `send_calendar_invite`, `create_event`, `list_events`, `delete_event` | Radicale (+ Brevo for the invite email) |
| `sheet_create`, `sheet_read`, `sheet_write_cell`, `sheet_append_row` | Nextcloud + openpyxl |
| `doc_create`, `doc_read`, `doc_write`, `doc_append` | Nextcloud + python-docx |
| `create_share_link`, `list_files` | Nextcloud |

## Status

Early build. The **identity spine** (token → bot resolution, per-bot credential
derivation, the no-spoof guarantee) is done and tested; the FastMCP server and
the individual tools are being built on top of it, hermetically (mocked backends)
before anything touches the box.

## Local development

Fully testable on a laptop — no backends, no box:

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q          # hermetic suite (mocked backends)
uv run ruff check .
```

## Configuration

All secrets live in a single gitignored `.env` on the box (see the deploy stage
docs for the full contract). The shape, per bot:

```bash
MAIL_DOMAIN=example.com
BOT_TOKEN_<BOT>=<opaque token>                 # openssl rand -hex 32
RADICALE_PASS_<BOT>=<the bot's CalDAV password>
NEXTCLOUD_APP_PASSWORD_<BOT>=<the bot's Nextcloud app password>
# + Brevo SMTP creds, internal service URLs (Radicale/Nextcloud on ollama-net)
```

Backend I/O uses the **internal** service addresses (`http://nextcloud:80`,
`http://radicale:5232`); the only public URL that ever appears is the share link
handed back to a human.
