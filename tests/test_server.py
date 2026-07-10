"""Server + auth-middleware tests. Hermetic: no real backends, no bound port.

The auth middleware gates every *tool call*, so we exercise its decision logic
directly (with the Authorization header mocked) rather than through the full
streamable-HTTP handshake — the decision is what matters, and testing it in
isolation keeps these fast and unambiguous. Discovery (initialize / tools/list)
is deliberately ungated, so there's nothing to assert there. `/health` is
checked through a real ASGI client since it's a plain route.
"""

from unittest.mock import patch

import pytest
from fastmcp.exceptions import AuthorizationError, ToolError
from starlette.testclient import TestClient

from bot_tools_mcp.identity import Identity
from bot_tools_mcp.server import (
    BotAuthMiddleware,
    create_server,
    current_bot,
)

ENV = {
    "MAIL_DOMAIN": "example.com",
    "BOT_TOKEN_CLAUDETTE": "tok-claudette",
    "BOT_TOKEN_DONNA": "tok-donna",
}


# --- test doubles: a minimal MiddlewareContext + fastmcp_context ---


class _FakeState:
    # get_state/set_state are ASYNC in FastMCP — the doubles must be too, or the
    # tests pass while production breaks (exactly the bug that shipped once).
    def __init__(self):
        self._store = {}

    async def set_state(self, key, value):
        self._store[key] = value

    async def get_state(self, key):
        return self._store.get(key)


class _FakeCtx:
    """Stands in for MiddlewareContext: carries a .fastmcp_context."""

    def __init__(self):
        self.fastmcp_context = _FakeState()


def _mw():
    return BotAuthMiddleware(Identity(ENV))


async def _passthrough(ctx):
    return "PASSED"


def _with_header(value):
    # Patch the header accessor the middleware calls.
    return patch("bot_tools_mcp.server.get_http_headers", return_value={"authorization": value})


def _with_no_headers():
    return patch("bot_tools_mcp.server.get_http_headers", return_value={})


# --- regression: the header accessor MUST include sensitive headers ---


def test_bearer_reader_requests_sensitive_headers():
    """get_http_headers() strips `authorization` by default — the reader MUST
    pass include_all=True, or the token never arrives and every call is rejected.
    This guards the exact production bug the mocked auth tests could not catch.
    """
    from unittest.mock import MagicMock

    from bot_tools_mcp.server import _bearer_from_headers

    fake = MagicMock(return_value={"authorization": "Bearer tok-donna"})
    with patch("bot_tools_mcp.server.get_http_headers", fake):
        assert _bearer_from_headers() == "tok-donna"
    fake.assert_called_once_with(include_all=True)


# --- auth gate (fires on every tool call) ---


async def test_valid_token_passes_and_stashes_bot():
    ctx = _FakeCtx()
    with _with_header("Bearer tok-claudette"):
        result = await _mw().on_call_tool(ctx, _passthrough)
    assert result == "PASSED"
    assert await ctx.fastmcp_context.get_state("bot") == "claudette"


@pytest.mark.parametrize(
    "header",
    ["Bearer WRONG", "Bearer ", "tok-claudette", "Basic tok-claudette", ""],
)
async def test_bad_or_missing_token_is_rejected(header):
    ctx = _FakeCtx()
    with _with_header(header):
        with pytest.raises(AuthorizationError, match="unknown or missing bot token"):
            await _mw().on_call_tool(ctx, _passthrough)


async def test_no_authorization_header_is_rejected():
    ctx = _FakeCtx()
    with _with_no_headers():
        with pytest.raises(AuthorizationError):
            await _mw().on_call_tool(ctx, _passthrough)


async def test_bearer_is_case_insensitive_scheme_but_not_token():
    # "bearer" scheme in any case is fine; the token itself is exact.
    ctx = _FakeCtx()
    with _with_header("bearer tok-donna"):
        await _mw().on_call_tool(ctx, _passthrough)
    assert await ctx.fastmcp_context.get_state("bot") == "donna"

    ctx = _FakeCtx()
    with _with_header("Bearer TOK-DONNA"):  # wrong-case token must fail
        with pytest.raises(AuthorizationError):
            await _mw().on_call_tool(ctx, _passthrough)


# --- current_bot() helper ---


async def test_current_bot_reads_stashed_value():
    ctx = _FakeState()
    await ctx.set_state("bot", "claudette")
    assert await current_bot(ctx) == "claudette"


async def test_current_bot_raises_when_unauthenticated():
    # A tool running with no bot in context = a wiring bug; refuse to guess.
    ctx = _FakeState()
    with pytest.raises(ToolError, match="no authenticated bot"):
        await current_bot(ctx)


# --- /health route ---


def test_health_route_is_unauthenticated_and_ok():
    # register_tools=False: this test is about the route + auth gate, not backends.
    app = create_server(Identity(ENV), register_tools=False).http_app()
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_create_server_builds_with_default_env(monkeypatch):
    # create_server() with no identity builds one from the environment.
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    server = create_server(register_tools=False)
    assert server.name == "bot-tools"
