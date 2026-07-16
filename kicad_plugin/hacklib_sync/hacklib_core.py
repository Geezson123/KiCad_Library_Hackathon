"""Shared HackLib sync core — the single source of truth for download + extract.

Standard library only, no KiCad/wx/CLI specifics, so it can be reused by both:
  * client/sync_client.py         (the double-click CLI sync)
  * the KiCad plugin              (kicad_plugin/hacklib_sync/__init__.py)

This file is CANONICAL here in client/. build_pcm_package.py copies it verbatim into
the plugin so there is exactly one implementation to maintain.
"""
import json
import os
import tempfile
import urllib.request
import zipfile


def load_config(config_path):
    """Read a {server_url, local_dir} JSON config, tolerating a missing/broken file."""
    cfg = {"server_url": "", "local_dir": ""}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except Exception:
            pass
    return cfg


def save_config(config_path, cfg):
    try:
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except Exception:
        pass


def resolve_local_dir(cfg, env_var="HACKLIB_DIR"):
    """Where to sync into: explicit config, else the env var KiCad exports, else default."""
    if cfg.get("local_dir"):
        return os.path.expandvars(os.path.expanduser(cfg["local_dir"]))
    env = os.environ.get(env_var)
    if env:
        return os.path.expandvars(env)
    return os.path.join(os.path.expanduser("~"), "Documents", "KiCad_HackLib")


def sync(server_url, local_dir, timeout=30):
    """Download /api/bundle from server_url and extract into local_dir.

    Returns the number of files extracted. Raises on network/zip errors so callers can
    present the failure however they like (CLI print vs. wx dialog).
    """
    url = server_url.rstrip("/") + "/api/bundle"
    os.makedirs(local_dir, exist_ok=True)
    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, open(tmp_zip, "wb") as out:
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
