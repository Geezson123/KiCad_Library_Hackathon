"""HackLib Sync — KiCad action plugin (PCB editor).

Adds a toolbar button that pulls the latest library bundle from the HackLib server and
extracts it into the local KiCad library folder — the same thing sync.bat does, but from
inside KiCad.

The download/extract logic lives in the shared ``hacklib_core`` module (canonical copy in
client/hacklib_core.py, copied next to this file at build time) so the CLI client and this
plugin share one implementation. We import it by adding this file's directory to sys.path
and importing by plain name, NOT with a relative import: KiCad's Plugin & Content Manager
installs packages into directories whose names contain dashes/dots (invalid Python module
names), which would break relative imports.

Uses only the standard library + wx, both bundled with KiCad — nothing to pip install.

Configuration (resolved in this order):
  * server URL : hacklib_config.json next to this file; else prompt once and save.
  * local dir  : hacklib_config.json; else the HACKLIB_DIR env var KiCad exports
                 (Preferences -> Configure Paths); else ~/Documents/KiCad_HackLib.
"""
import os
import sys

import pcbnew

try:
    import wx
    HAVE_WX = True
except Exception:  # pragma: no cover - wx is always present inside KiCad
    HAVE_WX = False

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PLUGIN_DIR, "hacklib_config.json")

# Import the shared sync core that ships alongside this file (build_pcm_package.py copies
# client/hacklib_core.py in). We add the plugin's own directory to sys.path and import by
# plain name because PCM installs the plugin into a directory whose name contains
# dashes/dots (not a valid Python package), which rules out relative imports.
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)
try:
    import hacklib_core as core
except Exception:  # pragma: no cover
    core = None


_DialogBase = wx.Dialog if HAVE_WX else object


class _ReloadHintDialog(_DialogBase):
    """Small dialog shown after a successful sync, explaining how to reload libraries."""

    def __init__(self, count, local_dir):
        super().__init__(None, title="HackLib Sync", style=wx.DEFAULT_DIALOG_STYLE)
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(panel, label="Synced %d files." % count)
        font = heading.GetFont()
        font.MakeBold()
        font.SetPointSize(font.GetPointSize() + 1)
        heading.SetFont(font)

        body = wx.StaticText(panel, label=(
            "Saved to:\n%s\n\n"
            "KiCad caches libraries, so reload to see new/updated parts:\n\n"
            "  1. Schematic Editor → press 'A' to open the Symbol Chooser.\n"
            "  2. Click the circular ↻ Refresh button (top of the library tree).\n\n"
            "If parts still don't appear (e.g. the .kicad_dbl changed), restart KiCad."
            % local_dir
        ))

        outer.Add(heading, 0, wx.ALL, 14)
        outer.Add(body, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)

        btns = self.CreateButtonSizer(wx.OK)
        outer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        panel.SetSizer(outer)
        outer.Fit(panel)
        self.Fit()
        self.CentreOnScreen()


class HackLibSyncPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "HackLib: Sync Library"
        self.category = "HackLib"
        self.description = "Download the latest shared KiCad library from the HackLib server."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(PLUGIN_DIR, "icon.png")
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        if core is None:
            self._error("hacklib_core.py is missing next to the plugin. Reinstall the "
                        "plugin package (or run build_pcm_package.py).")
            return

        cfg = core.load_config(CONFIG_PATH)
        server_url = (cfg.get("server_url") or "").strip()
        local_dir = core.resolve_local_dir(cfg)

        # First run (or unconfigured): ask for the server URL and remember it.
        if not server_url and HAVE_WX:
            dlg = wx.TextEntryDialog(
                None, "HackLib server URL:", "HackLib Sync (first-time setup)",
                "http://YOUR_VPS_IP:8000",
            )
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            server_url = dlg.GetValue().strip()
            dlg.Destroy()

        if not server_url:
            self._error("No server URL configured.\nCreate hacklib_config.json next to the "
                        "plugin, or run it again to enter the URL.")
            return

        cfg["server_url"] = server_url
        if not cfg.get("local_dir"):
            cfg["local_dir"] = local_dir
        core.save_config(CONFIG_PATH, cfg)

        try:
            count = core.sync(server_url, local_dir)
        except Exception as exc:  # noqa: BLE001 - report any failure to the user
            self._error("Sync failed:\n%s\n\nServer: %s" % (exc, server_url))
            return

        if HAVE_WX:
            dlg = _ReloadHintDialog(count, local_dir)
            dlg.ShowModal()
            dlg.Destroy()
        else:
            print("Synced %d files to %s" % (count, local_dir))

    def _error(self, text):
        if HAVE_WX:
            wx.MessageBox(text, "HackLib Sync", wx.ICON_ERROR | wx.OK)
        else:
            print("ERROR:", text)


HackLibSyncPlugin().register()
