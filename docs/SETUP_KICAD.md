# KiCad setup (one-time, per machine)

Requires **KiCad 7 or newer** — database libraries do not exist before that.

## The short version

1. Install the SQLite ODBC driver (below — **do this first**, it is the most common
   failure point).
2. Sign in to the LuGroupLib website with Slack and create a sync token at `/tokens`.
3. Run the installer:
   - **Windows:** double-click `client\install.bat`
   - **macOS:** double-click `client/install.command` (first time:
     `chmod +x install.command`)
   - **Linux:** `python3 client/install.py`
4. Open KiCad, press `A` in the schematic editor, and look for **`LuGroupLib_DB`**.

The installer asks for the server URL and your token, downloads the library, sets
KiCad's path variables, and registers the libraries. **Close KiCad before running it** —
KiCad rewrites its own configuration when it exits, so it would discard the changes.

Useful flags:

```bash
python install.py --dry-run
```

shows exactly what would change without touching anything. `--kicad-version 8.0` targets
a specific KiCad when several are installed; re-run it once per version if you use more
than one. Every file the installer edits is copied to `<name>.lugrouplib-bak` first, and
re-running is safe — entries are replaced, never duplicated.

---

## 1. Install the SQLite ODBC driver

This is the one step the installer will not do for you: it detects the driver and tells
you what is missing, but never downloads and runs a third-party installer on your behalf.

### Windows

KiCad is 64-bit, so you need the **64-bit** driver.

1. Download **`sqliteodbc_w64.exe`** from <http://www.ch-werner.de/sqliteodbc/>.
2. Run it (Next → Next → Finish).
3. Verify: **ODBC Data Source Administrator (64-bit)** → **Drivers** tab shows
   **`SQLite3 ODBC Driver`**.

> The name must read exactly **`SQLite3 ODBC Driver`** — that string is what
> `LuGroupLib.kicad_dbl` asks for. A 32-bit-only install is the usual near-miss.

### macOS

There is no packaged driver, so this is a little more work than on Windows:

```bash
brew install unixodbc sqliteodbc
odbcinst -q -d
```

The last command lists the driver names actually registered. If it prints something
other than `SQLite3 ODBC Driver` (commonly just `SQLite3`), edit the `connection_string`
in `LuGroupLib.kicad_dbl` to match. The file uses `${CWD}`, so no paths need changing.

On Apple Silicon, check that Homebrew and KiCad agree on architecture — a driver built
for `arm64` will not load into an `x86_64` KiCad, or vice versa.

### Linux

```bash
sudo apt install unixodbc libsqliteodbc     # or your distribution's equivalent
odbcinst -q -d
```

Same rule about the driver name.

## 2. Get a sync token

Everything past browsing needs a signed-in account, and the sync client authenticates
with a token rather than a browser session.

1. Open the LuGroupLib website and **Sign in with Slack**.
2. Go to **Sync tokens** → **Create token**. Label it after the machine.
3. Copy it immediately — it is stored hashed and is never shown again.

Make one token per machine, so losing a laptop means revoking one token rather than
resetting everyone's.

---

## What the installer actually does

Useful if you are debugging, or prefer to do it by hand.

**Path variables** (`Preferences → Configure Paths…`):

| Name | Value |
|------|-------|
| `LUGROUPLIB_DIR` | your local library folder, e.g. `C:\Users\<you>\Documents\KiCad_LuGroupLib` |
| `LUGROUPLIB_3D`  | `${LUGROUPLIB_DIR}/3dmodels` |

**Symbol libraries** (`Preferences → Manage Symbol Libraries… → Global`) — two entries,
and the nicknames matter:

| Nickname | Type | Path |
|----------|------|------|
| `LuGroupLib` | KiCad | `${LUGROUPLIB_DIR}/symbols/LuGroupLib.kicad_sym` |
| `LuGroupLib_DB` | Database | `${LUGROUPLIB_DIR}/LuGroupLib.kicad_dbl` |

`LuGroupLib_DB` is the one you browse. `LuGroupLib` is where it fetches the actual symbol
geometry from: database rows store references like `LuGroupLib:R_10K`, so that nickname
has to match **character-for-character** or every part will load with a broken symbol.

**Footprint library** (`Preferences → Manage Footprint Libraries… → Global`):

| Nickname | Type | Path |
|----------|------|------|
| `LuGroupLib` | KiCad | `${LUGROUPLIB_DIR}/footprints/LuGroupLib.pretty` |

## 3. Confirm it works

Schematic Editor → **Place → Add Symbol** (`A`). You should see **`LuGroupLib_DB`** with
one entry per sub-group beneath it — `General`, plus whatever libraries your lab has
created. Place a part; it arrives with its footprint already assigned, and the 3D model
resolves through `${LUGROUPLIB_3D}`.

---

## Daily use

1. Someone uploads a part on the website.
2. Sync — double-click `sync.bat`, or use the **LuGroupLib: Sync Library** toolbar button
   in the PCB editor (see [../kicad_plugin/README.md](../kicad_plugin/README.md)).
3. Symbol Chooser → **Refresh**. New footprints need a full KiCad restart.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Could not load database library" | ODBC driver missing or misnamed — see step 1. Run `python install.py --dry-run`, which reports what it finds. |
| Library loads but **no parts** | `lugrouplib.sqlite` missing from your library folder — re-run `sync.bat`. |
| Sync says **"the server rejected your sync token"** | The token was revoked or mistyped. Create a new one at `/tokens`. The KiCad plugin clears a rejected token so it re-prompts next run. |
| Sync returns **401** | You have no token at all. `client_config.json` needs a `"token"` value. |
| Every part has a **broken symbol** | The plain `LuGroupLib` symbol library entry is missing or misnamed — it must match the `LuGroupLib:` prefix in the database rows exactly. |
| "Footprint library 'LuGroupLib' not found" | Same problem on the footprint side. |
| New **symbols** don't appear | Symbol Chooser → **Refresh**. |
| New **footprints** don't appear | **Restart KiCad.** Footprint libraries are cached and the chooser refresh does not reload them. |
| A **new sub-library** doesn't appear | Sync again — sub-libraries live in `LuGroupLib.kicad_dbl`, which the bundle regenerates. Nothing needs reconfiguring locally. |
| 3D model missing | `LUGROUPLIB_3D` not set, or the part was uploaded without a model. |
| Installer changes seem to vanish | KiCad was open. It writes its configuration on exit and overwrote them. Close KiCad and re-run. |

To undo anything the installer did, restore the `.lugrouplib-bak` files next to KiCad's
`sym-lib-table`, `fp-lib-table`, and `kicad_common.json`.
