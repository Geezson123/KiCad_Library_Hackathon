# LuGroupLib

A self-hosted shared KiCad parts library for the Lu group. Members browse and add parts
in a web app; a sync client pulls the whole library into their local KiCad as a native
**database library**, so every sub-group sees the same symbols, footprints, 3D models,
and stock levels.

Runs comfortably on a 1 GB Ubuntu VPS — a Flask app and two SQLite files, no database
server and no open database port.

## What it does

| | |
|---|---|
| **Shared library** | Symbols, footprints, and 3D models managed together, so a part is never half-added. |
| **Sub-group libraries** | Each team gets its own library, appearing as its own entry in KiCad's Symbol Chooser. Plus `common` libraries anyone can contribute to. |
| **Permissions** | Sub-group libraries are members-only. In common libraries anyone can add a part, but each part stays editable by whoever uploaded it and the people they invite. Master librarians can edit everything. |
| **Slack sign-in** | Your lab Slack workspace is the account system. No separate passwords. |
| **Add from a Mouser link** | Paste a product URL: Mouser supplies the facts, Claude drafts the category, keywords, and a footprint suggestion, and you review before anything is saved. |
| **Inventory** | Stock counts and storage locations, visible **inside KiCad's Symbol Chooser** so you can see what's on the shelf while picking a part. |
| **Receipt ingestion** | Upload a Mouser order confirmation; it's read, matched to your parts, and shown for review before stock moves. |
| **Incremental sync** | Only changed files transfer. A sync with nothing new moves zero bytes. |
| **One-command install** | A script sets up KiCad on Windows, macOS, or Linux. |

## Documentation

| Guide | For |
|-------|-----|
| **[User guide](docs/USER_GUIDE.md)** | Everyone. How to use the website and the sync client. |
| **[KiCad setup](docs/SETUP_KICAD.md)** | Everyone, once per machine. Installer, ODBC driver, troubleshooting. |
| **[VPS setup](docs/SETUP_VPS.md)** | Whoever runs the server. Install, configure, update, back up. |
| **[Deployment plan](docs/DEPLOYMENT.md)** | Rollout: Tailscale test server first, public VPS second. |
| **[KiCad plugin](kicad_plugin/README.md)** | Optional sync button inside KiCad. |

## How it fits together

```
 VPS                                        Member's machine
 ┌──────────────────────────────┐          ┌─────────────────────────────────┐
 │ Flask app                    │          │ Documents/KiCad_LuGroupLib/     │
 │  · browse / add / edit parts │  HTTPS   │   LuGroupLib.kicad_dbl          │
 │  · libraries & permissions   │◄────────►│   lugrouplib.sqlite   (ODBC)    │
 │  · inventory & receipts      │          │   symbols/LuGroupLib.kicad_sym  │
 │                              │  only    │   footprints/LuGroupLib.pretty/ │
 │ library/     ships to users  │  changed │   3dmodels/                     │
 │ server/app.sqlite  NEVER does│  files   └─────────────────────────────────┘
 └──────────────────────────────┘             install.py · sync.bat · plugin
```

### Two databases, on purpose

`library/lugrouplib.sqlite` is copied to **every** member's machine as part of the sync
bundle, so it holds only non-personal data: parts, libraries, and stock counts.

`server/app.sqlite` never leaves the server. It holds users, API tokens, library
membership, per-part editor invites, and the stock audit trail — everything that names a
person.

When adding a table, decide which side it belongs on first.

### Why the library ships as files, not just rows

KiCad database libraries **don't store symbol or footprint geometry**. A row holds only a
text reference like `LuGroupLib:R_10K`, which KiCad resolves through its normal library
tables to real `.kicad_sym` files and `.pretty` folders. So three things move together in
every sync: the SQLite rows, the aggregated symbol/footprint files, and the 3D models
(linked from footprints via `${LUGROUPLIB_3D}`).

## Repository layout

| Path | What it is |
|------|-----------|
| `server/` | The web app. `app.py` routes, `db.py` library database, `auth.py` identity and permissions, `dbl.py` generates the `.kicad_dbl`, `mouser.py` + `ai.py` part ingest, `manifest.py` incremental sync |
| `library/` | The managed library — this directory *is* the sync bundle |
| `client/` | `install.py` (setup), `sync_client.py` + `sync.bat` (sync), `lugrouplib_core.py` (shared logic) |
| `kicad_plugin/` | Optional toolbar button for syncing inside KiCad |
| `tests/` | Verification suites — `python tests/run_all.py` |
| `deploy/` | systemd unit and environment template |
| `docs/` | The guides listed above |

## Running locally

```bash
python -m pip install -r server/requirements.txt
```

```bash
LUGROUPLIB_DEV_LOGIN=1 python server/app.py
```

Then open `http://localhost:8000`. `LUGROUPLIB_DEV_LOGIN=1` lets you sign in as anybody
without credentials so you can try things before Slack is configured — it shows a warning
banner on every page and must never be set on a reachable server.

## Tests

```bash
python tests/run_all.py
```

Seven suites, ~250 checks. They run against throwaway copies of both databases, so they
never touch your real library.

## Configuration reference

All configuration is environment variables. See
[docs/SETUP_VPS.md](docs/SETUP_VPS.md) for how to set them in production.

| Variable | Required | Purpose |
|----------|----------|---------|
| `LUGROUPLIB_SECRET` | **yes, in production** | Signs session cookies. Random per-process if unset, which logs everyone out on restart. |
| `LUGROUPLIB_SLACK_CLIENT_ID` | for sign-in | Slack app credentials |
| `LUGROUPLIB_SLACK_CLIENT_SECRET` | for sign-in | |
| `LUGROUPLIB_SLACK_TEAM_ID` | recommended | Restricts sign-in to one workspace |
| `LUGROUPLIB_LIBRARIANS` | first run | Comma-separated Slack user IDs granted master librarian on first sign-in |
| `LUGROUPLIB_HTTPS` | behind TLS | Set to `1` to mark session cookies Secure |
| `LUGROUPLIB_LIBRARY_DIR` | no | Where the library lives (default `library/`) |
| `LUGROUPLIB_APP_DB` | no | Where the identity database lives (default `server/app.sqlite`) |
| `LUGROUPLIB_MOUSER_KEY` | for Mouser ingest | Free key from mouser.com/api-hub |
| `ANTHROPIC_API_KEY` | for AI features | Enables metadata drafting and receipt reading |
| `LUGROUPLIB_DEV_LOGIN` | **never in production** | Passwordless sign-in as anyone |
| `LUGROUPLIB_DEBUG` | **never in production** | Flask debug mode. Serves the Werkzeug debugger, which runs arbitrary code from the browser. Off by default; only meaningful with `python app.py`, since gunicorn ignores it. |
