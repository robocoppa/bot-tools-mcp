# PROJECT_STATE — bot-tools-mcp

_Single continuity file for this repo. Read this first when resuming. Update the
**Status** block whenever a piece ships or a decision is made. Newest status
entry on top._

This is the **MCP server** half of the larger `bot-tools` workstream. The backend
deploy stages (Brevo email, Radicale calendar, Nextcloud + Collabora docs) and
all build/deploy plans live in this repo under `docs/plans/` (gitignored,
laptop-local). Stages 0–3 are **done and verified**; Stage 4 (this server) is
**done and live on the box**; Stage 5 (wiring the bots) is **DONE — all three bots
(claudette, donna, brigitte) have all capabilities verified from real chat**.

> **Continuity note — keep audrey's PROJECT_STATE light on this.**
> `audrey_ai_2.0/docs/PROJECT_STATE.md` should carry only a **brief, general
> pointer** to the bot-tools project's state (e.g. "Stage 4 MCP server underway
> in the `bot-tools-mcp` repo — see that repo's docs"), not a detailed status.
> **This file is the authoritative, targeted continuity doc for Stage 4** — all
> the detail lives here. When updating audrey's state, just refresh the one-line
> pointer; don't duplicate the specifics.

---

## ▶ Status

### 2026-07-14 — ✅ STAGE 5 DONE — all three bots have all capabilities, verified from real chat

**The workstream's finish line.** All three bots — **claudette** (Hermes/GLM), **donna**
(Hermes/Codex OAuth), **brigitte** (OpenClaw/Codex OAuth) — now drive the **full bot-tools set**
(docs, sheets, email, calendar invite, delete) **from real chat messages**. Two runtimes (Hermes +
OpenClaw), three model backends, one shared MCP server on the box, per-bot bearer-token identity.

Stage 5.4 complete. bot-tools MCP workstream (Stages 0–5) is **done and live in production** across
the fleet. Setup gotchas captured for future bots: Hermes reconnect after tool changes (use
`/reload-mcp`), OpenClaw strict-JSON + literal token, and the macOS Codex app-server LAN-sandbox fix
(§5.2a). Onboarding a new bot is now the §5.5 recipe: mint a token, add the MCP block on its host,
done.

**Token hardening — DONE (2026-07-14):** no literal bearer tokens left in any bot's config. Each
host keeps `BOT_TOKEN_<NAME>` in its env file (`~/.hermes/.env` / `~/.openclaw/.env`) and the
config references `${BOT_TOKEN_<NAME>}` — Hermes `mcp_servers.headers` and OpenClaw
`mcp.servers.headers` both expand it (OpenClaw needs v2026.4.24+; verified working on all three
after restart + a live tool action). SecretRef objects do NOT work for MCP headers — only `${VAR}`.
Pattern is baked into the Stage 5 deploy doc (§ intro + §5.1/§5.2) for future bots.

**Remaining follow-up (not a blocker):** per-bot From-identity spot check across the fleet if not
already implicitly confirmed by each bot's successful sends.

### 2026-07-14 — brigitte (OpenClaw + Codex) verified end-to-end + macOS LAN-sandbox gotcha solved

Third bot live. **brigitte** (OpenClaw on a Mac mini, ChatGPT-OAuth **Codex** `gpt-5.5`) now
drives bot-tools **from a real chat message** — doc + sheet + email + calendar invite all
succeeded. Fleet is now: **claudette** (Hermes/GLM), **donna** (Hermes/Codex OAuth), **brigitte**
(OpenClaw/Codex OAuth).

