# Deploy & Smoke Test — bot-tools-mcp

_How to deploy the MCP server to the Unraid box and verify every tool works
end-to-end against the live backends. Run the smoke tests in order — each layer
builds on the one before, so the first failure tells you where to look._

Companion to [PROJECT_STATE.md](PROJECT_STATE.md) and [BUILD_PLAN.md](BUILD_PLAN.md).

---

## Prerequisites (must be true before deploying)

- **Backends live on `ollama-net`:** `radicale:5232` and `nextcloud:80` reachable
  by container DNS (Stages 2 & 3 — done). Collabora need not be up for the MCP
  server itself, only for humans opening docs.
- **Per-bot accounts exist:** Radicale users + Nextcloud users `brigitte`,
  `claudette`, `donna`, each with its own password / app password.
- **Port 9110 is free** on the box (`docker ps | grep 9110` → nothing).
- **`.env` filled in** at `/mnt/user/appdata/bot-tools/.env` — every value from
  `.env.example`, with real per-bot tokens (`openssl rand -hex 32`).

---

## Deploy

The repo deploys to `/mnt/user/appdata/bot-tools/` on the box (alongside the
shared `.env`).

```bash
# 1. Get the code onto the box (clone once, then git pull to update)
cd /mnt/user/appdata/bot-tools
git clone https://github.com/robocoppa/bot-tools-mcp.git mcp   # first time
#   (or: cd mcp && git pull)

# 2. Point compose at the shared .env one level up, or copy the example in:
cd /mnt/user/appdata/bot-tools/mcp
cp .env.example .env        # then fill it in — OR symlink the shared one:
#   ln -s /mnt/user/appdata/bot-tools/.env .env

# 3. Build and start
docker compose up -d --build

# 4. Watch it come up
docker compose logs -f bot-tools-mcp
```

Expect the FastMCP banner and a line showing it listening on `0.0.0.0:9110`.
`Ctrl-C` out of the logs — the container keeps running.

> If you edit `.env` later, `docker compose up -d --force-recreate bot-tools-mcp`
> to pick it up (a plain restart can hold a stale bind-mounted file).

---

## Smoke tests

Run these from your **laptop** (it reaches the box over the LAN). Load the env
so `$BOT_TOKEN_*` are available:

```bash
set -a; . /mnt/user/appdata/bot-tools/.env; set +a    # on the box
# from the laptop, export the one token you're testing with instead:
export BOT_TOKEN_CLAUDETTE='<the claudette token>'
```

`BASE=http://192.168.1.11:9110` throughout.

### 1. Liveness — the server is up

```bash
curl -sS http://192.168.1.11:9110/health          # → ok
```

❌ If this fails: the container isn't up or 9110 isn't published.
`docker compose ps` and `docker compose logs bot-tools-mcp`.

### 2. Auth — bad tokens are rejected, discovery is open

Tool discovery (`tools/list`) is intentionally open; tool *calls* require a
valid token. First, a bad token must NOT be able to call a tool. The cleanest
check is with an MCP client, but you can prove auth with raw JSON-RPC:

```bash
# initialize + list tools with NO token — should succeed (discovery is open)
# and show 15 tools. Use an MCP client (below) — raw curl needs the session
# handshake, which is fiddly.
```

The reliable way is a tiny MCP client script (run on the laptop, where Python +
the fastmcp client are available):

```bash
# save as smoke_client.py
cat > smoke_client.py <<'PY'
import asyncio, json, os, sys
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BASE = "http://192.168.1.11:9110/mcp"

async def main():
    token = os.environ.get("TOKEN", "")
    # Auth headers go on the TRANSPORT, not the Client.
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = StreamableHttpTransport(BASE, headers=headers)
    async with Client(transport) as c:
        if len(sys.argv) > 1:                          # call a tool
            name = sys.argv[1]
            args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
            print(await c.call_tool(name, args))
        else:                                          # just list tools
            tools = await c.list_tools()
            print("tools:", sorted(t.name for t in tools))

asyncio.run(main())
PY

# a) discovery with no token → 15 tool names
uv run --with fastmcp python smoke_client.py

# b) a tool call with a BAD token → AuthorizationError
TOKEN=WRONG uv run --with fastmcp python smoke_client.py \
  send_email '{"to":["you@yourdomain"],"subject":"x","body":"x"}'
#   → should raise "unknown or missing bot token", NOT send
```

✅ (a) lists 15 tools. ✅ (b) errors with an auth message. If a bad token sends
mail, stop — the gate is broken.

### 3. Email — `send_email` lands in the inbox, From the right bot

```bash
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  send_email '{"to":["<a mailbox you own>"],"subject":"bot-tools smoke","body":"hi from claudette"}'
```

✅ Arrives **in the inbox** (not spam), **From `claudette@<your domain>`**, DKIM
pass. This closes the loop with Stage 1 through the real tool path.

