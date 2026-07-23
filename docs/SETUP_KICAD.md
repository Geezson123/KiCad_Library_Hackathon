# KiCad + Windows setup (one-time, per laptop)

Do this **once** on each member's machine (and **early** on the demo laptop — the ODBC
driver is the single most common failure point). After this, syncing is just running
`sync.bat`.

Menu paths below are for **KiCad 8/9**; KiCad 7 is nearly identical. KiCad 7+ is required
for database libraries.

---

## 1. Install the SQLite ODBC driver (64-bit) — DO THIS FIRST

KiCad is 64-bit, so you need the **64-bit** driver.

1. Download **`sqliteodbc_w64.exe`** from <http://www.ch-werner.de/sqliteodbc/>.
2. Run the installer (Next → Next → Finish).
3. Verify: open **ODBC Data Source Administrator (64-bit)** (search "ODBC" in the Start
   menu, pick the **64-bit** one) → **Drivers** tab → confirm **`SQLite3 ODBC Driver`**
   is listed.

> The name must read exactly **`SQLite3 ODBC Driver`** — that string is what
> `LuGroupLib.kicad_dbl` uses in its connection string. If you see only a 32-bit driver,
> re-run the `_w64` installer.

## 2. Install Python (for the sync client)

Install Python 3 from <https://www.python.org/downloads/> and tick **"Add python.exe to
PATH"**. The sync client uses only the standard library — nothing else to install.

## 3. Do a first sync to create the local library folder

1. Copy `client/client_config.example.json` to `client/client_config.json`.
2. Edit it:
   ```json
   {
     "server_url": "http://YOUR_VPS_IP:8000",
     "local_dir": "%USERPROFILE%\\Documents\\KiCad_LuGroupLib"
   }
   ```
3. Double-click **`client/sync.bat`**. It downloads the bundle into
   `Documents\KiCad_LuGroupLib\`, which should now contain `LuGroupLib.kicad_dbl`,
   `lugrouplib.sqlite`, `symbols\`, `footprints\`, and `3dmodels\`.

## 4. Define KiCad environment variables

KiCad → **Preferences → Configure Paths… → Environment Variables**, add two:

| Name | Value |
|------|-------|
| `LUGROUPLIB_DIR` | `C:\Users\<you>\Documents\KiCad_LuGroupLib` |
| `LUGROUPLIB_3D`  | `${LUGROUPLIB_DIR}/3dmodels` |

(`LUGROUPLIB_3D` is how footprints find their 3D models after a sync.)

## 5. Register the symbol libraries

KiCad (Schematic Editor) → **Preferences → Manage Symbol Libraries… → Global Libraries**:

1. Add a normal symbol library (📁 icon):
   - **Nickname:** `LuGroupLib`
   - **Library Path:** `${LUGROUPLIB_DIR}/symbols/LuGroupLib.kicad_sym`
2. Add the **database** library (the icon for adding a database library, or "Add
   existing" and pick the `.kicad_dbl`):
   - **Nickname:** `LuGroupLib_DB`
   - **Library Path:** `${LUGROUPLIB_DIR}/LuGroupLib.kicad_dbl`
   - **Plugin type:** Database

## 6. Register the footprint library

KiCad (PCB Editor) → **Preferences → Manage Footprint Libraries… → Global Libraries**:

- **Nickname:** `LuGroupLib`
- **Library Path:** `${LUGROUPLIB_DIR}/footprints/LuGroupLib.pretty`

## 7. Confirm it works

- Schematic Editor → **Place → Add Symbol** (`A`) → in the chooser you should see the
  **`LuGroupLib_DB` → Parts** library with the seeded resistor and its fields (MPN, Value,
  Manufacturer). Place it.
- The placed symbol already carries its footprint (`LuGroupLib:R_0603`); the footprint's 3D
  model resolves via `${LUGROUPLIB_3D}`.

---

## Daily use

1. Someone uploads a part in the web GUI.
2. Sync — either double-click **`sync.bat`**, or click the **LuGroupLib: Sync Library**
   toolbar button in KiCad's PCB editor (see below).
3. In the Symbol Chooser, click **Refresh** (or restart KiCad) — the new part appears.

## Optional: Sync button inside KiCad

Instead of `sync.bat`, you can install the KiCad plugin so syncing is a toolbar button.
See **[../kicad_plugin/README.md](../kicad_plugin/README.md)**. Two ways to install:

- **Plugin & Content Manager (recommended):** Plugins → Plugin and Content Manager →
  **Install from File…** → pick `kicad_plugin/dist/LuGroupLib-Sync-1.0.0.zip`.
- **Manual:** copy the `lugrouplib_sync` folder into KiCad's plugin directory (Tools →
  External Plugins → Open Plugin Directory) and Refresh Plugins.

Either way, a green ⤓ **LuGroupLib: Sync Library** button appears in the PCB editor. It
reuses the `LUGROUPLIB_DIR` path from step 4, so the only thing to set is the server URL
(asked once on first click).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Could not load database library" / driver error | 64-bit `SQLite3 ODBC Driver` not installed, or name mismatch — recheck step 1. |
| Library loads but **no parts** | `lugrouplib.sqlite` missing from `KiCad_LuGroupLib` — re-run `sync.bat`. |
| New **symbols** don't show after sync | Click **Refresh** in the Symbol Chooser. |
| New **footprints** synced (file is in `LuGroupLib.pretty`) but KiCad can't find them | **Restart KiCad.** Footprint libraries are cached — new `.kicad_mod` files are only read when the library is reopened; the Symbol Chooser refresh does *not* reload them. |
| "Footprint library 'LuGroupLib' not found" | The footprint library table has no entry with nickname **exactly `LuGroupLib`** (step 6). The database rows reference `LuGroupLib:<name>`, so the fp-lib-table nickname must match `LuGroupLib` character-for-character. |
| 3D model not shown | `LUGROUPLIB_3D` env var not set (step 4), or model wasn't uploaded with the part. |

> **Linux/macOS clients:** the driver name is whatever you set in `odbcinst.ini` (commonly
> `SQLite3`). If it differs from `SQLite3 ODBC Driver`, edit the `connection_string` in
> `LuGroupLib.kicad_dbl` to match. Since the file uses `${CWD}`, no path edits are needed.
