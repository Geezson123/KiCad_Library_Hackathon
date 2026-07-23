"""LuGroupLib Sync — KiCad action plugin (PCB editor).

Adds a toolbar button that pulls the latest library bundle from the LuGroupLib server and
extracts it into the local KiCad library folder — the same thing sync.bat does, but from
inside KiCad.

The download/extract logic lives in the shared ``lugrouplib_core`` module (canonical copy in
client/lugrouplib_core.py, copied next to this file at build time) so the CLI client and this
plugin share one implementation. We import it by adding this file's directory to sys.path
and importing by plain name, NOT with a relative import: KiCad's Plugin & Content Manager
installs packages into directories whose names contain dashes/dots (invalid Python module
names), which would break relative imports.

Uses only the standard library + wx, both bundled with KiCad — nothing to pip install.

Configuration (resolved in this order):
  * server URL : lugrouplib_config.json next to this file; else prompt once and save.
  * token      : lugrouplib_config.json; else prompt once and save. Create it on the
                 server's /tokens page -- one per machine, so a single laptop can be
                 revoked without disturbing the others.
  * local dir  : lugrouplib_config.json; else the LUGROUPLIB_DIR env var KiCad exports
                 (Preferences -> Configure Paths); else ~/Documents/KiCad_LuGroupLib.
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
CONFIG_PATH = os.path.join(PLUGIN_DIR, "lugrouplib_config.json")

# Import the shared sync core that ships alongside this file (build_pcm_package.py copies
# client/lugrouplib_core.py in). We add the plugin's own directory to sys.path and import by
# plain name because PCM installs the plugin into a directory whose name contains
# dashes/dots (not a valid Python package), which rules out relative imports.
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)
try:
    import lugrouplib_core as core
except Exception:  # pragma: no cover
    core = None


_DialogBase = wx.Dialog if HAVE_WX else object


class _ReloadHintDialog(_DialogBase):
    """Small dialog shown after a successful sync, explaining how to reload libraries."""

    def __init__(self, count, deleted, local_dir):
        super().__init__(None, title="LuGroupLib Sync", style=wx.DEFAULT_DIALOG_STYLE)
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        summary = "Synced %d files." % count
        if deleted:
            summary += "  Removed %d deleted file(s)." % deleted
        heading = wx.StaticText(panel, label=summary)
        font = heading.GetFont()
        font.MakeBold()
        font.SetPointSize(font.GetPointSize() + 1)
        heading.SetFont(font)

        body = wx.StaticText(panel, label=(
            "Saved to:\n%s\n\n"
            "Reload so KiCad picks up the changes:\n\n"
            "  • Symbols: open the Symbol Chooser (press 'A') and click the\n"
            "    circular ↻ Refresh button at the top of the library list.\n\n"
            "  • Footprints & 3D models: RESTART KiCad. New .kicad_mod files\n"
            "    are only read when a footprint library is (re)opened — the\n"
            "    Symbol Chooser refresh does NOT reload them.\n\n"
            "Note: the count above is the whole library, not just new parts. A\n"
            "new part adds 2 files (its footprint + 3D model); its symbol is\n"
            "merged into the shared LuGroupLib.kicad_sym."
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


class LuGroupLibSyncPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "LuGroupLib: Sync Library"
        self.category = "LuGroupLib"
        self.description = "Download the latest shared KiCad library from the LuGroupLib server."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(PLUGIN_DIR, "icon.png")
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        if core is None:
            self._error("lugrouplib_core.py is missing next to the plugin. Reinstall the "
                        "plugin package (or run build_pcm_package.py).")
            return

        cfg = core.load_config(CONFIG_PATH)
        server_url = (cfg.get("server_url") or "").strip()
        token = (cfg.get("token") or "").strip()
        local_dir = core.resolve_local_dir(cfg)

        # First run (or unconfigured): ask for the server URL and remember it.
        if not server_url and HAVE_WX:
            server_url = self._prompt(
                "LuGroupLib server URL:", "http://YOUR_VPS_IP:8000"
            )
            if server_url is None:
                return

        if not server_url:
            self._error("No server URL configured.\nCreate lugrouplib_config.json next to the "
                        "plugin, or run it again to enter the URL.")
            return

        # The server requires a token per machine; ask for it the same way.
        if not token and HAVE_WX:
            token = self._prompt(
                "Sync token (create one at %s/tokens):" % server_url.rstrip("/"), ""
            )
            if token is None:
                return

        cfg["server_url"] = server_url
        cfg["token"] = token
        if not cfg.get("local_dir"):
            cfg["local_dir"] = local_dir
        core.save_config(CONFIG_PATH, cfg)

        try:
            result = core.sync(server_url, local_dir, token=token)
        except core.AuthError as exc:
            # Clear the bad token so the next run prompts again instead of failing
            # identically forever.
            cfg["token"] = ""
            core.save_config(CONFIG_PATH, cfg)
            self._error("Sync failed: %s" % exc)
            return
        except Exception as exc:  # noqa: BLE001 - report any failure to the user
            self._error("Sync failed:\n%s\n\nServer: %s" % (exc, server_url))
            return

        if HAVE_WX:
            dlg = _ReloadHintDialog(result["extracted"], result["deleted"], local_dir)
            dlg.ShowModal()
            dlg.Destroy()
        else:
            print("Synced %d files (%d removed) to %s"
                  % (result["extracted"], result["deleted"], local_dir))

    def _prompt(self, label, default):
        """Ask for a single value. Returns the string, or None if the user cancelled."""
        dlg = wx.TextEntryDialog(
            None, label, "LuGroupLib Sync (first-time setup)", default
        )
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return None
            return dlg.GetValue().strip()
        finally:
            dlg.Destroy()

    def _error(self, text):
        if HAVE_WX:
            wx.MessageBox(text, "LuGroupLib Sync", wx.ICON_ERROR | wx.OK)
        else:
            print("ERROR:", text)


LuGroupLibSyncPlugin().register()