- **The blocker, and the real fix.** brigitte's tools looked wired (`openclaw mcp probe` → 16
  tools, `doctor` → ok) but her Codex session couldn't see them. Root cause was NOT tool
  projection — it was **network**: OpenClaw runs Codex via the app-server harness, which on macOS
  runs under the **seatbelt sandbox with networking disabled**, so it got `EHOSTUNREACH` reaching
  the LAN server `192.168.1.11:9110` while the shell reached it fine (curl 406). Fix:
  `plugins.entries.codex.config.appServer.sandbox = "danger-full-access"` in `openclaw.json`, then
  a **full stop → kill lingering `codex` proc → start** + a fresh chat thread. Documented as
  **Stage 5 §5.2a** (the gotcha + the exact diagnose-via-`codex-home/logs_2.sqlite` recipe).
- **Lesson recorded:** `mcp probe`/`doctor` only prove the OpenClaw layer; when a **Codex** session
  can't see MCP tools, read the Codex app-server's own log first — the connection error is there.
- OpenClaw config specifics also captured in §5.2: it's strict JSON (not JSON5), `mcp.servers` is a
  top-level key, use the **literal** token (no `${VAR}` expansion), `transport: streamable-http`.

**Stage 5.4 status:** brigitte = docs/sheets **+ email + calendar** all verified from chat.
claudette = docs/sheets + delete verified; email/calendar still pending. donna (Hermes/Codex) wired,
tools working, 5.4 checks pending. Remaining: claudette + donna email/calendar confirmation, and the
per-bot From-identity check across all three (no cross-bot spoofing).

### 2026-07-13 — STAGE 5 UNDERWAY — Claudette wired + docs/delete verified from real Telegram

First bot (Claudette) is wired to the live MCP server and driving tools **from real
Telegram messages**, not just container smoke tests.

- **Claudette wired.** `mcp_servers.bot-tools` added to `~/.hermes/config.yaml` on
  claudettelaptop → `http://192.168.1.11:9110/mcp` with `BOT_TOKEN_CLAUDETTE`. The
  server's tools joined Hermes's bundle. Hermes now runs
  `audrey_passthrough/glm-5.2:cloud` via Audrey (the earlier virtual-model attempts
  broke Hermes; only `audrey_passthrough/*` works).
- **Docs/sheets verified from Telegram** — create + share round-trip end-to-end from a
  real chat message (checkbox 3 of the 5.4 plan).
- **NEW TOOL: `delete_file`.** Bots could create/share Nextcloud files but not remove
  them, so every test/scrapped request left orphans (hit this live — Claudette had to
  ask the user to delete test files by hand). Added `nextcloud_client.delete_file`
  (WebDAV DELETE, `safe_path`-guarded, moves to the bot's **own trash** so it's
  recoverable) + the `delete_file` tool (per-bot scoped, fails loud on a missing path).
  **90 tests green.** Deployed (git pull + `docker compose up -d --build`), and
  **verified working from Telegram** after `hermes gateway restart` (the client caches
  the tool list at handshake — a server rebuild alone isn't enough; the bot must
  reconnect). Tool count is now **16**.

**Remaining Stage 5.4 (from real chat messages):** email (inbox, right From, dkim=pass)
and calendar invite (`.ics` + shows in the subscribed CalDAV client) driven from
Telegram; confirm per-bot From identity holds. Then onboard the other bots
(`brigitte`, `donna`) — add their `mcp_servers:` block with their own token.

### 2026-07-10 — docs/ reorganized (flatter plans/, added docs index)

Tidied the docs tree — no content lost, tracked-vs-gitignored boundary unchanged:
- **Flattened `plans/`.** Dropped the redundant `plans/bot-tools/` nesting; the
  stage docs now live directly under `docs/plans/`. The master plan is
  `docs/plans/MASTER_PLAN.md` (was `bot-workspace-tools-plan.md`), and the
  stage-3 lessons doc is now `stage-3-appendix-lessons-learned.md` so it reads as
  the appendix it is, not a peer stage.
- **Added `docs/README.md`** — a tracked index of every doc and the
  tracked (`docs/*.md`) vs gitignored (`docs/plans/**`) split.
- All cross-references updated. **No code change; Stage 4 status below unchanged.**

### 2026-07-10 — All bot-tools plan docs consolidated into THIS repo

