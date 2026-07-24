"""Identity, sessions, and API tokens.

Everything here lives in a SEPARATE database (``config.APP_DB_PATH``) from the KiCad
library. ``config.DB_PATH`` is zipped into /api/bundle and extracted onto every synced
machine, so user emails, Slack IDs, token hashes and membership rows must never touch it.
Only bare integer ids (``parts.owner_id``, ``parts.library_id``) cross the boundary.

Sign-in is Slack "Sign in with Slack" (OpenID Connect). Workspace membership is the
access boundary: if ``config.SLACK_TEAM_ID`` is set, identities from any other workspace
are rejected. Browsing stays open to anyone who can reach the server -- only writes and
token management require a session.
"""
import datetime
import functools
import hashlib
import json
import secrets
import sqlite3
import urllib.parse
import urllib.request

from flask import session, redirect, url_for, flash, request, g, abort

import config
import db

SLACK_AUTHORIZE = "https://slack.com/openid/connect/authorize"
SLACK_TOKEN = "https://slack.com/api/openid.connect.token"
SLACK_USERINFO = "https://slack.com/api/openid.connect.userInfo"
SLACK_TEAM_CLAIM = "https://slack.com/team_id"

APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slack_id     TEXT    NOT NULL UNIQUE,
    email        TEXT    NOT NULL DEFAULT '',
    name         TEXT    NOT NULL DEFAULT '',
    avatar_url   TEXT    NOT NULL DEFAULT '',
    is_librarian INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    token_hash   TEXT    NOT NULL UNIQUE,
    label        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT '',
    last_used_at TEXT    NOT NULL DEFAULT ''
);

-- Stage 2 access control. Kept here (not in the library DB) so membership is not
-- published in the sync bundle.
CREATE TABLE IF NOT EXISTS library_members (
    library_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    added_at   TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (library_id, user_id)
);

CREATE TABLE IF NOT EXISTS part_editors (
    part_id  INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    added_at TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (part_id, user_id)
);

-- Stage 7 stock audit trail. The counts themselves live in the KiCad database so
-- they can reach the Symbol Chooser; who moved them is personal data and stays here.
CREATE TABLE IF NOT EXISTS stock_moves (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id    INTEGER NOT NULL,
    delta      INTEGER NOT NULL,
    resulting  INTEGER NOT NULL DEFAULT 0,
    reason     TEXT    NOT NULL DEFAULT '',
    reference  TEXT    NOT NULL DEFAULT '',
    user_id    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT ''
);
"""


def get_app_conn():
    conn = sqlite3.connect(config.APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_app_db():
    with get_app_conn() as conn:
        conn.executescript(APP_SCHEMA)


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
def upsert_user(slack_id, email="", name="", avatar_url=""):
    """Create or refresh a user from their Slack profile. Returns the user dict."""
    with get_app_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE slack_id = ?", (slack_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET email = ?, name = ?, avatar_url = ? WHERE id = ?",
                (email, name, avatar_url, row["id"]),
            )
        else:
            # The first users need librarian rights from somewhere: nobody exists yet to
            # grant them. LUGROUPLIB_LIBRARIANS bootstraps that list by Slack id.
            librarian = 1 if slack_id in config.BOOTSTRAP_LIBRARIANS else 0
            conn.execute(
                "INSERT INTO users (slack_id, email, name, avatar_url, is_librarian,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (slack_id, email, name, avatar_url, librarian, now_iso()),
            )
        return dict(conn.execute(
            "SELECT * FROM users WHERE slack_id = ?", (slack_id,)
        ).fetchone())


def get_user(user_id):
    with get_app_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def list_users():
    with get_app_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY name")]


def set_librarian(user_id, is_librarian):
    with get_app_conn() as conn:
        conn.execute(
            "UPDATE users SET is_librarian = ? WHERE id = ?",
            (1 if is_librarian else 0, user_id),
        )


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------
def login_user(user):
    session["user_id"] = user["id"]
    session.permanent = True


def logout_user():
    session.pop("user_id", None)


def current_user():
    """The signed-in user for this request, or None. Cached on ``g`` per request."""
    if "current_user" not in g:
        uid = session.get("user_id")
        g.current_user = get_user(uid) if uid else None
    return g.current_user


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Sign in to do that.", "error")
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def librarian_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Sign in to do that.", "error")
            return redirect(url_for("login", next=request.full_path))
        if not user["is_librarian"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# API tokens (for the sync client and the KiCad plugin)
# ---------------------------------------------------------------------------
def _hash_token(token):
    """Tokens are 256 bits of CSPRNG output, so a plain digest is sufficient -- there is
    no low-entropy secret here for a slow KDF to protect."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user_id, label=""):
    """Create a token. Returns the RAW token, which is shown to the user exactly once."""
    token = secrets.token_urlsafe(32)
    with get_app_conn() as conn:
        conn.execute(
            "INSERT INTO api_tokens (user_id, token_hash, label, created_at)"
            " VALUES (?, ?, ?, ?)",
            (user_id, _hash_token(token), label.strip(), now_iso()),
        )
    return token


