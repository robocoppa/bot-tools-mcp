"""Per-bot identity: the bearer token IS the bot's identity.

The whole security model rests here. A bot presents a bearer token; we resolve it
to exactly one bot name. Everything a tool does — the From address it sends mail
as, the Nextcloud/Radicale user it authenticates as, the WebDAV path segment it
writes under — is derived from that resolved name, NEVER from anything the caller
passes in. There is deliberately no `from`/`user`/`as` parameter anywhere: a bot
can only ever act as itself.

The token→bot map is built once at import from the environment (`.env` on the
box). `BOT_TOKEN_CLAUDETTE=<token>` means "this token is claudette." Per-bot
backend secrets follow the same shape: `RADICALE_PASS_<BOT>`,
`NEXTCLOUD_APP_PASSWORD_<BOT>`.
"""

from __future__ import annotations

import os

# Env-var prefixes. The bot name is the suffix, lower-cased.
_TOKEN_PREFIX = "BOT_TOKEN_"
_RADICALE_PASS_PREFIX = "RADICALE_PASS_"
_NEXTCLOUD_PASS_PREFIX = "NEXTCLOUD_APP_PASSWORD_"


def build_token_map(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return {token: bot_name} from `BOT_TOKEN_<BOT>` vars.

    `env` defaults to `os.environ`; pass a dict in tests. Empty-valued vars are
    ignored (an unfilled placeholder must not authenticate anyone). If two bots
    somehow share a token, that's a misconfiguration we refuse to paper over.
    """
    env = os.environ if env is None else env
    out: dict[str, str] = {}
    for key, value in env.items():
        if not key.startswith(_TOKEN_PREFIX) or not value:
            continue
        bot = key[len(_TOKEN_PREFIX):].lower()
        if value in out and out[value] != bot:
            raise ValueError(
                f"token collision: same BOT_TOKEN value maps to both "
                f"{out[value]!r} and {bot!r}"
            )
        out[value] = bot
    return out


class Identity:
    """Resolves tokens to bots and derives per-bot backend credentials.

    Built once at startup from the environment and shared across requests. It
    holds no request state — the *resolved* bot for a given request is carried in
    the request context by the auth middleware, not here.
    """

    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._env = os.environ if env is None else env
        self._token_map = build_token_map(self._env)

    @property
    def bots(self) -> list[str]:
        """The known bot names (sorted, for stable logging/tests)."""
        return sorted(set(self._token_map.values()))

    def bot_for_token(self, token: str | None) -> str | None:
        """Resolve a bearer token to a bot name, or None if unknown/empty.

        A None/empty/whitespace token never resolves — callers treat None as
        'reject this request'.
        """
        if not token or not token.strip():
            return None
        return self._token_map.get(token.strip())

    def from_address(self, bot: str) -> str:
        """The bot's email From address: `<bot>@<MAIL_DOMAIN>`."""
        return f"{bot}@{self._require('MAIL_DOMAIN')}"

    def radicale_url(self) -> str:
        """The internal Radicale base URL (`RADICALE_URL`)."""
        return self._require("RADICALE_URL")

    def radicale_password(self, bot: str) -> str:
        """The bot's own Radicale password (`RADICALE_PASS_<BOT>`).

        Username on the CalDAV side is the bot name itself (Stage 2 owner_only).
        """
        return self._require(f"{_RADICALE_PASS_PREFIX}{bot.upper()}")

    def nextcloud_url(self) -> str:
        """The internal Nextcloud base URL (`NEXTCLOUD_URL`) — for backend I/O."""
        return self._require("NEXTCLOUD_URL")

    def nextcloud_public_url(self) -> str:
        """The public Nextcloud URL (`NEXTCLOUD_PUBLIC_URL`) — ONLY for share links
        handed to humans, never for a server-side backend call (it hairpins)."""
        return self._require("NEXTCLOUD_PUBLIC_URL")

    def nextcloud_password(self, bot: str) -> str:
        """The bot's own Nextcloud app password (`NEXTCLOUD_APP_PASSWORD_<BOT>`)."""
        return self._require(f"{_NEXTCLOUD_PASS_PREFIX}{bot.upper()}")

    def _require(self, key: str) -> str:
        """Fetch a required env var, failing loudly (never silently empty)."""
        value = self._env.get(key)
        if not value:
            raise KeyError(f"required environment variable {key!r} is missing or empty")
        return value
