# LuGroupLib Sync — KiCad plugin

Adds a **Sync** button to KiCad's PCB editor toolbar (and the Tools → External Plugins
menu). Clicking it downloads the latest shared library from the LuGroupLib server into your
local KiCad library folder — the same job as `client/sync.bat`, but from inside KiCad.
After syncing it pops a small dialog reminding you how to reload libraries.

> KiCad's Python action plugins live in the **PCB editor** (Pcbnew). Click Sync there,
> then switch to the Schematic editor and refresh the Symbol Chooser. (KiCad has no
> plugin toolbar in the schematic editor.)

## Install — Option A: Plugin & Content Manager (recommended)

1. Build the package (or use the prebuilt one in `dist/`):
   ```bash
   python kicad_plugin/build_pcm_package.py     # -> dist/LuGroupLib-Sync-1.0.0.zip
   ```
2. KiCad main window → **Plugins → Plugin and Content Manager**.
3. Click **Install from File…** and pick `dist/LuGroupLib-Sync-1.0.0.zip`.
4. Apply/close. Open the **PCB Editor**; a green ⤓ **LuGroupLib: Sync Library** button is on
   the toolbar.

## Install — Option B: manual copy

1. PCB Editor → **Tools → External Plugins → Open Plugin Directory**
   (Windows: `%APPDATA%\kicad\<version>\scripting\plugins`).
2. Copy the **`lugrouplib_sync`** folder (the one with `__init__.py`) into that directory.
3. **Tools → External Plugins → Refresh Plugins** (or restart KiCad).

## Configure

- **Easiest:** the first click asks for the server URL (`http://YOUR_VPS_IP:8000`) and
  remembers it. The target folder comes automatically from the `LUGROUPLIB_DIR` environment
  variable you set in KiCad (Preferences → Configure Paths), else `~/Documents/KiCad_LuGroupLib`.
- **Pre-configure:** copy `lugrouplib_config.example.json` → `lugrouplib_config.json` next to the
  plugin and set the values. Leave `local_dir` as `""` to use `LUGROUPLIB_DIR`.

## Use

Click **LuGroupLib: Sync Library** → it downloads and extracts the bundle, then shows how
many files it pulled and how to reload. Refresh the Symbol Chooser (or restart KiCad) to
see new parts.

## Layout / how it's built

```
client/
  lugrouplib_core.py               # CANONICAL shared sync core (download + extract)
  sync_client.py                # CLI wrapper over lugrouplib_core
kicad_plugin/
  lugrouplib_sync/                 # the plugin (UI + registration)
    __init__.py                 #   ← wx UI + ActionPlugin, imports lugrouplib_core
    lugrouplib_core.py             #   ← copy of client/lugrouplib_core.py (build keeps it in sync)
    icon.png                    #   24x24 toolbar icon
    lugrouplib_config.example.json
  pcm/
    metadata.json               # PCM manifest (v1 schema, KiCad 6.0+)
    resources/icon.png          # 64x64 package icon shown in the PCM
  build_pcm_package.py          # copies the core + zips into dist/LuGroupLib-Sync-<v>.zip
  dist/LuGroupLib-Sync-1.0.0.zip   # ready to "Install from File"
```

**One implementation, shared:** the download/extract code lives once in
`client/lugrouplib_core.py`. The CLI imports it directly; `build_pcm_package.py` copies it
byte-for-byte next to the plugin and into the package. The plugin imports it by adding its
own directory to `sys.path` (not a relative import) because PCM install directories have
dash/dot names that aren't valid Python modules. If you change the core, re-run
`build_pcm_package.py` before committing.

## Requirements

Just KiCad — the plugin uses only the Python standard library and wx, both bundled with
KiCad. Nothing to `pip install`.
