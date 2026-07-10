"""Nextcloud transport — WebDAV file I/O + the OCS share API, as a given bot.

Every call authenticates as the bot (Basic auth: username = bot name, password =
`NEXTCLOUD_APP_PASSWORD_<BOT>`) against the **internal** Nextcloud URL
(`http://nextcloud:80`). The internal URL matters: a server-side call to the
public `cloud.…` URL hairpins to plaintext on the host-mode tunnel and fails
(the entire Stage-3 saga). The public URL appears only in the share link this
returns to a human — and that value comes from the caller, never from a fetch.

`safe_path` is the security-critical helper: it rejects absolute paths and any
`..` traversal so a bot can never escape its own `/dav/files/<bot>/` root. That's
defense in depth over the per-bot credential (which already scopes access
server-side), but we don't rely on the server alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from bot_tools_mcp._util import BackendError, safe_path

# OCS share bitmask (Nextcloud normalizes on return; we assert on capability).
PERM_READ = 1
PERM_EDIT = 1 | 2 | 4 | 8 | 16  # read+update+create+delete+share = 31; edit link
SHARE_TYPE_PUBLIC_LINK = 3


class NextcloudError(BackendError):
    """Raised on any WebDAV/OCS failure; message names the operation + status."""


@dataclass
class NextcloudConfig:
    """Where Nextcloud lives, for backend I/O and (separately) share links."""

    internal_url: str  # http://nextcloud:80 — all file/OCS I/O
    public_url: str  # https://cloud.… — only ever put into a returned share link


def _dav_url(cfg: NextcloudConfig, bot: str, path: str) -> str:
    # An empty/blank path addresses the bot's root (used by list_files); any
    # non-empty path is validated against traversal.
    clean = safe_path(path) if path and path.strip() else ""
    encoded = quote(clean)
    return f"{cfg.internal_url}/remote.php/dav/files/{bot}/{encoded}"


def _client(bot: str, password: str, timeout: float = 30.0):
    """A short-lived httpx client Basic-auth'd as the bot. Imported lazily."""
    import httpx

    return httpx.Client(auth=(bot, password), timeout=timeout)


# --- WebDAV ---


def get_file(cfg: NextcloudConfig, bot: str, password: str, path: str) -> bytes:
    """Download a file's bytes from the bot's Nextcloud files."""
    url = _dav_url(cfg, bot, path)
    with _client(bot, password) as c:
        resp = c.get(url)
    if resp.status_code == 404:
        raise NextcloudError(f"file not found: {path!r}")
    if resp.status_code >= 400:
        raise NextcloudError(f"GET {path!r} failed: HTTP {resp.status_code}")
    return resp.content


def put_file(cfg: NextcloudConfig, bot: str, password: str, path: str, content: bytes) -> None:
    """Upload bytes to a path in the bot's Nextcloud files (creates or overwrites)."""
    url = _dav_url(cfg, bot, path)
    with _client(bot, password) as c:
        resp = c.put(url, content=content)
    if resp.status_code >= 400:
        raise NextcloudError(f"PUT {path!r} failed: HTTP {resp.status_code}")


def file_exists(cfg: NextcloudConfig, bot: str, password: str, path: str) -> bool:
    """True if the path exists in the bot's files (HEAD)."""
    url = _dav_url(cfg, bot, path)
    with _client(bot, password) as c:
        resp = c.head(url)
    if resp.status_code == 404:
        return False
    if resp.status_code >= 400:
        raise NextcloudError(f"HEAD {path!r} failed: HTTP {resp.status_code}")
    return True


def list_files(cfg: NextcloudConfig, bot: str, password: str, path: str = "") -> list[str]:
    """PROPFIND (depth 1) under a folder; return child paths relative to the root."""
    url = _dav_url(cfg, bot, path)  # empty path → the bot's root
    with _client(bot, password) as c:
        resp = c.request("PROPFIND", url, headers={"Depth": "1"})
    if resp.status_code == 404:
        raise NextcloudError(f"folder not found: {path!r}")
    if resp.status_code >= 400:
        raise NextcloudError(f"PROPFIND {path!r} failed: HTTP {resp.status_code}")
    return _parse_propfind_hrefs(resp.text, bot)


def _parse_propfind_hrefs(xml_text: str, bot: str) -> list[str]:
    """Pull child hrefs out of a PROPFIND multistatus, relative to the bot root.

    Uses ElementTree; the WebDAV namespace is 'DAV:'. The first href is the
    folder itself — dropped.
    """
    import xml.etree.ElementTree as ET
    from urllib.parse import unquote

    prefix = f"/remote.php/dav/files/{bot}/"
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise NextcloudError(f"could not parse PROPFIND response: {exc}") from exc

    out: list[str] = []
    for href in root.iter("{DAV:}href"):
        h = unquote(href.text or "")
        idx = h.find(prefix)
        if idx == -1:
            continue
        rel = h[idx + len(prefix):].strip("/")
        if rel:  # drop the folder-itself entry (empty rel)
            out.append(rel)
    return out


# --- OCS share API ---


def create_share_link(
    cfg: NextcloudConfig,
    bot: str,
    password: str,
    path: str,
    *,
    permission: str = "edit",
    expiry: str | None = None,
    share_password: str | None = None,
) -> str:
    """Create a public share link for a file the bot owns; return its public URL.

    `permission` is "edit" or "view". The returned URL uses the **public** host
    (that's its whole purpose — a link for a human); the request itself goes to
    the internal host.
    """
    # The tool layer validates `permission` ∈ {edit, view}; here we just map it
    # (anything other than "edit" → read-only, a safe default).
    clean = safe_path(path)
    perms = PERM_EDIT if permission == "edit" else PERM_READ

    data = {
        "path": f"/{clean}",
        "shareType": SHARE_TYPE_PUBLIC_LINK,
        "permissions": perms,
    }
    if expiry:
        data["expireDate"] = expiry
    if share_password:
        data["password"] = share_password

    url = f"{cfg.internal_url}/ocs/v2.php/apps/files_sharing/api/v1/shares"
    headers = {"OCS-APIRequest": "true", "Accept": "application/json"}
    with _client(bot, password) as c:
        resp = c.post(url, data=data, headers=headers)
    if resp.status_code >= 400:
        raise NextcloudError(f"share of {path!r} failed: HTTP {resp.status_code}")

    token = _share_token(resp.json(), path)
    return f"{cfg.public_url}/s/{token}"


def _share_token(ocs_json: dict, path: str) -> str:
    """Extract the share token from an OCS response, or raise with the status."""
    try:
        meta = ocs_json["ocs"]["meta"]
        if meta.get("statuscode") not in (200, 100):
            raise NextcloudError(
                f"share of {path!r} rejected: {meta.get('statuscode')} {meta.get('message')}"
            )
        return ocs_json["ocs"]["data"]["token"]
    except (KeyError, TypeError) as exc:
        raise NextcloudError(f"unexpected OCS share response for {path!r}: {exc}") from exc
