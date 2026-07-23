"""Shared LuGroupLib sync core — the single source of truth for download + extract.

Standard library only, no KiCad/wx/CLI specifics, so it can be reused by both:
  * client/sync_client.py         (the double-click CLI sync)
  * the KiCad plugin              (kicad_plugin/lugrouplib_sync/__init__.py)

This file is CANONICAL here in client/. build_pcm_package.py copies it verbatim into
the plugin so there is exactly one implementation to maintain.
"""
import json
import os
import tempfile
import urllib.error
import urllib.request
import zipfile


def load_config(config_path):
    """Read a {server_url, local_dir, token} JSON config, tolerating a missing/broken file."""
    cfg = {"server_url": "", "local_dir": "", "token": ""}
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


def resolve_local_dir(cfg, env_var="LUGROUPLIB_DIR"):
    """Where to sync into: explicit config, else the env var KiCad exports, else default."""
    if cfg.get("local_dir"):
        return os.path.expandvars(os.path.expanduser(cfg["local_dir"]))
    env = os.environ.get(env_var)
    if env:
        return os.path.expandvars(env)
    return os.path.join(os.path.expanduser("~"), "Documents", "KiCad_LuGroupLib")


# Subdirectories we fully mirror: files here that are no longer on the server are
# deleted locally, so deleting a part on the server removes its footprint/3D-model files
# from every synced machine. Restricted to these two managed dirs so a mis-pointed
# local_dir can never cause us to delete unrelated files.
_MIRRORED_DIRS = ("footprints", "3dmodels")


class AuthError(Exception):
    """The server rejected our token (or we did not send one)."""


def sync(server_url, local_dir, timeout=30, token=""):
    """Download /api/bundle from server_url and extract into local_dir, mirroring.

    Extracts the bundle (adding/updating files) and prunes stale files under the mirrored
    directories so server-side deletions propagate. Returns
    ``{"extracted": int, "deleted": int}``. Raises AuthError on 401, or the underlying
    exception on other network/zip errors.

    ``token`` is a sync token from the server's /tokens page, sent as a bearer header.
    """
    url = server_url.rstrip("/") + "/api/bundle"
    os.makedirs(local_dir, exist_ok=True)
    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise AuthError(
                    "the server rejected your sync token. Create one at "
                    + server_url.rstrip("/") + "/tokens and put it in your config."
                )
            raise
        with resp, open(tmp_zip, "wb") as out:
            out.write(resp.read())
        with zipfile.ZipFile(tmp_zip) as zf:
            members = [m for m in zf.namelist() if not m.endswith("/")]
            keep = {os.path.normpath(m) for m in members}
            zf.extractall(local_dir)
        deleted = _prune_stale(local_dir, keep)
        return {"extracted": len(members), "deleted": deleted}
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass


def _prune_stale(local_dir, keep):
    """Delete files under the mirrored dirs that are not in ``keep`` (bundle-relative,
    normpath'd). Returns the number of files removed."""
    deleted = 0
    for sub in _MIRRORED_DIRS:
        base = os.path.join(local_dir, sub)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.normpath(os.path.relpath(full, local_dir))
                if rel not in keep:
                    try:
                        os.remove(full)
                        deleted += 1
                    except OSError:
                        pass
    return deleted