def list_tokens(user_id):
    with get_app_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, label, created_at, last_used_at FROM api_tokens"
            " WHERE user_id = ? ORDER BY id DESC", (user_id,)
        )]


def revoke_token(user_id, token_id):
    with get_app_conn() as conn:
        conn.execute(
            "DELETE FROM api_tokens WHERE id = ? AND user_id = ?", (token_id, user_id)
        )


def user_for_token(token):
    """Resolve a raw token to its user, stamping last_used_at. None if unknown."""
    if not token:
        return None
    with get_app_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM api_tokens WHERE token_hash = ?", (_hash_token(token),)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE token_hash = ?",
            (now_iso(), _hash_token(token)),
        )
    return get_user(row["user_id"])


def request_token():
    """Pull a token off the request: Authorization: Bearer <t>, or ?token=<t>."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.args.get("token", "").strip()


def bundle_user():
    """Who is requesting the bundle: a token bearer, or a signed-in browser session."""
    return user_for_token(request_token()) or current_user()


# ---------------------------------------------------------------------------
# access control
# ---------------------------------------------------------------------------
# Two levels of ownership, because the two library kinds work differently:
#
#   'group'  libraries belong to a sub-group -- any member may add and edit anything
#            in them, which is what makes them a shared workspace.
#   'common' libraries are open to contribution from anyone, but each part stays
#            editable only by whoever uploaded it, plus people they invite.
#
# Group membership is therefore just a bulk version of a per-part invite, which is why
# both collapse into the single expression in can_edit_part below.
def member_ids(library_id):
    with get_app_conn() as conn:
        return [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM library_members WHERE library_id = ?", (library_id,)
        )]


def is_member(user_id, library_id):
    with get_app_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM library_members WHERE library_id = ? AND user_id = ?",
            (library_id, user_id),
        ).fetchone() is not None


def add_member(library_id, user_id):
    with get_app_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO library_members (library_id, user_id, added_at)"
            " VALUES (?, ?, ?)", (library_id, user_id, now_iso())
        )


def remove_member(library_id, user_id):
    with get_app_conn() as conn:
        conn.execute(
            "DELETE FROM library_members WHERE library_id = ? AND user_id = ?",
            (library_id, user_id),
        )


def part_editor_ids(part_id):
    with get_app_conn() as conn:
        return [r["user_id"] for r in conn.execute(
            "SELECT user_id FROM part_editors WHERE part_id = ?", (part_id,)
        )]


def add_part_editor(part_id, user_id):
    with get_app_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO part_editors (part_id, user_id, added_at)"
            " VALUES (?, ?, ?)", (part_id, user_id, now_iso())
        )


def remove_part_editor(part_id, user_id):
    with get_app_conn() as conn:
        conn.execute(
            "DELETE FROM part_editors WHERE part_id = ? AND user_id = ?",
            (part_id, user_id),
        )


def can_admin_library(user, lib):
    """Rename/delete the library itself, and manage its membership."""
    if not user or not lib:
        return False
    return bool(user["is_librarian"]) or user["id"] == lib["owner_id"]


def can_add_part(user, lib):
    """Upload a new part into this library."""
    if not user or not lib:
        return False
    if user["is_librarian"] or lib["kind"] == db.KIND_COMMON:
        return True
    return user["id"] == lib["owner_id"] or is_member(user["id"], lib["id"])


def can_edit_part(user, part, lib):
    """Edit or delete an existing part."""
    if not user or not part:
        return False
    if user["is_librarian"]:
        return True
    if part["owner_id"] and user["id"] == part["owner_id"]:
        return True
    if user["id"] in part_editor_ids(part["id"]):
        return True
    # In a sub-group library, membership grants edit rights across the library. In a
    # common library it does not: parts there stay with their uploader.
    if lib and lib["kind"] == db.KIND_GROUP:
        return user["id"] == lib["owner_id"] or is_member(user["id"], lib["id"])
    return False


# ---------------------------------------------------------------------------
# stock audit trail
# ---------------------------------------------------------------------------
def log_stock_move(part_id, delta, resulting, reason, reference, user_id):
    """Record who moved stock, by how much, and why.

    Deliberately append-only: the count in the library database is the current state,
    and this is the history that explains how it got there. When a shelf count and the
    database disagree, this log is the only way to find out where they diverged.
    """
    with get_app_conn() as conn:
        conn.execute(
            "INSERT INTO stock_moves (part_id, delta, resulting, reason, reference,"
            " user_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(part_id), int(delta), int(resulting), reason, reference,
             int(user_id or 0), now_iso()),
        )


def stock_history(part_id, limit=50):
    """Recent movements for a part, newest first, with the mover's name resolved."""
    with get_app_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM stock_moves WHERE part_id = ?"
            " ORDER BY id DESC LIMIT ?", (part_id, limit)
        )]
    for row in rows:
        user = get_user(row["user_id"]) if row["user_id"] else None
        row["user_name"] = user["name"] if user else "—"
    return rows