### 4. Calendar — event create / list / delete + invite

```bash
# create → prints an event_id
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  create_event '{"title":"Smoke test","start":"2026-07-15T15:00:00","end":"2026-07-15T15:30:00"}'

# list → should include it, with the same event_id
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py list_events '{}'

# delete → pass the event_id back
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  delete_event '{"event_id":"<the id from create>"}'

# invite → saves to the calendar AND emails a .ics (method=REQUEST)
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  send_calendar_invite '{"to":["<a mailbox you own>"],"title":"Smoke invite","start":"2026-07-16T10:00:00","end":"2026-07-16T10:30:00"}'
```

✅ `create` returns an id, `list` shows it, `delete` removes it (a second `list`
is empty). ✅ The invite email arrives as an **invitation** (calendar shows an
accept/decline), From `claudette@…`.

### 5. Docs / sheets — round-trip + a working share link

```bash
# a spreadsheet: create, write a cell, read it back
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  sheet_create '{"path":"smoke.xlsx","sheets":["Data"]}'
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  sheet_write_cell '{"path":"smoke.xlsx","sheet":"Data","cell":"A1","value":"hello"}'
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  sheet_read '{"path":"smoke.xlsx","sheet":"Data"}'      # → [["hello"]]

# a document
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  doc_create '{"path":"smoke.docx","content":"first line"}'
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  doc_read '{"path":"smoke.docx"}'                        # → "first line"

# list the bot's files
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py list_files '{}'

# a public, editable share link
TOKEN="$BOT_TOKEN_CLAUDETTE" uv run --with fastmcp python smoke_client.py \
  create_share_link '{"path":"smoke.xlsx","permission":"edit"}'
#   → https://cloud.<domain>/s/TOKEN
```

✅ The sheet round-trips (`[["hello"]]`), the doc round-trips (`"first line"`),
`list_files` shows both. ✅ Opening the `/s/…` link in an incognito window opens
the file in Collabora and lets you edit — the same round-trip proven in Stage 3,
now driven by the tool.

### 6. Per-bot isolation (optional but reassuring)

```bash
# claudette's file must NOT be readable as donna
TOKEN="$BOT_TOKEN_DONNA" uv run --with fastmcp python smoke_client.py \
  doc_read '{"path":"smoke.docx"}'
#   → "file not found" (donna has her own root; she can't see claudette's file)
```

✅ Errors with "file not found" — each bot only sees its own files.

### Cleanup

```bash
# remove the smoke files as claudette (or just leave them)
# (there's no delete_file tool in v1; delete via the Nextcloud web UI if wanted)
```

---

## Done when

- [ ] `/health` → `ok`.
- [ ] Discovery lists 15 tools; a bad token cannot call one.
- [ ] `send_email` lands inbox From the right bot.
- [ ] Calendar create/list/delete round-trips; invite emails a REQUEST `.ics`.
- [ ] Sheet + doc round-trip; `create_share_link` gives a working editable link.
- [ ] A bot can't read another bot's file.

Record the run (date, what passed, any surprises) in
[PROJECT_STATE.md](PROJECT_STATE.md)'s status block and the stage-4 deploy log
in `audrey_ai_2.0/docs/plans/bot-tools/`.

---

## Troubleshooting (keyed to known traps)

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` unreachable | container down, or 9110 not published | `docker compose ps`; check `ports:` in compose |
| every tool call → auth error even with a good token | token in `.env` doesn't match what the bot sends, or `.env` not loaded into the container | `docker compose exec bot-tools-mcp env \| grep BOT_TOKEN`; `--force-recreate` after `.env` edits |
| `send_email` fails, names the smarthost | Brevo creds wrong / SMTP key rotated | re-check `BREVO_SMTP_*` in `.env` |
| email lands in **spam** | DKIM/SPF/DMARC drift | re-verify the Stage-1 DNS records |
| calendar op → "has no calendar" | the bot's Radicale calendar wasn't created, or wrong per-bot password | create it in the Radicale web UI (Stage 2); check `RADICALE_PASS_<BOT>` |
| docs op → connection/TLS error naming `cloud.<domain>` | a backend call hit the **public** URL (hairpin) | `NEXTCLOUD_URL` must be the **internal** `http://nextcloud:80` |
| `create_share_link` → OCS rejected | Nextcloud sharing disabled, or file owned by a different bot | share the file as its owner; enable link shares in Nextcloud |
| share link opens but won't edit | Collabora/WOPI issue, not the MCP server | see the Stage-3 lessons-learned doc |

**Reading logs:** `docker compose logs -f bot-tools-mcp`. Every backend error is
logged with the failing host/URL named (fail-loud by design) — the log tells you
which backend and which URL, so a hairpin or a wrong credential is obvious.
