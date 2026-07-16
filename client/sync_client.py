#!/usr/bin/env python3
"""HackLib sync client — downloads the library bundle and extracts it locally.

Standard-library only (urllib + zipfile), so the demo laptop needs nothing beyond
Python. Configure it by copying ``client_config.example.json`` to
``client_config.json`` and editing the two values, or pass them on the command line:

    python sync_client.py --server http://VPS_IP:8000 --dir "%USERPROFILE%\\Documents\\KiCad_HackLib"

After a successful sync, refresh the HackLib database library in KiCad's Symbol
Chooser (or restart KiCad) to see new parts.
"""
import argparse
import json
import os
import sys
import tempfile
import zipfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "client_config.json")


def load_config():
    cfg = {"server_url": "", "local_dir": ""}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))

    ap = argparse.ArgumentParser(description="Sync the HackLib KiCad library.")
    ap.add_argument("--server", dest="server_url", default=cfg["server_url"],
                    help="Base URL of the HackLib server, e.g. http://10.0.0.5:8000")
    ap.add_argument("--dir", dest="local_dir", default=cfg["local_dir"],
                    help="Local folder to sync into (the KiCad_HackLib folder)")
    args = ap.parse_args()

    server = args.server_url.rstrip("/")
    local = os.path.expandvars(os.path.expanduser(args.local_dir))
    if not server or not local:
        sys.exit(
            "Missing configuration. Create client_config.json (copy the .example) "
            "or pass --server and --dir."
        )
    return server, local


def main():
    server, local = load_config()
    url = server + "/api/bundle"
    print(f"Syncing from {url}")
    print(f"          -> {local}")

    os.makedirs(local, exist_ok=True)
    tmp_fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(tmp_fd)
    try:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp, open(tmp_zip, "wb") as out:
                out.write(resp.read())
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"ERROR: could not download bundle: {exc}")

        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                members = zf.namelist()
                zf.extractall(local)
        except zipfile.BadZipFile:
            sys.exit("ERROR: server did not return a valid zip (check the server URL).")

        files = [m for m in members if not m.endswith("/")]
        print(f"OK - extracted {len(files)} files.")
        print("\nDone. In KiCad: refresh the HackLib database library "
              "(Symbol Chooser) or restart KiCad to see new parts.")
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass


if __name__ == "__main__":
    main()
