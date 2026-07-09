"""Identity is the security spine — these tests pin the contract that makes
per-bot tokens trustworthy. All hermetic: env is passed as a dict, no backends,
no real os.environ.
"""

import pytest

from bot_tools_mcp.identity import Identity, build_token_map

# A representative env: three bots, each with a token + per-bot backend secrets.
ENV = {
    "MAIL_DOMAIN": "builtryte.xyz",
    "BOT_TOKEN_CLAUDETTE": "tok-claudette",
    "BOT_TOKEN_BRIGITTE": "tok-brigitte",
    "BOT_TOKEN_DONNA": "tok-donna",
    "RADICALE_PASS_CLAUDETTE": "rad-claudette",
    "NEXTCLOUD_APP_PASSWORD_CLAUDETTE": "nc-claudette",
}


def test_build_token_map_lowercases_bot_names():
    m = build_token_map(ENV)
    assert m == {
        "tok-claudette": "claudette",
        "tok-brigitte": "brigitte",
        "tok-donna": "donna",
    }


def test_empty_valued_token_var_is_ignored():
    # An unfilled placeholder must never authenticate anyone.
    env = {**ENV, "BOT_TOKEN_GHOST": ""}
    assert "" not in build_token_map(env).keys()
    assert build_token_map(env).get("") is None


def test_token_collision_is_rejected():
    env = {"BOT_TOKEN_A": "same", "BOT_TOKEN_B": "same"}
    with pytest.raises(ValueError, match="token collision"):
        build_token_map(env)


def test_bot_for_known_token():
    idn = Identity(ENV)
    assert idn.bot_for_token("tok-claudette") == "claudette"
    assert idn.bot_for_token("tok-brigitte") == "brigitte"


@pytest.mark.parametrize("bad", [None, "", "   ", "not-a-real-token", "TOK-CLAUDETTE"])
def test_unknown_or_empty_token_rejected(bad):
    # Case matters (tokens are opaque); None/empty/whitespace never resolve.
    assert Identity(ENV).bot_for_token(bad) is None


def test_token_is_stripped_before_lookup():
    # A stray leading/trailing space (e.g. from a header) still resolves.
    assert Identity(ENV).bot_for_token("  tok-donna  ") == "donna"


def test_from_address_derives_from_bot_not_input():
    idn = Identity(ENV)
    assert idn.from_address("claudette") == "claudette@builtryte.xyz"
    assert idn.from_address("donna") == "donna@builtryte.xyz"


def test_per_bot_backend_secrets():
    idn = Identity(ENV)
    assert idn.radicale_password("claudette") == "rad-claudette"
    assert idn.nextcloud_password("claudette") == "nc-claudette"


def test_missing_required_var_fails_loud():
    # No MAIL_DOMAIN → from_address must raise, not return a half-formed address.
    idn = Identity({"BOT_TOKEN_CLAUDETTE": "tok-claudette"})
    with pytest.raises(KeyError, match="MAIL_DOMAIN"):
        idn.from_address("claudette")


def test_missing_per_bot_secret_fails_loud():
    idn = Identity(ENV)  # only claudette has backend secrets in ENV
    with pytest.raises(KeyError, match="RADICALE_PASS_BRIGITTE"):
        idn.radicale_password("brigitte")


def test_bots_property_is_sorted_and_unique():
    assert Identity(ENV).bots == ["brigitte", "claudette", "donna"]