The 8 stage docs + master plan moved here from `audrey_ai_2.0` into
`docs/plans/` (gitignored, laptop-local — same privacy as before; they hold the
domain/LAN-IP/bot-names). So this repo is now the single home for everything
bot-tools: tracked continuity docs (`docs/*.md`) + gitignored plans
(`docs/plans/`). Cross-refs fixed; audrey's `docs/plans/` is now purely audrey.
Open Cursor at `~/Documents/github` to see both repos side-by-side. **No code
change; Stage 4 status below is unchanged.**

### 2026-07-10 — STAGE 4 DONE ✅ — all 6 smoke tests pass on the box

The MCP server is live on the box and **every tool is verified end-to-end** with
real backends. Full smoke suite passed:

1. ✅ Health — server up at `:9110`.
2. ✅ Auth — discovery open (15 tools), bad token rejected.
3. ✅ Email — `send_email` landed inbox, From `claudette@builtryte.xyz`, DKIM pass.
4. ✅ Calendar — `create_event`/`list_events`/`delete_event` round-trip;
   `send_calendar_invite` saved to Radicale AND emailed a `.ics` invitation.
5. ✅ Docs/sheets — `.xlsx` + `.docx` round-trip (openpyxl/python-docx);
   `create_share_link` returned a `cloud.builtryte.xyz/s/…` link that **opens
   editable in Collabora** (verified in incognito); `list_files` works.
6. ✅ Per-bot isolation — a bot cannot read another bot's file.

Deployed as `bot-tools-mcp` on `ollama-net`, LAN at `192.168.1.11:9110/mcp`,
per-bot tokens + creds from `mcp/.env`. Drove the tests from **inside the
container** (its own token → no mismatch). Two production bugs found+fixed during
bring-up (auth header stripping; async `Context.get_state`) — see entries below.

**Stage 4 complete. Next: Stage 5 — wire the bots** (each bot's `mcp_servers:`
config → `http://192.168.1.11:9110/mcp` with its own `BOT_TOKEN`), in the
[plans/stage-5-wire-bots.md](plans/stage-5-wire-bots.md) plan.

_Earlier the same day:_

### 2026-07-10 — LIVE ON THE BOX: send_email verified end-to-end ✅

`send_email` works on the box through the real tool path — mail sent through
Brevo, From `claudette@builtryte.xyz`, landed in the inbox. Smoke test **steps
1–3 pass** (health, auth gate, real email). This validated the full
auth → identity → backend chain after fixing two real deploy bugs (below).

**Two production bugs found + fixed during first deploy** (both invisible to the
mocked unit tests — now guarded):
1. **Auth header stripped** — `get_http_headers()` drops `authorization` by
   default; the bearer never reached the gate → every call "unknown or missing
   bot token". Fix: `get_http_headers(include_all=True)`.
2. **Async context misuse** — `Context.get_state`/`set_state` are async in this
   FastMCP; calling them sync made `current_bot` return a *coroutine*, which
   became the email From → Brevo `501`. Fix: `await` them; `current_bot`/
   `bot_creds` are now async (7 call sites updated). Test doubles made async so
   this can't regress.

Also: `.env` `$` in Nextcloud app passwords must be escaped `$$` (Compose
substitution) — done on the box.

**Next:** smoke steps 4 (calendar) + 5 (docs/sheets, exercises the Nextcloud
password) + 6 (per-bot isolation). Then Stage 5 (wire the bots).

_Earlier:_

### 2026-07-10 — First box deploy: fixed a real auth bug (header stripping)

Deployed to the box; the very first authenticated call failed with "unknown or
missing bot token" **even using the container's own loaded token over localhost**
— which ruled out the token value, the network, and stale env, and pointed at the
server. Instrumented the live middleware and found: **`get_http_headers()` strips
`authorization` by default**, so the bearer never reached the auth gate — every
call was rejected. Fix: `get_http_headers(include_all=True)` in
`_bearer_from_headers`. The unit tests missed it because they mocked
`get_http_headers` to return the header regardless of args; added a **regression
test** asserting `include_all=True` is passed. Verified live: header now arrives,
token resolves, bot stashed. **83 tests green, ruff clean.**

