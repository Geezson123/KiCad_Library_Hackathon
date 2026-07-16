#!/usr/bin/env python3
"""HackLib sync client (CLI) — thin wrapper around hacklib_core.

Standard-library only, so the demo laptop needs nothing beyond Python. Configure by
copying ``client_config.example.json`` to ``client_config.json`` and editing the two
values, or pass them on the command line:

    python sync_client.py --server http://VPS_IP:8000 --dir "%USERPROFILE%\\Documents\\KiCad_HackLib"

After a successful sync, refresh the HackLib database library in KiCad's Symbol Chooser
(or restart KiCad) to see new parts.
"""
import argparse
import os
import sys

import hacklib_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "client_config.json")


def main():
    cfg = core.load_config(CONFIG_PATH)

    ap = argparse.ArgumentParser(description="Sync the HackLib KiCad library.")
    ap.add_argument("--server", dest="server_url", default=cfg.get("server_url", ""),
                    help="Base URL of the HackLib server, e.g. http://10.0.0.5:8000")
    ap.add_argument("--dir", dest="local_dir", default="",
                    help="Local folder to sync into (overrides config / HACKLIB_DIR)")
    args = ap.parse_args()

    server = args.server_url.rstrip("/")
    if args.local_dir:
        local = os.path.expandvars(os.path.expanduser(args.local_dir))
    else:
        local = core.resolve_local_dir(cfg)

    if not server or not local:
        sys.exit(
            "Missing configuration. Create client_config.json (copy the .example) "
            "or pass --server and --dir."
        )

    print(f"Syncing from {server}/api/bundle")
    print(f"          -> {local}")
    try:
        count = core.sync(server, local)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"ERROR: sync failed: {exc}")

    print(f"OK - extracted {count} files.")
    print("\nDone. In KiCad: refresh the HackLib database library (Symbol Chooser) "
          "or restart KiCad to see new parts.")


if __name__ == "__main__":
    main()
