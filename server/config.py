"""Central paths and constants for the LuGroupLib server.

The whole system revolves around a single ``library/`` directory that is BOTH the
web app's store and the KiCad-facing library bundle. The download "sync" is just a
zip of this directory, so every artifact KiCad needs lives under LIBRARY_DIR.
"""
import os

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SERVER_DIR)

# Allow override so the app can be relocated on the VPS without code changes.
LIBRARY_DIR = os.environ.get(
    "LUGROUPLIB_LIBRARY_DIR", os.path.join(REPO_ROOT, "library")
)

# KiCad-facing artifacts (all inside the synced bundle)
DB_PATH = os.path.join(LIBRARY_DIR, "lugrouplib.sqlite")
SYMBOLS_LIB = os.path.join(LIBRARY_DIR, "symbols", "LuGroupLib.kicad_sym")
FOOTPRINTS_DIR = os.path.join(LIBRARY_DIR, "footprints", "LuGroupLib.pretty")
MODELS_DIR = os.path.join(LIBRARY_DIR, "3dmodels")
DBL_FILE = os.path.join(LIBRARY_DIR, "LuGroupLib.kicad_dbl")

# Example seed assets (real, placeable parts so the demo is never empty)
EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")

# ---------------------------------------------------------------------------
# Identity / access control
# ---------------------------------------------------------------------------
# Auth lives in a SEPARATE database that is never bundled. DB_PATH above is zipped
# into /api/bundle and lands on every synced machine, so it must never hold user
# emails, Slack IDs, or token hashes. Only bare integer ids (parts.owner_id,
# parts.library_id) cross over into the KiCad-facing database.
APP_DB_PATH = os.environ.get(
    "LUGROUPLIB_APP_DB", os.path.join(SERVER_DIR, "app.sqlite")
)

# Slack "Sign in with Slack" (OpenID Connect) credentials. Create the app at
# https://api.slack.com/apps -> OAuth & Permissions, and add the redirect URL
# <your server>/auth/slack/callback.
SLACK_CLIENT_ID = os.environ.get("LUGROUPLIB_SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.environ.get("LUGROUPLIB_SLACK_CLIENT_SECRET", "")

# Restrict sign-in to one workspace. If set, a Slack identity whose team does not
# match is rejected — this is what makes "workspace member" the access boundary.
SLACK_TEAM_ID = os.environ.get("LUGROUPLIB_SLACK_TEAM_ID", "")

# Slack IDs (comma-separated) bootstrapped as master librarians on first sign-in.
# Needed because the very first user has nobody to promote them.
BOOTSTRAP_LIBRARIANS = [
    s.strip() for s in os.environ.get("LUGROUPLIB_LIBRARIANS", "").split(",") if s.strip()
]

# DEVELOPMENT ONLY: enables /dev-login, which signs in as an arbitrary name with no
# credentials whatsoever. Never set this on a reachable server.
DEV_LOGIN = os.environ.get("LUGROUPLIB_DEV_LOGIN", "") == "1"


def slack_configured():
    return bool(SLACK_CLIENT_ID and SLACK_CLIENT_SECRET)


# ---------------------------------------------------------------------------
# Part ingest (Stage 6)
# ---------------------------------------------------------------------------
# Free key from https://www.mouser.com/api-hub/ — supplies the factual part data.
MOUSER_API_KEY = os.environ.get("LUGROUPLIB_MOUSER_KEY", "")

# Optional. Only used for the judgement calls (category, keywords, footprint match);
# ingest still works without it, just with more fields left for the user to fill in.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# The single nickname every part is filed under. Keeps the KiCad symbol/footprint
# library tables to one entry each.
LIB_NICKNAME = "LuGroupLib"

# .kicad_sym format version written by kiutils. KiCad auto-migrates older versions.
SYMLIB_VERSION = "20211014"


def ensure_dirs():
    """Create the managed library directory tree if it does not exist yet."""
    for path in (
        LIBRARY_DIR,
        os.path.dirname(SYMBOLS_LIB),
        FOOTPRINTS_DIR,
        MODELS_DIR,
    ):
        os.makedirs(path, exist_ok=True)