Also seen box-side: a Compose WARN `The "ZCzDKDf7E" variable is not set` on
`up`, meaning a literal `$` somewhere in `.env` triggers Compose variable-
substitution and blanks that fragment. (NOT the same as the trailing-`$` cat -A
display artifact — this is Compose parsing the file.) To confirm it's actually
truncating a secret: compare `grep KEY .env | wc -c` vs `docker exec … printenv
KEY | wc -c`; if shorter, escape `$$` or regenerate. Documented in the deploy-doc
troubleshooting table.

**Next:** ship this fix to the box (rebuild + force-recreate), fix the `$` in the
Nextcloud passwords, then re-run smoke tests from step 3 (real `send_email`).

_Earlier:_

### 2026-07-09 — Full Stage 4 built: all 15 tools, packaged, 82 tests green

The whole v1 tool contract is implemented and hermetically tested. **Not yet
deployed to the box** — next action is the live smoke test (see
[DEPLOY_AND_SMOKE_TEST.md](DEPLOY_AND_SMOKE_TEST.md)).

- **All 15 tools built + registered** (`server.list_tools()` returns 15):
  `send_email`; `create_event`/`list_events`/`delete_event`/
  `send_calendar_invite`; `sheet_create`/`read`/`write_cell`/`append_row`;
  `doc_create`/`read`/`write`/`append`; `create_share_link`; `list_files`.
- **Transports** (identity-free, mockable): `email_smtp.py` (Brevo STARTTLS),
  `caldav_client.py` (Radicale, UUID-calendar discovery, sync-in-thread),
  `nextcloud_client.py` (WebDAV + OCS, `safe_path` traversal guard).
- **Every tool derives identity from the token** — per-bot Radicale/Nextcloud
  creds, per-bot WebDAV root, From = the bot. No spoof params anywhere.
- **Packaging:** `Dockerfile` (slim, `/health` urllib healthcheck, no curl),
  `compose.yaml` (ollama-net, publishes 9110), `.env.example`,
  `[project.scripts] bot-tools-mcp`. `run()` honors `MCP_HOST`/`MCP_PORT`.
- **Tests: 82 green, ruff clean.** Includes the no-spoof tests, path-traversal
  rejection, per-bot isolation, and "no backend call uses the public URL."
- **Verified over the wire** (live server + real FastMCP `StreamableHttpTransport`
  client): discovery open without a token, a bad token calling a tool is rejected,
  a good token passes auth and the tool executes. The smoke-test doc's client
  script (transport-level `headers=`) is confirmed against a running server.

Docs: [DEPLOY_AND_SMOKE_TEST.md](DEPLOY_AND_SMOKE_TEST.md) — box deploy +
layered live smoke tests (health → auth → each tool) + troubleshooting.

**Next:** deploy to the box, run the smoke tests, then wire the bots (Stage 5).

_Earlier the same day:_

### 2026-07-09 — Auth spine + first tool built (email), all hermetic

- **Repo scaffolded** (standalone, sibling to `audrey_ai_2.0`/`fleet-watchdog`):
  `src/bot_tools_mcp/` package layout, `uv` + hatchling, ruff line-length 100.
- **Identity spine** (`identity.py`) — token→bot resolution, per-bot credential
  derivation (`from_address`, `radicale_password`, `nextcloud_password`), the
  no-spoof guarantee. Rejects unknown/empty/collision tokens, fails loud on
  missing env.
- **Server + auth** (`server.py`) — FastMCP app; `BotAuthMiddleware` gates every
  **tool call** on a valid bearer (`on_call_tool`, NOT `on_request`), so
  discovery (`initialize`/`tools/list`) flows freely while every action needs a
  token. Unauthenticated `/health` route for the healthcheck. `current_bot(ctx)`
  reads the authed bot; raises if absent.
