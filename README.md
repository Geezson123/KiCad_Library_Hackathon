# LuGroupLib — SQL-backed KiCad library manager

A lightweight, self-hosted system for a research group to manage shared KiCad
**symbol**, **footprint**, and **3D-model** libraries, backed by a SQLite database and a
simple web GUI. Members browse and upload parts through the browser; a one-click **Sync**
pulls everything into their local KiCad install as a native **database library**.

Designed to run on a **1 GB RAM Ubuntu VPS** (only a Flask app + SQLite — no separate DB
server, no open database port).

```
 VPS (Ubuntu, 1 GB)                         Windows laptop (KiCad)
 ┌─────────────────────────────┐           ┌──────────────────────────────┐
 │ Flask web app + SQLite      │  HTTP     │ Documents/KiCad_LuGroupLib/     │
 │  · browse / upload parts    │◄─────────►│   LuGroupLib.kicad_dbl          │
 │  · /api/bundle → library.zip│  bundle   │   lugrouplib.sqlite  (via ODBC) │
 │                             │  .zip     │   symbols/LuGroupLib.kicad_sym  │
 │ library/  (single source)   │──────────►│   footprints/LuGroupLib.pretty/ │
 └─────────────────────────────┘  extract  │   3dmodels/                  │
        sync_client.py / sync.bat          └──────────────────────────────┘
```

## Why the design looks like this

KiCad database libraries **do not store symbol/footprint geometry in the database**. Each
DB row only holds a text reference such as `LuGroupLib:R_10K`, which KiCad resolves through
its normal symbol/footprint library tables to real `.kicad_sym` files and `.pretty`
folders. So the system keeps three things in lockstep and ships them together in the sync
bundle:

1. the **SQLite rows** (metadata + the `LuGroupLib:` references),
2. an aggregated **`LuGroupLib.kicad_sym`** + **`LuGroupLib.pretty/`** on disk,
3. the **3D model files**, linked from footprints via `${LUGROUPLIB_3D}`.

## Repository layout

| Path | What it is |
|------|-----------|
| `server/` | Flask app (`app.py`), DB layer (`db.py`), KiCad asset handling (`library.py`) |
| `library/` | The managed library = the sync bundle. `LuGroupLib.kicad_dbl` + generated content |
| `client/` | `sync.bat` + `sync_client.py` — the one-click sync for Windows |
| `kicad_plugin/` | Optional KiCad toolbar-button version of Sync ([README](kicad_plugin/README.md)) |
| `examples/` | Real example resistor (symbol/footprint/3D) used to seed the demo |
| `docs/` | [VPS setup](docs/SETUP_VPS.md), [KiCad setup](docs/SETUP_KICAD.md), [demo script](docs/DEMO_SCRIPT.md) |
| `deploy/` | `lugrouplib.service` systemd unit |

## Quick start (local)

```bash
cd server
python -m pip install -r requirements.txt
python app.py            # http://localhost:8000  (auto-seeds one example part)
```

Then follow **[docs/SETUP_KICAD.md](docs/SETUP_KICAD.md)** on the Windows machine to wire
KiCad to the synced folder, and **[docs/SETUP_VPS.md](docs/SETUP_VPS.md)** to deploy on the
VPS. For demo day, use **[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)**.

## Requirements covered

- **Lightweight (1 GB VPS):** Flask + SQLite only; idle ~30–50 MB, no DB daemon.
- **Integrates with KiCad:** native database library (`.kicad_dbl`) over SQLite/ODBC.
- **Web GUI:** browse + search + upload, **edit** (incl. replacing symbol/footprint/3D
  files), and **delete** parts.
- **One-click sync:** `sync.bat` (or the KiCad plugin) downloads the bundle into the local
  KiCad library folder. Sync **mirrors** the server — deleting a part on the server removes
  its footprint/3D files from every synced machine on the next sync.
