# HackLib Sync — KiCad plugin

Adds a **Sync** button to KiCad's PCB editor toolbar (and the Tools → External Plugins
menu). Clicking it downloads the latest shared library from the HackLib server into your
local KiCad library folder — the same job as `client/sync.bat`, but from inside KiCad.

> KiCad's Python action plugins live in the **PCB editor** (Pcbnew). Click Sync there,
> then switch to the Schematic editor and refresh the Symbol Chooser. (KiCad has no
> plugin toolbar in the schematic editor.)

## Install

1. Open the **PCB Editor** → **Tools → External Plugins → Open Plugin Directory**.
   (On Windows this is `%APPDATA%\kicad\<version>\scripting\plugins`.)
2. Copy the **`hacklib_sync`** folder (the one containing `__init__.py`) into that
   directory.
3. Back in KiCad: **Tools → External Plugins → Refresh Plugins** (or restart KiCad).
4. A green ⤓ **HackLib: Sync Library** button appears on the toolbar.

## Configure

You have two options:

- **Easiest:** the first time you click the button it asks for the server URL
  (`http://YOUR_VPS_IP:8000`) and remembers it. The target folder is taken automatically
  from the `HACKLIB_DIR` environment variable you set in KiCad
  (Preferences → Configure Paths), falling back to `~/Documents/KiCad_HackLib`.
- **Pre-configure:** copy `hacklib_config.example.json` to `hacklib_config.json` in the
  `hacklib_sync` folder and set the values. Leave `local_dir` as `""` to use `HACKLIB_DIR`.

## Use

Click **HackLib: Sync Library** → it downloads and extracts the bundle, then tells you how
many files it pulled. Refresh the HackLib database library in the Symbol Chooser (or
restart KiCad) to see new parts.

## Requirements

Just KiCad — the plugin uses only the Python standard library and wx, both bundled with
KiCad. Nothing to `pip install`.
