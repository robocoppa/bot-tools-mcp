# bot-tools-mcp · docs

Documentation for the shared **bot-tools MCP server**. Start with
[PROJECT_STATE.md](PROJECT_STATE.md) — it's the single continuity file (read it
first when resuming; newest status on top).

## The tracked/gitignored split

Two tiers, on purpose:

- **Tracked** (`docs/*.md`) — the continuity + ops docs. Safe to commit.
- **Gitignored** (`docs/plans/**`) — the staged build/deploy plans. They hold the
  real domain, LAN IP, and bot names, so they stay **laptop-local** and never get
  committed. `.gitignore` enforces this (`docs/plans/`). See it in Cursor, but
  it won't show up in a `git status`.

## Tracked docs (committed)

| Doc | What it's for |
|---|---|
| [PROJECT_STATE.md](PROJECT_STATE.md) | **Read first.** Single continuity file — current status, decisions, where things live, non-negotiables. |
| [BUILD_PLAN.md](BUILD_PLAN.md) | The execution roadmap: build the server tool-by-tool, hermetically, then deploy. Tracks which steps are done. |
| [DEPLOY_AND_SMOKE_TEST.md](DEPLOY_AND_SMOKE_TEST.md) | How to deploy to the Unraid box and run the layered live smoke tests (health → auth → each tool), plus troubleshooting. |

## Plans (gitignored — laptop-local)

The staged walkthrough that builds the whole capability, backend-first. Each stage
is an independent, verifiable unit that becomes its own as-built deploy record as
you execute it.

| Doc | Stage |
|---|---|
| `plans/README.md` | Stage index + end-state picture + locked decisions. |
| `plans/MASTER_PLAN.md` | The master design + every locked decision (the source the stages break down). |
| `plans/stage-0-prereqs.md` | Prereqs, layout & naming. |
| `plans/stage-1-email-smarthost.md` | Email deliverability (Brevo + DNS). |
| `plans/stage-2-calendar-radicale.md` | Calendar (Radicale / CalDAV). |
| `plans/stage-3-docs-nextcloud-collabora.md` | Docs/Sheets (Nextcloud + Collabora). |
| `plans/stage-3-appendix-lessons-learned.md` | ↳ Appendix to Stage 3: the host-mode-tunnel hairpin saga, distilled. |
| `plans/stage-4-mcp-server.md` | The MCP server itself (this repo's code). |
| `plans/stage-5-wire-bots.md` | Wire the bots (Hermes + OpenClaw config). |

> The plan docs use relative links among themselves; they resolve within
> `plans/`. If you're reading them on the box or in Cursor, open the `plans/`
> folder directly.
