#!/usr/bin/env python3
"""One-time LuGroupLib setup for a lab machine. Windows, macOS and Linux.

    python install.py                 # interactive
    python install.py --dry-run       # show what would change, touch nothing
    python install.py --server URL --token TOKEN

Does everything in docs/SETUP_KICAD.md except installing the ODBC driver, which it
detects and gives instructions for rather than downloading and running an installer
on your behalf.

Safe to re-run: every step is idempotent, and any KiCad file it edits is copied to
``<name>.lugrouplib-bak`` first.
"""
import argparse
import os
import sys

import kicad_setup
import lugrouplib_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "client_config.json")

STEP = 0


def step(title):
    global STEP
    STEP += 1
    print(f"\n[{STEP}] {title}")


def ok(msg):
    print(f"    OK   {msg}")


def warn(msg):
    print(f"    WARN {msg}")


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"    {prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def main():
    ap = argparse.ArgumentParser(description="Set up LuGroupLib for KiCad.")
    ap.add_argument("--server", default="", help="LuGroupLib server URL")
    ap.add_argument("--token", default="", help="sync token from the server's /tokens page")
    ap.add_argument("--dir", dest="local_dir", default="", help="local library folder")
    ap.add_argument("--kicad-version", default="", help="e.g. 9.0 (default: newest found)")
    ap.add_argument("--dry-run", action="store_true", help="report changes, make none")
    ap.add_argument("--skip-sync", action="store_true", help="configure only, do not download")
    ap.add_argument("--config-root", default="", help="override KiCad's config directory (testing)")
    args = ap.parse_args()

    print("=" * 64)
    print("  LuGroupLib installer" + ("  (DRY RUN - nothing will be changed)" if args.dry_run else ""))
    print("=" * 64)

    cfg = core.load_config(CONFIG_PATH)

    # --- 1. KiCad must be closed -------------------------------------------------
    step("Checking KiCad is closed")
    if kicad_setup.kicad_is_running():
        print("\n    KiCad appears to be running. It loads its configuration at startup\n"
              "    and writes it back when it exits, so changes made now would be\n"
              "    silently thrown away. Close KiCad and run this again.")
        return 1
    ok("KiCad is not running")

    # --- 2. find KiCad -----------------------------------------------------------
    step("Locating KiCad")
    root = args.config_root or kicad_setup.config_root()
    versions = kicad_setup.installed_versions(root)
    version = kicad_setup.pick_version(versions, args.kicad_version or None)
    config_dir = os.path.join(root, version)
    ok(f"KiCad {version}  ({config_dir})")
    if len(versions) > 1:
        warn(f"also found {', '.join(v for v in versions if v != version)}"
             f" - re-run with --kicad-version to configure those too")

    # --- 3. server details -------------------------------------------------------
    step("Server details")
    server = args.server or cfg.get("server_url") or ""
    if not server:
        server = ask("LuGroupLib server URL", "http://localhost:8000")
    server = server.rstrip("/")

    token = args.token or cfg.get("token") or ""
    if not token:
        print(f"    Create a sync token at {server}/tokens (sign in with Slack first).")
        token = ask("Sync token")
    if not token:
        warn("no token given - the first sync will fail until you add one")
    ok(f"server {server}")

    local_dir = args.local_dir or core.resolve_local_dir(cfg)
    local_dir = os.path.expandvars(os.path.expanduser(local_dir))
    ok(f"library folder {local_dir}")

    # --- 4. save client config ---------------------------------------------------
    step("Saving client configuration")
    cfg.update({"server_url": server, "token": token, "local_dir": local_dir})
    if args.dry_run:
        ok(f"would write {CONFIG_PATH}")
    else:
        core.save_config(CONFIG_PATH, cfg)
        ok(f"wrote {CONFIG_PATH}")

    # --- 5. first sync -----------------------------------------------------------
    step("Downloading the library")
    if args.dry_run or args.skip_sync:
        ok(f"would sync {server}/api/bundle -> {local_dir}")
    else:
        try:
            result = core.sync(server, local_dir, token=token)
            ok(f"{result['extracted']} files downloaded"
               + (f", {result['deleted']} stale removed" if result["deleted"] else ""))
        except core.AuthError as exc:
            warn(str(exc))
            warn("configuration will continue; re-run after fixing the token")
        except Exception as exc:  # noqa: BLE001
            warn(f"sync failed: {exc}")
            warn("configuration will continue; run sync.bat once the server is reachable")

    # --- 6. KiCad path variables -------------------------------------------------
    step("Setting KiCad path variables")
    changed = kicad_setup.set_env_vars(config_dir, local_dir, args.dry_run)
    if changed:
        for key, value in changed.items():
            ok(f"{'would set' if args.dry_run else 'set'} {key} = {value}")
    else:
        ok("already correct")

    # --- 7. library tables -------------------------------------------------------
    step("Registering libraries with KiCad")
    for label, outcome in kicad_setup.register_libraries(config_dir, args.dry_run):
        ok(f"{label}: {outcome}")

    # --- 8. ODBC driver ----------------------------------------------------------
    step("Checking the SQLite ODBC driver")
    found, detail = kicad_setup.odbc_driver_present()
    if found:
        ok(f"'{kicad_setup.ODBC_DRIVER_NAME}' is installed")
    else:
        warn("the SQLite ODBC driver is MISSING - KiCad will show the library but no parts")
        warn(f"drivers found: {detail}")
        print()
        for line in kicad_setup.odbc_instructions().splitlines():
            print(f"    {line}")

    # --- done --------------------------------------------------------------------
    print("\n" + "=" * 64)
    if args.dry_run:
        print("  Dry run complete - nothing was changed.")
    else:
        print("  Setup complete.")
        print(f"\n  Open KiCad, press 'A' in the schematic editor, and look for the\n"
              f"  '{kicad_setup.DB_NICKNAME}' library - each sub-group appears as its own\n"
              f"  entry underneath it.\n")
        print("  From now on, syncing is just sync.bat (or the toolbar button in the\n"
              "  PCB editor if you install the plugin).")
        if not found:
            print("\n  Install the ODBC driver first, or the library will load empty.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