- **First tool** (`tools/email_tools.py` + `email_smtp.py`) — `send_email`.
  From is derived from the authed bot; **no `from` parameter exists**.
  Attachments via base64, fail-loud on transport error. Transport layer is
  identity-free and mockable.
- **Tests: 43 green, ruff clean.** Full server boots with the tool registered;
  `tools/list` returns `['send_email']`.

**Key decision — FastMCP version.** The plan doc said "v2"; `fastmcp>=2.0`
actually resolves to **3.4.4**. Built + verified against the real 3.4.4 API
(`Middleware.on_call_tool`, `get_http_headers`, `Context.set/get_state`,
`run(transport="http")`, `AuthorizationError`). Pinned `fastmcp>=3.4` honestly.

**Next:** the calendar tools (`create_event`/`list_events`/`delete_event`/
`send_calendar_invite`) — see [BUILD_PLAN.md](BUILD_PLAN.md). Then docs/sheets,
then compose + box deploy + live verify.

---

## Where things live

| Piece | Path | State |
|---|---|---|
| Identity spine | `src/bot_tools_mcp/identity.py` | ✅ done, tested |
| Server + auth middleware | `src/bot_tools_mcp/server.py` | ✅ done, tested |
| Email transport + tool | `email_smtp.py`, `tools/email_tools.py` | ✅ done, tested |
| Calendar transport + tools | `caldav_client.py`, `tools/calendar_tools.py` | ✅ done, tested |
| Docs/sheets transport + tools (incl. `delete_file`) | `nextcloud_client.py`, `tools/docs.py` | ✅ done, tested |
| Dockerfile + compose + `.env.example` | repo root | ✅ done |
| Box deploy + live smoke test | on Unraid | ✅ done, verified |
| Wire the bots (Stage 5) | bots' `mcp_servers:` config | 🔶 Claudette wired + docs/delete verified from Telegram; email/calendar + other bots remain |

Backend + build plans (now in this repo, gitignored): `docs/plans/`
— `stage-{0,1,2,3}-*.md` (backend deploys, done), `stage-4-mcp-server.md`
(this server's plan of record), `stage-5-wire-bots.md` (bots' `mcp_servers:`
config). Master plan: `docs/plans/MASTER_PLAN.md`.

## Non-negotiables (carried from the backend stages)

- **The token IS the identity.** No `from`/`user`/`as` parameter on any tool,
  ever. From/username/path segment are all derived from the authed bot.
- **Per-bot everything.** Each bot has its own token, Radicale password, and
  Nextcloud app password. No shared accounts. Bots: `brigitte`, `claudette`,
  `donna`.
- **Internal URLs for backend I/O; public URL only in returned share links.**
  A server-side call to the public Nextcloud URL hairpins on the host-mode
  tunnel and fails (the whole Stage-3 saga). `http://nextcloud:80`,
  `http://radicale:5232` for I/O.
- **Fail loud.** Name the failing host/URL on any backend error; never swallow
  into a bare 500. (Stage-3's worst time-sink was a silent hairpin.)
- **Hermetic-first.** Every tool has mocked-backend tests that pass on the
  laptop before anything touches the box.

## How to run / test

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q          # hermetic suite
uv run ruff check .
```

## Deploy target (box)

- Runs at `/mnt/user/appdata/bot-tools/mcp/` on Unraid, on `ollama-net`,
  LAN-only at `http://192.168.1.11:9110/mcp` (streamable-HTTP).
- **Port 9110** (not 9100 — that's node_exporter's canonical port; 9110 clears
  the 9090/9099/9100 monitoring cluster).
- Secrets from the box's `/mnt/user/appdata/bot-tools/.env` (per-bot tokens +
  backend creds). Never committed — see `.env.example` (to be added).
