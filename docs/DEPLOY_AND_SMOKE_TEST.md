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

> **⚠️ Escape `$` in `.env` values.** Docker Compose runs variable substitution
> on `env_file`, so any literal `$` in a secret (common in Nextcloud app
> passwords) gets expanded and **blanked** — you'll see
> `WARN … variable is not set` on `up`, and the container receives a truncated
> password. **Double every `$` to `$$`** in `.env` (Compose collapses `$$` → one
> literal `$`). Verify the container got the full value:
> `docker exec bot-tools-mcp printenv NEXTCLOUD_APP_PASSWORD_<BOT>`. Alternatively,
> regenerate app passwords without a `$` — they're disposable.

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

Run these **on the box**, driving the server from **inside its own container**.
The container already has Python + the fastmcp client, and — crucially — it holds
each bot's token in its own env (`$BOT_TOKEN_<BOT>`). Using the container's own
token means the token the client sends is *guaranteed* to be the exact one the
server checks, so you never chase a "laptop token doesn't match the container"
ghost.

### One-time setup: the client + a helper

Write the tiny MCP client into the container, then define a `sc` shell helper so
every command below is short. (Both are disposable — the `/tmp` file clears when
the container is recreated; re-run this block after any rebuild.)

```bash
# 1. the client, inside the container
docker exec -i bot-tools-mcp sh -c 'cat > /tmp/sc.py' <<'PY'
import asyncio, json, os, sys
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
async def main():
    token = os.environ.get("TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with Client(StreamableHttpTransport("http://localhost:9110/mcp", headers=headers)) as c:
        if len(sys.argv) > 1:
            r = await c.call_tool(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
            print(r.data)          # just the tool's return value, not the whole result object
        else:
            print("tools:", sorted(t.name for t in await c.list_tools()))
asyncio.run(main())
PY

# 2. a helper: `sc <bot> <tool> '<json-args>'` — runs as that bot's own token.
#    `sc "" <tool>` runs with NO token (for the discovery check).
sc() {
  local bot="$1"; shift
  local var="BOT_TOKEN_$(echo "$bot" | tr a-z A-Z)"
  docker exec bot-tools-mcp sh -c \
    "TOKEN=\"\${${var}:-}\" python /tmp/sc.py $(printf '%q ' "$@")"
}
```

Now every test is `sc <bot> <tool> '<args>'`.

### 1. Liveness — the server is up

```bash
docker exec bot-tools-mcp python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:9110/health').read().decode())"
#   → ok
```

❌ If this fails: the container isn't up. `docker compose ps` /
`docker compose logs bot-tools-mcp`.

### 2. Auth — bad tokens are rejected, discovery is open

Discovery (`tools/list`) is intentionally open; tool *calls* require a valid
token. So: no token → still lists 15 tools; a bad token → cannot call a tool.

```bash
# a) discovery with NO token → 15 tool names
docker exec bot-tools-mcp python /tmp/sc.py

# b) a tool CALL with a bad token → rejected, NOT executed
docker exec -e TOKEN=WRONG bot-tools-mcp python /tmp/sc.py \
  send_email '{"to":["x@example.com"],"subject":"x","body":"x"}'
#   → "unknown or missing bot token", NOT a send
```

✅ (a) lists 15 tools. ✅ (b) errors with the auth message. If a bad token sends
mail, stop — the gate is broken.

### 3. Email — `send_email` lands in the inbox, From the right bot

```bash
# change you@yourmailbox to a real inbox you own
sc claudette send_email '{"to":["you@yourmailbox"],"subject":"bot-tools smoke","body":"hi from claudette"}'
```

✅ Prints `sent from claudette@<your domain> to you@yourmailbox`, and the mail
arrives **in the inbox** (not spam), **From `claudette@<your domain>`**, DKIM
pass. This closes the loop with Stage 1 through the real tool path.

### 4. Calendar — event create / list / delete + invite

```bash
# create → prints an event_id (copy it for the delete step)
sc claudette create_event '{"title":"Smoke test","start":"2026-07-15T15:00:00","end":"2026-07-15T15:30:00"}'

# list → should include it, with the same event_id
sc claudette list_events '{}'

# delete → pass the event_id back
sc claudette delete_event '{"event_id":"<the id from create>"}'

# invite → saves to the calendar AND emails a .ics (method=REQUEST)
sc claudette send_calendar_invite '{"to":["you@yourmailbox"],"title":"Smoke invite","start":"2026-07-16T10:00:00","end":"2026-07-16T10:30:00"}'
```

✅ `create` returns an id, `list` shows it, `delete` removes it (a second `list`
is empty). ✅ The invite email arrives as an **invitation** (calendar shows an
accept/decline), From `claudette@…`.

❌ `create_event` → "has no calendar": the bot's Radicale calendar wasn't created
(Stage 2) or `RADICALE_PASS_CLAUDETTE` is wrong.

