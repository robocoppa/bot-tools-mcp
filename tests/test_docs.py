"""Docs/sheets tool tests. Hermetic: the Nextcloud WebDAV/OCS transport is
replaced by an in-memory file store, so openpyxl/python-docx round-trips run for
real but nothing hits the network.
"""

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from bot_tools_mcp import nextcloud_client as nc
from bot_tools_mcp.identity import Identity
from bot_tools_mcp.nextcloud_client import NextcloudConfig, safe_path
from bot_tools_mcp.tools import docs

ENV = {
    "MAIL_DOMAIN": "example.com",
    "NEXTCLOUD_URL": "http://nextcloud:80",
    "NEXTCLOUD_PUBLIC_URL": "https://cloud.example.com",
    "BOT_TOKEN_CLAUDETTE": "tok-claudette",
    "BOT_TOKEN_DONNA": "tok-donna",
    "NEXTCLOUD_APP_PASSWORD_CLAUDETTE": "nc-claudette",
    "NEXTCLOUD_APP_PASSWORD_DONNA": "nc-donna",
}


class _FakeCtx:
    def __init__(self, bot):
        self._bot = bot

    async def get_state(self, key):  # async, like FastMCP's Context
        return {"bot": self._bot}.get(key)


class _Store:
    """In-memory stand-in for the WebDAV backend. Keyed by (bot, path) so we can
    assert per-bot isolation. Records the config each call saw (to prove the
    internal URL — never the public one — is used for I/O)."""

    def __init__(self):
        self.files = {}
        self.auth_seen = []  # (bot, password) tuples
        self.urls_seen = []  # internal_url used per call
        self.shares = []

    def get_file(self, cfg, bot, password, path):
        self.auth_seen.append((bot, password))
        self.urls_seen.append(cfg.internal_url)
        key = (bot, safe_path(path))
        if key not in self.files:
            raise nc.NextcloudError(f"file not found: {path!r}")
        return self.files[key]

    def put_file(self, cfg, bot, password, path, content):
        self.auth_seen.append((bot, password))
        self.urls_seen.append(cfg.internal_url)
        self.files[(bot, safe_path(path))] = content

    def list_files(self, cfg, bot, password, path=""):
        self.auth_seen.append((bot, password))
        self.urls_seen.append(cfg.internal_url)
        return [p for (b, p) in self.files if b == bot]

    def create_share_link(self, cfg, bot, password, path, **kw):
        self.auth_seen.append((bot, password))
        self.urls_seen.append(cfg.internal_url)
        self.shares.append({"bot": bot, "path": path, **kw})
        safe_path(path)  # enforce guard like the real one
        return f"{cfg.public_url}/s/TOKEN123"


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(nc, "get_file", s.get_file)
    monkeypatch.setattr(nc, "put_file", s.put_file)
    monkeypatch.setattr(nc, "list_files", s.list_files)
    monkeypatch.setattr(nc, "create_share_link", s.create_share_link)
    return s


@pytest.fixture
def tools():
    cfg = NextcloudConfig(internal_url="http://nextcloud:80", public_url="https://cloud.example.com")
    return docs.register(FastMCP("t"), Identity(ENV), cfg)


# --- spreadsheets round-trip for real ---


async def test_sheet_create_write_read_roundtrip(store, tools):
    ctx = _FakeCtx("claudette")
    await tools["sheet_create"](ctx, path="book.xlsx", sheets=["Data"])
    await tools["sheet_write_cell"](ctx, path="book.xlsx", sheet="Data", cell="A1", value="hello")
    await tools["sheet_append_row"](ctx, path="book.xlsx", sheet="Data", values=["x", "y"])
    rows = await tools["sheet_read"](ctx, path="book.xlsx", sheet="Data")
    assert rows[0][0] == "hello"
    assert rows[1] == ["x", "y"]


async def test_sheet_read_missing_sheet_errors(store, tools):
    ctx = _FakeCtx("claudette")
    await tools["sheet_create"](ctx, path="b.xlsx", sheets=["Only"])
    with pytest.raises(ToolError, match="sheet 'Nope' not found"):
        await tools["sheet_read"](ctx, path="b.xlsx", sheet="Nope")


