"""HackLib Sync action plugin for KiCad (PCB editor).

Adds a toolbar button that pulls the latest library bundle from the HackLib server
and extracts it into the local KiCad library folder — the same thing sync.bat does,
but from inside KiCad.

Self-contained (standard library + wx, both shipped with KiCad) so it works wherever
KiCad drops it, independent of the repo's client/ folder.

Configuration (resolved in this order):
  * server URL  : hacklib_config.json next to this file; else prompt once and save.
  * local dir   : hacklib_config.json; else the HACKLIB_DIR env var KiCad exports
                  (set in Preferences -> Configure Paths); else ~/Documents/KiCad_HackLib.
"""
import json
import os
import tempfile
import urllib.request
import zipfile

import pcbnew

try:
    import wx
    HAVE_WX = True
except Exception:  # pragma: no cover - wx is always present in KiCad
    HAVE_WX = False

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PLUGIN_DIR, "hacklib_config.json")


def _load_cfg():
    cfg = {"server_url": "", "local_dir": ""}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except Exception:
            pass
    return cfg


def _save_cfg(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


def _resolve_local_dir(cfg):
    if cfg.get("local_dir"):
        return os.path.expandvars(os.path.expanduser(cfg["local_dir"]))
    env = os.environ.get("HACKLIB_DIR")
    if env:
        return os.path.expandvars(env)
    return os.path.join(os.path.expanduser("~"), "Documents", "KiCad_HackLib")


def do_sync(server_url, local_dir):
    """Download /api/bundle and extract it into local_dir. Returns file count."""
    url = server_url.rstrip("/") + "/api/bundle"
    os.makedirs(local_dir, exist_ok=True)
    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp, open(tmp_zip, "wb") as out:
            out.write(resp.read())
        with zipfile.ZipFile(tmp_zip) as zf:
            members = [m for m in zf.namelist() if not m.endswith("/")]
            zf.extractall(local_dir)
        return len(members)
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass


class HackLibSyncPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "HackLib: Sync Library"
        self.category = "HackLib"
        self.description = "Download the latest shared KiCad library from the HackLib server."
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(PLUGIN_DIR, "icon.png")
        self.dark_icon_file_name = self.icon_file_name

    def Run(self):
        cfg = _load_cfg()
        server_url = (cfg.get("server_url") or "").strip()
        local_dir = _resolve_local_dir(cfg)

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
            self._msg("No server URL configured.\nCreate hacklib_config.json next to the "
                      "plugin, or run it again to enter the URL.", error=True)
            return

        cfg["server_url"] = server_url
        if not cfg.get("local_dir"):
            cfg["local_dir"] = local_dir
        _save_cfg(cfg)

        try:
            count = do_sync(server_url, local_dir)
        except Exception as exc:  # noqa: BLE001 - report any failure to the user
            self._msg("Sync failed:\n%s\n\nServer: %s" % (exc, server_url), error=True)
            return

        self._msg(
            "Synced %d files into:\n%s\n\n"
            "Now refresh the HackLib database library in the Symbol Chooser "
            "(or restart KiCad) to see new parts." % (count, local_dir)
        )

    def _msg(self, text, error=False):
        if HAVE_WX:
            style = wx.ICON_ERROR if error else wx.ICON_INFORMATION
            wx.MessageBox(text, "HackLib Sync", style | wx.OK)
        else:
            print(text)
