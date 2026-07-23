#!/usr/bin/env python3
"""Assemble the KiCad PCM (Plugin & Content Manager) archive for LuGroupLib Sync.

Builds ``dist/LuGroupLib-Sync-<version>.zip`` with the layout KiCad expects:

    metadata.json
    plugins/__init__.py                 (the plugin, copied from lugrouplib_sync/)
    plugins/icon.png                    (24x24 toolbar icon)
    plugins/lugrouplib_config.example.json
    resources/icon.png                  (64x64 package icon shown in the PCM)

Install it in KiCad via  Plugin & Content Manager -> Install from File…

The plugin source in lugrouplib_sync/ stays the single source of truth; this script only
packages it. Run:  python build_pcm_package.py
"""
import hashlib
import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "lugrouplib_sync")
PCM = os.path.join(HERE, "pcm")
DIST = os.path.join(HERE, "dist")

# The shared sync core lives canonically in client/. Copy it next to the plugin so both
# the manual-install folder and the packaged archive carry an identical implementation.
CANONICAL_CORE = os.path.join(REPO_ROOT, "client", "lugrouplib_core.py")
PLUGIN_CORE = os.path.join(SRC, "lugrouplib_core.py")

# (path inside archive, source file on disk)
FILES = [
    ("metadata.json", os.path.join(PCM, "metadata.json")),
    ("plugins/__init__.py", os.path.join(SRC, "__init__.py")),
    ("plugins/lugrouplib_core.py", PLUGIN_CORE),
    ("plugins/icon.png", os.path.join(SRC, "icon.png")),
    ("plugins/lugrouplib_config.example.json", os.path.join(SRC, "lugrouplib_config.example.json")),
    ("resources/icon.png", os.path.join(PCM, "resources", "icon.png")),
]


def main():
    # Keep the plugin's core byte-for-byte identical to the canonical client copy.
    shutil.copyfile(CANONICAL_CORE, PLUGIN_CORE)
    print(f"Synced core: {CANONICAL_CORE} -> {PLUGIN_CORE}")

    with open(os.path.join(PCM, "metadata.json"), "r", encoding="utf-8") as fh:
        version = json.load(fh)["versions"][0]["version"]

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"LuGroupLib-Sync-{version}.zip")

    missing = [src for _, src in FILES if not os.path.exists(src)]
    if missing:
        raise SystemExit("Missing source files:\n  " + "\n  ".join(missing))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, src in FILES:
            zf.write(src, arc)

    data = open(out, "rb").read()
    print(f"Built {out}")
    print(f"  size          : {len(data)} bytes")
    print(f"  download_sha256: {hashlib.sha256(data).hexdigest()}")
    print("  contents      :")
    with zipfile.ZipFile(out) as zf:
        for n in zf.namelist():
            print("    " + n)


if __name__ == "__main__":
    main()
