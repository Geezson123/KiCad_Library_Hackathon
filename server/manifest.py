"""Content manifest for incremental sync.

The bundle zip is a fine way to seed a machine, but re-downloading every 3D model to
pick up one new resistor gets slow as the library grows. The manifest lets a client ask
"what do you have, and what does it hash to?", then fetch only what it is missing.

Hashes are cached against (size, mtime) so a manifest request does not re-read every
STEP file in the library. The cache is per-process and self-correcting: any change to a
file changes its size or mtime, which invalidates the entry.
"""
import hashlib
import os

import config

# abs_path -> ((size, mtime_ns), sha256)
_hash_cache = {}

_CHUNK = 1 << 20


def _hash_file(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    cached = _hash_cache.get(path)
    if cached and cached[0] == key:
        return cached[1]

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_CHUNK), b""):
                digest.update(chunk)
    except OSError:
        return None
    result = digest.hexdigest()
    _hash_cache[path] = (key, result)
    return result


def build():
    """Map every bundled file to its sha256, keyed by forward-slash relative path.

    Paths use '/' regardless of platform so a Windows server and a macOS client agree.
    """
    config.ensure_dirs()
    files = {}
    for root, _dirs, names in os.walk(config.LIBRARY_DIR):
        for name in names:
            full = os.path.join(root, name)
            digest = _hash_file(full)
            if digest is None:
                continue  # vanished mid-walk; the next sync will pick it up
            rel = os.path.relpath(full, config.LIBRARY_DIR).replace(os.sep, "/")
            files[rel] = digest
    return files


def resolve(rel_path):
    """Absolute path for a manifest-relative path, or None if it is not servable.

    This is the security boundary for /api/file. The client supplies the path, so it
    must be resolved and confirmed to sit inside the library directory -- otherwise
    '../../server/app.sqlite' would hand out the identity database, which is precisely
    the file the two-database split exists to keep off client machines.
    """
    base = os.path.realpath(config.LIBRARY_DIR)
    full = os.path.realpath(os.path.join(base, rel_path))
    if full != base and not full.startswith(base + os.sep):
        return None
    return full if os.path.isfile(full) else None
