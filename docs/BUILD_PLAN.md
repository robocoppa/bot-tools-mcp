# BUILD_PLAN — bot-tools-mcp

_The execution roadmap for building this server tool-by-tool, hermetically, then
deploying it. Companion to [PROJECT_STATE.md](PROJECT_STATE.md) (current status)
and the plan-of-record in `audrey_ai_2.0/docs/plans/bot-tools/stage-4-mcp-server.md`._

Each step is: build the transport layer (identity-free, mockable) → build the
tool layer (reads the authed bot, no identity params) → write mocked-backend
tests → all green + ruff clean before moving on.

## The pattern every tool follows

1. **Transport module** (`<backend>_*.py`) — does the raw backend I/O, takes
   fully-formed inputs, holds no identity. Trivially mockable.
2. **Tool module** (`tools/<area>.py`) — `register(mcp, identity, ...)` attaches
   the tools; each reads `current_bot(ctx)`, derives per-bot creds via
   `Identity`, calls the transport. **No `from`/`user`/`path-owner` parameter.**
3. **Tests** — mock the transport; assert (a) the action is scoped to the authed
   bot, (b) a bot can't act as another, (c) inputs validated, (d) backend errors
   surface loud.
4. Register the module in `server.py :: _register_tools`.

## Steps

### ✅ 0. Scaffold + identity spine + server + auth
Done. `identity.py`, `server.py` (`BotAuthMiddleware` on `on_call_tool`,
`/health`, `current_bot`). 43 tests.

### ✅ 1. Email — `send_email`
Done. `email_smtp.py` (Brevo STARTTLS send, mirrors Stage 1) + `email_tools.py`.
From derived from the bot; attachments base64; fail-loud.

### ✅ 2. Calendar — `create_event`, `list_events`, `delete_event`, `send_calendar_invite`
Done. `caldav_client.py` (UUID discovery, sync-in-thread, REQUEST invite ICS) +
`calendar_tools.py`. Per-bot auth, opaque `event_id`, invite saves + emails.
Backend: Radicale CalDAV (Stage 2), **per-bot creds** (`RADICALE_PASS_<BOT>`,
username = bot name, `owner_only`).

- Transport `caldav_client.py`: connect as a given bot, **discover** the bot's
  one calendar via `principal().calendars()` — the collection path is a **UUID**,
  not a name (Stage 2 web-UI assigned it), so never hardcode a path.
- `create_event` — build a VEVENT (`icalendar`), `save_event` to the discovered
  calendar. Return an **opaque `event_id`** (the event's UID/href).
- `list_events` — optional `start`/`end` window; return events each with the
  same opaque `event_id`.
- `delete_event` — take that `event_id` back; resolve + delete. Don't ask the
  bot to construct a path.
- `send_calendar_invite` — VEVENT with attendees + `method=REQUEST`, save to the
  calendar, then reuse the email path to mail the `.ics` as
  `text/calendar; method=REQUEST`.
- Tests: mock `caldav`; assert per-bot auth (`RADICALE_PASS_<BOT>`), calendar is
  discovered not hardcoded, VEVENT has attendees + REQUEST, `.ics` also emailed,
  `event_id` round-trips create→delete.

### ✅ 3. Docs / sheets — `doc_*`, `sheet_*`, `create_share_link`, `list_files`
Done. `nextcloud_client.py` (WebDAV + OCS, `safe_path` guard, internal-URL I/O)
+ `docs.py` (in-memory openpyxl/python-docx round-trips). Path traversal rejected,
per-bot isolation, share link returns public URL only.

_Original detail:_
Backend: Nextcloud WebDAV + OCS (Stage 3), **per-bot users**
(`NEXTCLOUD_APP_PASSWORD_<BOT>`), each bot owns only `/dav/files/<bot>/…`.

- Transport `nextcloud_client.py`: WebDAV `GET`/`PUT`/`PROPFIND` and the OCS
  share `POST`, Basic-auth'd as the bot, against the **internal** URL
  (`http://nextcloud:80`).
- **Path guard** (shared helper): reject absolute paths and any `..` segment
  before building a URL — defense in depth over the per-bot credential.
- `sheet_create/read/write_cell/append_row` — WebDAV round-trip + `openpyxl`.
- `doc_create/read/write/append` — WebDAV round-trip + `python-docx`.
- `create_share_link(path, permission=edit|view, expiry?, password?)` — OCS
  `POST …/shares`, `shareType=3`. Returns the **public** `…/s/<token>` URL (the
  only place the public host appears). Nextcloud **normalizes** `permissions`
  (requested 15 → returned 19); assert on `can_edit`, not an exact int.
- `list_files(path?)` — WebDAV `PROPFIND` under the bot's root.
- Tests: mock `httpx`; assert per-bot auth + path, path-traversal rejected,
  openpyxl round-trips a cell, no tool composes a URL against the **public** host
  for a backend call.

### ✅ 4. Packaging — Dockerfile + `.env.example` + compose
Done. `Dockerfile` (slim, `/health` urllib healthcheck, no curl), `compose.yaml`
(ollama-net, publishes 9110), `.env.example` (full per-bot contract),
`[project.scripts] bot-tools-mcp`, `run()` honors `MCP_HOST`/`MCP_PORT`.

_Original detail:_
- `Dockerfile`: slim Python, `uv`-installed, runs `bot-tools-mcp` entry
  (add `[project.scripts]`), exposes `9110`. No `curl` in the image — the
  healthcheck uses `python -c urllib…` against `/health`.
- `.env.example`: the full var contract (Brevo, per-bot Radicale/Nextcloud,
  per-bot tokens), placeholders only. Real `.env` stays on the box.

### ⬜ 5. Deploy + live verify (box)
Folds into `audrey_ai_2.0/docs/plans/bot-tools/` compose. On the box:
- `docker compose up -d --build bot-tools-mcp`; confirm healthy at `:9110`.
- Bad token rejected; valid token lists + calls tools.
- Live `send_email` as `claudette` → inbox From `claudette@builtryte.xyz`.
- `send_calendar_invite` → Radicale event + `.ics` email.
- `create_share_link` → working `cloud.builtryte.xyz/s/…`.
- Record as-built in the stage-4 deploy log.

### ⬜ 6. Wire the bots (Stage 5, other repo)
Each bot's runtime gets an `mcp_servers:` entry pointing at
`http://192.168.1.11:9110/mcp` with its own `BOT_TOKEN`. See
`stage-5-wire-bots.md`.

## Definition of done (whole server)

- [ ] Hermetic suite green (incl. the no-spoof + path-traversal tests).
- [ ] Container healthy + LAN-reachable at `:9110/mcp`.
- [ ] Each tool proven live against its real backend, scoped per-bot.
- [ ] At least one bot wired and calling a tool end-to-end.