# ---------------------------------------------------------------------------
# Slack OpenID Connect
# ---------------------------------------------------------------------------
def slack_authorize_url(redirect_uri, state):
    params = {
        "response_type": "code",
        "client_id": config.SLACK_CLIENT_ID,
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if config.SLACK_TEAM_ID:
        params["team"] = config.SLACK_TEAM_ID
    return SLACK_AUTHORIZE + "?" + urllib.parse.urlencode(params)


def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_bearer(url, access_token):
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + access_token}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slack_exchange(code, redirect_uri):
    """Trade an authorization code for the caller's Slack profile.

    Returns a dict with slack_id / email / name / avatar_url / team_id. Raises
    ValueError with a user-presentable message if Slack rejects the exchange.

    The profile comes from the userInfo endpoint rather than by decoding the id_token:
    we fetch it ourselves over TLS straight from Slack, so it needs no signature check.
    """
    tok = _post_form(SLACK_TOKEN, {
        "client_id": config.SLACK_CLIENT_ID,
        "client_secret": config.SLACK_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if not tok.get("ok"):
        raise ValueError("Slack rejected the sign-in: %s" % tok.get("error", "unknown"))

    info = _get_bearer(SLACK_USERINFO, tok["access_token"])
    if not info.get("ok"):
        raise ValueError("Could not read your Slack profile: %s"
                         % info.get("error", "unknown"))

    team_id = info.get(SLACK_TEAM_CLAIM, "")
    if config.SLACK_TEAM_ID and team_id != config.SLACK_TEAM_ID:
        raise ValueError("That Slack account is not in this workspace.")

    return {
        "slack_id": info.get("sub", ""),
        "email": info.get("email", ""),
        "name": info.get("name", "") or info.get("email", ""),
        "avatar_url": info.get("picture", ""),
        "team_id": team_id,
    }
