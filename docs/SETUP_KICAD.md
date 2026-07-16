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
> `HackLib.kicad_dbl` uses in its connection string. If you see only a 32-bit driver,
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
     "local_dir": "%USERPROFILE%\\Documents\\KiCad_HackLib"
   }
   ```
3. Double-click **`client/sync.bat`**. It downloads the bundle into
   `Documents\KiCad_HackLib\`, which should now contain `HackLib.kicad_dbl`,
   `hacklib.sqlite`, `symbols\`, `footprints\`, and `3dmodels\`.

## 4. Define KiCad environment variables

KiCad → **Preferences → Configure Paths… → Environment Variables**, add two:

| Name | Value |
|------|-------|
| `HACKLIB_DIR` | `C:\Users\<you>\Documents\KiCad_HackLib` |
| `HACKLIB_3D`  | `${HACKLIB_DIR}/3dmodels` |

(`HACKLIB_3D` is how footprints find their 3D models after a sync.)

## 5. Register the symbol libraries

KiCad (Schematic Editor) → **Preferences → Manage Symbol Libraries… → Global Libraries**:

1. Add a normal symbol library (📁 icon):
   - **Nickname:** `HackLib`
   - **Library Path:** `${HACKLIB_DIR}/symbols/HackLib.kicad_sym`
2. Add the **database** library (the icon for adding a database library, or "Add
   existing" and pick the `.kicad_dbl`):
   - **Nickname:** `HackLib_DB`
   - **Library Path:** `${HACKLIB_DIR}/HackLib.kicad_dbl`
   - **Plugin type:** Database

## 6. Register the footprint library

KiCad (PCB Editor) → **Preferences → Manage Footprint Libraries… → Global Libraries**:

- **Nickname:** `HackLib`
- **Library Path:** `${HACKLIB_DIR}/footprints/HackLib.pretty`

## 7. Confirm it works

- Schematic Editor → **Place → Add Symbol** (`A`) → in the chooser you should see the
  **`HackLib_DB` → Parts** library with the seeded resistor and its fields (MPN, Value,
  Manufacturer). Place it.
- The placed symbol already carries its footprint (`HackLib:R_0603`); the footprint's 3D
  model resolves via `${HACKLIB_3D}`.

---

## Daily use

1. Someone uploads a part in the web GUI.
2. You run **`sync.bat`**.
3. In the Symbol Chooser, click **Refresh** (or restart KiCad) — the new part appears.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Could not load database library" / driver error | 64-bit `SQLite3 ODBC Driver` not installed, or name mismatch — recheck step 1. |
| Library loads but **no parts** | `hacklib.sqlite` missing from `KiCad_HackLib` — re-run `sync.bat`. |
| New parts don't show after sync | Click **Refresh** in the Symbol Chooser, or restart KiCad. |
| Symbol places but **footprint missing** | Footprint library `HackLib` not registered (step 6), or sync not run. |
| 3D model not shown | `HACKLIB_3D` env var not set (step 4), or model wasn't uploaded with the part. |

> **Linux/macOS clients:** the driver name is whatever you set in `odbcinst.ini` (commonly
> `SQLite3`). If it differs from `SQLite3 ODBC Driver`, edit the `connection_string` in
> `HackLib.kicad_dbl` to match. Since the file uses `${CWD}`, no path edits are needed.