### 5. Docs / sheets — round-trip + a working share link

This is the first step to exercise the **Nextcloud** password — a 401 here means
that app password is wrong or `$`-corrupted (see the `$$`-escape note above).

```bash
# a spreadsheet: create, write a cell, read it back
sc claudette sheet_create '{"path":"smoke.xlsx","sheets":["Data"]}'
sc claudette sheet_write_cell '{"path":"smoke.xlsx","sheet":"Data","cell":"A1","value":"hello"}'
sc claudette sheet_read '{"path":"smoke.xlsx","sheet":"Data"}'      # → [["hello"]]

# a document
sc claudette doc_create '{"path":"smoke.docx","content":"first line"}'
sc claudette doc_read '{"path":"smoke.docx"}'                        # → "first line"

# list the bot's files
sc claudette list_files '{}'

# a public, editable share link
sc claudette create_share_link '{"path":"smoke.xlsx","permission":"edit"}'
#   → https://cloud.<domain>/s/TOKEN
```

✅ The sheet round-trips (`[["hello"]]`), the doc round-trips (`"first line"`),
`list_files` shows both. ✅ Opening the `/s/…` link in an incognito window opens
the file in Collabora and lets you edit — the same round-trip proven in Stage 3,
now driven by the tool.

### 6. Per-bot isolation (optional but reassuring)

```bash
# claudette's file must NOT be readable as donna
sc donna doc_read '{"path":"smoke.docx"}'
#   → "file not found" (donna has her own root; she can't see claudette's file)
```

✅ Errors with "file not found" — each bot only sees its own files.

### Cleanup

```bash
# the /tmp/sc.py lives inside the container — it clears when the container is
# recreated; nothing to remove on the host.

# the smoke files created on the backends (smoke.xlsx/.docx, the test event)
# aren't removed by any v1 tool — delete them via the Nextcloud web UI and the
# Radicale/calendar client if you want a clean slate.
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
in [plans/stage-4-mcp-server.md](plans/stage-4-mcp-server.md).

---

## Troubleshooting (keyed to known traps)

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health` unreachable | container down, or 9110 not published | `docker compose ps`; check `ports:` in compose |
| **every** tool call → "unknown or missing bot token", even with the container's own token | (1) container running old image/env: rebuild+recreate needed; (2) token in `.env` differs from what's sent; (3) `.env` not loaded | `docker exec bot-tools-mcp printenv BOT_TOKEN_<BOT>` to see what it loaded; `docker compose up -d --build --force-recreate bot-tools-mcp`. NB: the server reads the bearer with `get_http_headers(include_all=True)` — without that flag FastMCP strips `authorization` and rejects everything (fixed, but the symptom to recognize). |
| compose WARN `The "XXXX" variable is not set. Defaulting to a blank string` | some line in `.env` contains a literal `$`, so Compose tries to expand `$XXXX` and blanks it — which **corrupts whatever secret that `$` is inside**. (A trailing `$` in `cat -A` output is just the newline marker, not this — this is Compose parsing the file.) | Confirm it's actually truncating: compare `grep KEY .env \| wc -c` with `docker exec bot-tools-mcp printenv KEY \| wc -c` — if the container's is shorter, Compose ate part of it. Fix: escape each `$` as `$$` in `.env`, or regenerate that credential without a `$` |
| `send_email` fails, names the smarthost | Brevo creds wrong / SMTP key rotated | re-check `BREVO_SMTP_*` in `.env` |
| email lands in **spam** | DKIM/SPF/DMARC drift | re-verify the Stage-1 DNS records |
| calendar op → "has no calendar" | the bot's Radicale calendar wasn't created, or wrong per-bot password | create it in the Radicale web UI (Stage 2); check `RADICALE_PASS_<BOT>` |
| docs op → connection/TLS error naming `cloud.<domain>` | a backend call hit the **public** URL (hairpin) | `NEXTCLOUD_URL` must be the **internal** `http://nextcloud:80` |
| docs/Nextcloud op → 401/auth failure but token was accepted | the Nextcloud app password is `$`-corrupted (see the compose WARN row) or wrong | verify with `docker exec ... printenv NEXTCLOUD_APP_PASSWORD_<BOT>`; escape `$$` or regenerate |
| `create_share_link` → OCS rejected | Nextcloud sharing disabled, or file owned by a different bot | share the file as its owner; enable link shares in Nextcloud |
| share link opens but won't edit | Collabora/WOPI issue, not the MCP server | see the Stage-3 lessons-learned doc |

**Reading logs:** `docker compose logs -f bot-tools-mcp`. Every backend error is
logged with the failing host/URL named (fail-loud by design) — the log tells you
which backend and which URL, so a hairpin or a wrong credential is obvious.
