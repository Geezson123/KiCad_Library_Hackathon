"""Shared LuGroupLib sync core — the single source of truth for download + extract.

Standard library only, no KiCad/wx/CLI specifics, so it can be reused by both:
  * client/sync_client.py         (the double-click CLI sync)
  * the KiCad plugin              (kicad_plugin/lugrouplib_sync/__init__.py)

This file is CANONICAL here in client/. build_pcm_package.py copies it verbatim into
the plugin so there is exactly one implementation to maintain.
"""
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
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


class _NoManifest(Exception):
    """Server has no /api/manifest -- fall back to downloading the whole bundle."""


# Above this share of files needing transfer -- a first install, most obviously -- one
# bundle request beats many small ones, because per-request overhead dominates. Below
# it, fetching individually avoids shipping the whole library to add one resistor.
_BUNDLE_THRESHOLD = 0.6

# ...but only once there are enough files for that overhead to matter. Seeding a small
# library file-by-file is fine, and skipping the zip saves the server building one.
_BUNDLE_MIN_FILES = 8

_CHUNK = 1 << 20


def should_use_bundle(transfers, total):
    """Whether to grab the whole zip instead of ``transfers`` individual files.

    Split out and named so the policy is explicit and testable on its own, rather than
    something you can only observe by varying the size of a real library.
    """
    return transfers >= _BUNDLE_MIN_FILES and transfers > total * _BUNDLE_THRESHOLD


def _request(url, token):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    return req


def _open(url, token, timeout, server_url=""):
    """urlopen with bearer auth, translating 401 into a useful AuthError."""
    try:
        return urllib.request.urlopen(_request(url, token), timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError(
                "the server rejected your sync token. Create one at "
                + (server_url or url).rstrip("/") + "/tokens and put it in your config."
            )
        raise


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_path(local_dir, rel):
    return os.path.join(local_dir, rel.replace("/", os.sep))


def _fetch_manifest(server, token, timeout):
    try:
        with _open(server + "/api/manifest", token, timeout, server) as resp:
            return json.loads(resp.read().decode("utf-8"))["files"]
    except AuthError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise _NoManifest()  # older server, still has /api/bundle
        raise
    except (ValueError, KeyError):
        raise _NoManifest()  # not the JSON we expected


def _plan(local_dir, remote):
    """Split the manifest into what is missing, stale, and already correct.

    Local files are hashed rather than trusting a remembered state file: it costs a
    little I/O but means a hand-edited or half-deleted library repairs itself instead
    of silently staying wrong.
    """
    added, updated, unchanged = [], [], []
    for rel, digest in remote.items():
        path = _local_path(local_dir, rel)
        if not os.path.isfile(path):
            added.append(rel)
        elif _sha256(path) != digest:
            updated.append(rel)
        else:
            unchanged.append(rel)
    return {"added": added, "updated": updated, "unchanged": unchanged}


def _download(server, local_dir, rel, token, timeout):
    """Fetch one file, writing via a temp file so an interrupted sync cannot leave a
    truncated .kicad_sym or 3D model in place."""
    dest = _local_path(local_dir, rel)
    os.makedirs(os.path.dirname(dest) or local_dir, exist_ok=True)
    url = server + "/api/file/" + urllib.parse.quote(rel)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest) or local_dir, suffix=".part")
    os.close(fd)
    try:
        with _open(url, token, timeout, server) as resp, open(tmp, "wb") as out:
            shutil.copyfileobj(resp, out, _CHUNK)
        size = os.path.getsize(tmp)
        os.replace(tmp, dest)
        return size
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def sync(server_url, local_dir, timeout=30, token="", full=False):
    """Bring local_dir in step with the server. Returns a summary dict:

        {"mode": "incremental"|"bundle", "added", "updated", "deleted",
         "unchanged", "bytes"}

    Fetches the manifest and transfers only what changed. Falls back to the whole
    bundle zip when most of the library is missing (a first install), or when talking
    to a server old enough not to have /api/manifest. Pass ``full=True`` to force the
    bundle. Raises AuthError on 401.
    """
    server = server_url.rstrip("/")
    os.makedirs(local_dir, exist_ok=True)

    if not full:
        try:
            remote = _fetch_manifest(server, token, timeout)
        except _NoManifest:
            remote = None
        if remote:
            plan = _plan(local_dir, remote)
            transfers = len(plan["added"]) + len(plan["updated"])
            if not should_use_bundle(transfers, len(remote)):
                return _sync_incremental(server, local_dir, token, timeout, plan, remote)

    return _sync_bundle(server, local_dir, token, timeout)


def _sync_incremental(server, local_dir, token, timeout, plan, remote):
    transferred = 0
    for rel in plan["added"] + plan["updated"]:
        transferred += _download(server, local_dir, rel, token, timeout)
    keep = {os.path.normpath(rel.replace("/", os.sep)) for rel in remote}
    return {
        "mode": "incremental",
        "added": len(plan["added"]),
        "updated": len(plan["updated"]),
        "unchanged": len(plan["unchanged"]),
        "deleted": _prune_stale(local_dir, keep),
        "bytes": transferred,
    }


def _sync_bundle(server, local_dir, token, timeout):
    """Download and extract the whole library as one zip."""
    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        with _open(server + "/api/bundle", token, timeout, server) as resp, \
                open(tmp_zip, "wb") as out:
            shutil.copyfileobj(resp, out, _CHUNK)
        size = os.path.getsize(tmp_zip)
        with zipfile.ZipFile(tmp_zip) as zf:
            members = [m for m in zf.namelist() if not m.endswith("/")]
            keep = {os.path.normpath(m) for m in members}
            zf.extractall(local_dir)
        return {
            "mode": "bundle",
            "added": len(members),
            "updated": 0,
            "unchanged": 0,
            "deleted": _prune_stale(local_dir, keep),
            "bytes": size,
        }
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def describe(result):
    """One-line summary of a sync, shared by the CLI and the KiCad plugin.

    Reports what actually moved. The old whole-bundle sync could only report the size
    of the entire library, which meant a one-part change looked identical to a first
    install and the number told nobody anything useful.
    """
    if result["mode"] == "bundle":
        return (f"Downloaded the full library: {result['added']} files "
                f"({human_bytes(result['bytes'])})"
                + (f", {result['deleted']} stale removed" if result["deleted"] else ""))

    bits = []
    if result["added"]:
        bits.append(f"{result['added']} new")
    if result["updated"]:
        bits.append(f"{result['updated']} updated")
    if result["deleted"]:
        bits.append(f"{result['deleted']} removed")
    if not bits:
        return "Already up to date."
    return (", ".join(bits).capitalize()
            + f" ({human_bytes(result['bytes'])} transferred, "
              f"{result['unchanged']} unchanged)")


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
