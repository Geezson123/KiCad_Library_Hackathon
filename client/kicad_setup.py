"""Locate and safely edit KiCad's configuration.

Standard library only, so it runs on a fresh machine with nothing but Python.

Three things have to be registered before KiCad can see the library:

  1. ``LUGROUPLIB_DIR`` / ``LUGROUPLIB_3D`` path variables, in kicad_common.json
  2. two symbol library table entries -- the database library the user browses, and
     the plain .kicad_sym it resolves its ``symbols`` column against
  3. one footprint library table entry

The nicknames are load-bearing. Database rows store ``LuGroupLib:R_10K``, so the
*plain* symbol library must be nicknamed exactly ``LuGroupLib``; the database library
therefore takes ``LuGroupLib_DB``. Getting these backwards yields a library that loads
but whose symbols all fail to resolve.

The library tables are s-expressions, and this module appends to them as text rather
than parsing and rewriting. Same reasoning as the footprint handling in the server's
library.py: a partial re-serialisation of a file we do not fully model is a good way to
corrupt someone's configuration. We only ever add or replace whole ``(lib ...)`` lines.
"""
import json
import os
import platform
import re
import shutil
import subprocess

# Nicknames -- see the module docstring before changing either of these.
SYMBOL_NICKNAME = "LuGroupLib"
DB_NICKNAME = "LuGroupLib_DB"
FOOTPRINT_NICKNAME = "LuGroupLib"

DIR_VAR = "LUGROUPLIB_DIR"
MODEL_VAR = "LUGROUPLIB_3D"

# The exact driver name the generated .kicad_dbl connection string asks for.
ODBC_DRIVER_NAME = "SQLite3 ODBC Driver"