# --- documents round-trip for real ---


async def test_doc_create_read_append_roundtrip(store, tools):
    ctx = _FakeCtx("claudette")
    await tools["doc_create"](ctx, path="notes.docx", content="line one\nline two")
    text = await tools["doc_read"](ctx, path="notes.docx")
    assert text == "line one\nline two"
    await tools["doc_append"](ctx, path="notes.docx", content="line three")
    assert (await tools["doc_read"](ctx, path="notes.docx")).endswith("line three")


async def test_doc_write_replaces(store, tools):
    ctx = _FakeCtx("claudette")
    await tools["doc_create"](ctx, path="d.docx", content="original")
    await tools["doc_write"](ctx, path="d.docx", content="replaced")
    assert await tools["doc_read"](ctx, path="d.docx") == "replaced"


# --- per-bot auth + isolation ---


async def test_ops_authenticate_as_the_calling_bot(store, tools):
    await tools["doc_create"](_FakeCtx("claudette"), path="c.docx", content="x")
    await tools["doc_create"](_FakeCtx("donna"), path="d.docx", content="y")
    assert ("claudette", "nc-claudette") in store.auth_seen
    assert ("donna", "nc-donna") in store.auth_seen


async def test_a_bot_cannot_read_anothers_file(store, tools):
    await tools["doc_create"](_FakeCtx("claudette"), path="secret.docx", content="x")
    # donna asking for the same path resolves to (donna, secret.docx) — not found
    with pytest.raises(ToolError, match="file not found"):
        await tools["doc_read"](_FakeCtx("donna"), path="secret.docx")


async def test_unauthenticated_context_refused(store, tools):
    with pytest.raises(ToolError, match="no authenticated bot"):
        await tools["list_files"](_FakeCtx(None))


# --- path traversal is rejected at the tool boundary ---


@pytest.mark.parametrize("bad", ["/etc/passwd", "../secret.docx", "a/../../b.docx", ".."])
async def test_path_traversal_rejected(store, tools, bad):
    with pytest.raises(ToolError, match="path"):
        await tools["doc_read"](_FakeCtx("claudette"), path=bad)


# --- sharing: public URL returned, internal URL used for the call ---


async def test_create_share_link_returns_public_url(store, tools):
    url = await tools["create_share_link"](_FakeCtx("claudette"), path="book.xlsx", permission="edit")
    assert url == "https://cloud.example.com/s/TOKEN123"
    assert store.shares[0]["bot"] == "claudette"
    assert store.shares[0]["permission"] == "edit"


async def test_share_permission_validated(store, tools):
    # invalid permission is caught by the transport's guard; surfaced as ToolError
    with pytest.raises(ToolError):
        await tools["create_share_link"](_FakeCtx("claudette"), path="x.xlsx", permission="delete")


async def test_backend_io_never_uses_public_url(store, tools):
    ctx = _FakeCtx("claudette")
    await tools["sheet_create"](ctx, path="b.xlsx")
    await tools["list_files"](ctx)
    await tools["create_share_link"](ctx, path="b.xlsx")
    # every backend call recorded the INTERNAL url, never the public one
    assert store.urls_seen, "no backend calls recorded"
    assert all(u == "http://nextcloud:80" for u in store.urls_seen)
    assert "cloud.example.com" not in " ".join(store.urls_seen)


# --- safe_path unit tests ---


@pytest.mark.parametrize("good", ["report.xlsx", "reports/q3.xlsx", "a/b/c.docx", "./x.txt"])
def test_safe_path_allows_relative(good):
    assert not safe_path(good).startswith("/")
    assert ".." not in safe_path(good).split("/")


@pytest.mark.parametrize("bad", ["/etc/passwd", "../secret", "a/../../b", "..", "", "   ", "\\win"])
def test_safe_path_rejects_escape(bad):
    with pytest.raises(ToolError):
        safe_path(bad)
