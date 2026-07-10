"""The FastMCP server: per-bot bearer-token auth in front of the tools.

The middleware is the gate. Every MCP request must carry
`Authorization: Bearer <token>`; the middleware resolves it to a bot via
`Identity`, rejects anything unknown, and stashes the resolved bot in the request
context. Tools read the bot back with `current_bot()` — they never accept a
caller-supplied identity, so a bot can only ever act as itself.

`/health` is an unauthenticated liveness route for the compose healthcheck (a
bare GET on `/mcp` is rejected by transport+auth rules, so it's useless as a
probe — hit `/health` instead).
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.exceptions import AuthorizationError, ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette.responses import PlainTextResponse

from bot_tools_mcp.identity import Identity

# The request-context key under which the resolved bot name is stashed.
_BOT_STATE_KEY = "bot"


def _bearer_from_headers() -> str | None:
    """Pull the bearer token out of the current request's Authorization header.

    `include_all=True` is REQUIRED: get_http_headers() strips `authorization`
    (and other sensitive headers) by default, so without it the token never
    reaches us and every call is rejected as "unknown or missing bot token".
    """
    auth = get_http_headers(include_all=True).get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    return auth[len("bearer "):].strip() or None


class BotAuthMiddleware(Middleware):
    """Gate every tool *call* on a valid per-bot bearer token.

    We gate on `on_call_tool` — the hook that fires only when a tool actually
    runs — not on every request. Discovery (`initialize`, `ping`, `tools/list`)
    flows freely: knowing tool *names* leaks nothing (they're in the README),
    and MCP clients list tools before presenting credentials. Everything that
    *does* something requires a token; an unknown/missing one raises
    `AuthorizationError`, and the resolved bot is stashed for the tool to read.
    """

    def __init__(self, identity: Identity) -> None:
        self._identity = identity

    async def on_call_tool(self, ctx: MiddlewareContext, call_next):
        bot = self._identity.bot_for_token(_bearer_from_headers())
        if bot is None:
            # Fail loud and specific — never a bare 500.
            raise AuthorizationError("unknown or missing bot token")

        # set_state is async in this FastMCP — must be awaited or the write is a
        # dangling coroutine and the bot never actually lands in the context.
        await ctx.fastmcp_context.set_state(_BOT_STATE_KEY, bot)
        return await call_next(ctx)


async def current_bot(ctx) -> str:
    """Read the authenticated bot from a tool's Context.

    `get_state` is async in this FastMCP version — it MUST be awaited, or you get
    a coroutine object instead of the bot name (which then poisons the From
    header / credential lookup). Raises `ToolError` if absent — which means a tool
    ran without passing the auth gate (a wiring bug), and we refuse to guess.
    """
    bot = await ctx.get_state(_BOT_STATE_KEY)
    if not bot:
        raise ToolError("no authenticated bot in context")
    return bot


async def bot_creds(ctx, password_for) -> tuple[str, str]:
    """Return (bot, password) for the authenticated bot, using the given per-bot
    password accessor (e.g. `identity.radicale_password`).

    The single place tools derive backend credentials from the authed bot —
    keeps that security-critical step out of each tool module.
    """
    bot = await current_bot(ctx)
    return bot, password_for(bot)


def create_server(identity: Identity | None = None, *, register_tools: bool = True) -> FastMCP:
    """Build the FastMCP app with auth wired in.

    `identity` is injectable for tests; defaults to one built from the process
    environment. Set `register_tools=False` to build just the app + auth gate
    without touching backend config (used by tests that don't exercise a tool) —
    otherwise tool modules are registered and will read their backend settings
    from the environment at startup, failing loud if any are missing.
    """
    identity = identity or Identity()
    mcp = FastMCP("bot-tools")
    mcp.add_middleware(BotAuthMiddleware(identity))

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request):  # unauthenticated liveness for the healthcheck
        return PlainTextResponse("ok")

    if register_tools:
        _register_tools(mcp, identity)

    return mcp


def _register_tools(mcp: FastMCP, identity: Identity) -> None:
    """Attach every tool module to the app. Imported here (not at module top) to
    avoid a circular import — the tool modules import `current_bot` from us."""
    from bot_tools_mcp.tools import calendar_tools, docs, email_tools

    email_tools.register(mcp, identity)
    calendar_tools.register(mcp, identity)
    docs.register(mcp, identity)


def run() -> None:
    """Entry point: serve MCP over streamable-HTTP on the LAN port.

    Host/port are overridable via `MCP_HOST`/`MCP_PORT` (default 0.0.0.0:9110)
    so the container and compose can set them without a code change.
    """
    import os

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "9110"))
    server = create_server()
    server.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    run()