# ---------------------------------------------------------------------------
# locating KiCad
# ---------------------------------------------------------------------------
def config_root():
    """The directory holding KiCad's per-version configuration folders."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
        return os.path.join(base, "kicad")
    if system == "Darwin":
        return os.path.expanduser("~/Library/Preferences/kicad")
    return os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "kicad"
    )


def installed_versions(root=None):
    """Version folders present, newest last. KiCad 7+ is required for DB libraries."""
    root = root or config_root()
    if not os.path.isdir(root):
        return []
    found = []
    for name in os.listdir(root):
        if re.fullmatch(r"\d+\.\d+", name) and os.path.isdir(os.path.join(root, name)):
            found.append(name)
    return sorted(found, key=lambda v: tuple(int(p) for p in v.split(".")))


def pick_version(versions, requested=None):
    """Choose which KiCad version to configure."""
    if requested:
        if requested not in versions:
            raise SystemExit(
                f"KiCad {requested} not found. Available: {', '.join(versions) or 'none'}"
            )
        return requested
    if not versions:
        raise SystemExit(
            "No KiCad configuration found. Install KiCad 7 or newer, run it once so it "
            f"creates its config, then re-run this installer.\nLooked in: {config_root()}"
        )
    newest = versions[-1]
    if tuple(int(p) for p in newest.split(".")) < (7, 0):
        raise SystemExit(
            f"KiCad {newest} is too old -- database libraries need KiCad 7 or newer."
        )
    return newest


def kicad_is_running():
    """True if KiCad appears to be open.

    This matters: KiCad reads its configuration at startup and writes it back on exit,
    so edits made while it is running are silently discarded when the user quits.
    """
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True, text=True,
                                 timeout=15).stdout.lower()
            return any(exe in out for exe in ("kicad.exe", "eeschema.exe", "pcbnew.exe"))
        out = subprocess.run(["ps", "-A"], capture_output=True, text=True,
                             timeout=15).stdout.lower()
        return any(name in out for name in ("kicad", "eeschema", "pcbnew"))
    except Exception:
        return False  # detection is a convenience; never block the install on it


# ---------------------------------------------------------------------------
# ODBC
# ---------------------------------------------------------------------------
def odbc_driver_present():
    """Whether the SQLite ODBC driver KiCad needs is installed.

    Returns (found: bool, detail: str). ``detail`` lists what was found instead, which
    is usually the useful part -- a 32-bit-only install is a common near-miss.
    """
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ODBC\ODBCINST.INI\ODBC Drivers"
            )
            drivers = []
            i = 0
            while True:
                try:
                    drivers.append(winreg.EnumValue(key, i)[0])
                    i += 1
                except OSError:
                    break
            return ODBC_DRIVER_NAME in drivers, ", ".join(drivers) or "none"
        except Exception as exc:  # noqa: BLE001
            return False, f"could not read the ODBC registry ({exc})"
    try:
        out = subprocess.run(["odbcinst", "-q", "-d"], capture_output=True, text=True,
                             timeout=15).stdout
        names = [line.strip("[]\n ") for line in out.splitlines() if line.strip()]
        return any("sqlite" in n.lower() for n in names), ", ".join(names) or "none"
    except FileNotFoundError:
        return False, "unixODBC is not installed (no odbcinst on PATH)"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def odbc_instructions():
    """Platform-specific setup text. We never download or run an installer ourselves."""
    system = platform.system()
    if system == "Windows":
        return (
            "Install the 64-bit SQLite ODBC driver:\n"
            "  1. Download sqliteodbc_w64.exe from http://www.ch-werner.de/sqliteodbc/\n"
            "  2. Run it (Next -> Next -> Finish)\n"
            "  3. Check 'ODBC Data Source Administrator (64-bit)' -> Drivers tab shows\n"
            f"     exactly: {ODBC_DRIVER_NAME}\n"
            "KiCad is 64-bit, so a 32-bit-only driver will not work."
        )
    if system == "Darwin":
        return (
            "Install unixODBC and a SQLite driver:\n"
            "  brew install unixodbc sqliteodbc\n"
            "Then confirm the driver name:\n"
            "  odbcinst -q -d\n"
            f"If it is not '{ODBC_DRIVER_NAME}', edit the connection_string in\n"
            "LuGroupLib.kicad_dbl to match. The file uses ${CWD}, so no paths change."
        )
    return (
        "Install unixODBC and the SQLite driver via your package manager, e.g.\n"
        "  sudo apt install unixodbc libsqliteodbc\n"
        "Then run 'odbcinst -q -d' and, if the name differs, update the\n"
        "connection_string in LuGroupLib.kicad_dbl to match."
    )


# ---------------------------------------------------------------------------
# editing config files
# ---------------------------------------------------------------------------
def backup(path):
    """Copy path to path.lugrouplib-bak once, before we first modify it."""
    if os.path.exists(path):
        dest = path + ".lugrouplib-bak"
        if not os.path.exists(dest):
            shutil.copyfile(path, dest)
            return dest
    return None


def set_env_vars(config_dir, local_dir, dry_run=False):
    """Add LUGROUPLIB_DIR / LUGROUPLIB_3D to kicad_common.json, preserving everything else."""
    path = os.path.join(config_dir, "kicad_common.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (ValueError, OSError):
            data = {}

    env = data.setdefault("environment", {})
    variables = env.setdefault("vars", {})
    wanted = {
        DIR_VAR: local_dir,
        # Expressed via DIR_VAR so moving the library folder only means changing one.
        MODEL_VAR: "${%s}/3dmodels" % DIR_VAR,
    }
    changed = {k: v for k, v in wanted.items() if variables.get(k) != v}
    if not changed or dry_run:
        return changed

    backup(path)
    variables.update(wanted)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return changed


_LIB_LINE_RE_TEMPLATE = r'^\s*\(lib\s+\(name\s+"{}"\).*$'


def _lib_line(name, lib_type, uri, descr):
    return (f'  (lib (name "{name}")(type "{lib_type}")(uri "{uri}")'
            f'(options "")(descr "{descr}"))')


def upsert_lib_entry(path, root_tag, name, lib_type, uri, descr, dry_run=False):
    """Add or replace one (lib ...) entry in a KiCad library table.

    Rewrites only the single matching line, so re-running is idempotent and every other
    entry -- including the stock KiCad libraries -- is left byte-for-byte alone.
    Returns "added", "updated" or "unchanged".
    """
    line = _lib_line(name, lib_type, uri, descr)
    if not os.path.exists(path):
        if dry_run:
            return "added"
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"({root_tag}\n  (version 7)\n{line}\n)\n")
        return "added"

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    pattern = re.compile(_LIB_LINE_RE_TEMPLATE.format(re.escape(name)), re.M)
    existing = pattern.search(text)
    if existing:
        if existing.group(0).strip() == line.strip():
            return "unchanged"
        if dry_run:
            return "updated"
        backup(path)
        text = pattern.sub(lambda _m: line, text, count=1)
        result = "updated"
    else:
        if dry_run:
            return "added"
        backup(path)
        # Insert before the final closing paren so the entry lands inside the table.
        close = text.rstrip().rfind(")")
        if close == -1:
            raise ValueError(f"{path} does not look like a KiCad library table")
        text = text[:close] + line + "\n" + text[close:]
        result = "added"

    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return result


def register_libraries(config_dir, dry_run=False):
    """Register the database library, its backing symbol library, and the footprints.

    Paths go through ${LUGROUPLIB_DIR} rather than being absolute, so a user who later
    moves the folder only has to update the one environment variable.
    """
    base = "${%s}" % DIR_VAR
    sym_table = os.path.join(config_dir, "sym-lib-table")
    fp_table = os.path.join(config_dir, "fp-lib-table")

    # A list, not a dict: the symbol and footprint libraries share the nickname
    # "LuGroupLib" (deliberately -- see the module docstring), so keying results by
    # nickname would silently drop one of them.
    return [
        # Plain symbol library FIRST: this is the nickname the database's `symbols`
        # column resolves against, so without it every part loads with a broken symbol.
        (f"{SYMBOL_NICKNAME} (symbols)", upsert_lib_entry(
            sym_table, "sym_lib_table", SYMBOL_NICKNAME, "KiCad",
            f"{base}/symbols/LuGroupLib.kicad_sym",
            "LuGroupLib shared symbols (backs the database library)", dry_run)),
        (f"{DB_NICKNAME} (database)", upsert_lib_entry(
            sym_table, "sym_lib_table", DB_NICKNAME, "Database",
            f"{base}/LuGroupLib.kicad_dbl",
            "LuGroupLib parts database (browse sub-groups here)", dry_run)),
        (f"{FOOTPRINT_NICKNAME} (footprints)", upsert_lib_entry(
            fp_table, "fp_lib_table", FOOTPRINT_NICKNAME, "KiCad",
            f"{base}/footprints/LuGroupLib.pretty",
            "LuGroupLib shared footprints", dry_run)),
    ]
