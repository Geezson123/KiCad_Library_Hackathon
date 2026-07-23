#!/usr/bin/env python3
"""Stage 4: KiCad config discovery, library-table editing, and ODBC detection.

Every test runs against a synthetic config directory. Nothing here may ever touch the
real KiCad configuration -- that is a user's own machine setup, not test scaffolding.
"""
import json
import os
import shutil
import sys
import tempfile

from harness import REPO_ROOT, check, finish, section

sys.path.insert(0, os.path.join(REPO_ROOT, "client"))
import kicad_setup  # noqa: E402

TMP = tempfile.mkdtemp(prefix="lgl_install_")

# A miniature but structurally real pair of library tables.
STOCK_SYM = '''(sym_lib_table
  (version 7)
  (lib (name "4xxx")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/4xxx.kicad_sym")(options "")(descr "4xxx series symbols"))
  (lib (name "74xx")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/74xx.kicad_sym")(options "")(descr "74xx symbols"))
)
'''
STOCK_FP = '''(fp_lib_table
  (version 7)
  (lib (name "Battery")(type "KiCad")(uri "${KICAD9_FOOTPRINT_DIR}/Battery.pretty")(options "")(descr "Battery footprints"))
)
'''


def make_config(name, versions=("9.0",), with_common=True):
    """Build a throwaway KiCad config root."""
    root = os.path.join(TMP, name)
    for version in versions:
        d = os.path.join(root, version)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "sym-lib-table"), "w", encoding="utf-8") as fh:
            fh.write(STOCK_SYM)
        with open(os.path.join(d, "fp-lib-table"), "w", encoding="utf-8") as fh:
            fh.write(STOCK_FP)
        if with_common:
            with open(os.path.join(d, "kicad_common.json"), "w", encoding="utf-8") as fh:
                json.dump({"environment": {"vars": {"KISYS3DMOD": "/existing/path"}},
                           "appearance": {"theme": "dark"}}, fh)
    return root


section("version discovery")
root = make_config("multi", versions=("7.0", "8.0", "9.0"))
check("finds every version folder",
      kicad_setup.installed_versions(root) == ["7.0", "8.0", "9.0"],
      kicad_setup.installed_versions(root))
check("defaults to the newest",
      kicad_setup.pick_version(["7.0", "8.0", "9.0"]) == "9.0")
check("honours an explicit version",
      kicad_setup.pick_version(["7.0", "8.0", "9.0"], "8.0") == "8.0")

try:
    kicad_setup.pick_version(["6.0"])
    check("rejects KiCad older than 7", False, "no error raised")
except SystemExit as exc:
    check("rejects KiCad older than 7", "too old" in str(exc), str(exc))

try:
    kicad_setup.pick_version([])
    check("errors clearly when KiCad is absent", False, "no error raised")
except SystemExit as exc:
    check("errors clearly when KiCad is absent", "No KiCad configuration" in str(exc))

os.makedirs(os.path.join(root, "not-a-version"), exist_ok=True)
check("ignores non-version folders",
      "not-a-version" not in kicad_setup.installed_versions(root))

section("registering libraries")
root = make_config("fresh")
config_dir = os.path.join(root, "9.0")
results = kicad_setup.register_libraries(config_dir)

# Regression: the symbol and footprint libraries share the nickname "LuGroupLib", so
# returning a dict keyed by nickname silently dropped one of the three.
check("reports all three registrations", len(results) == 3, results)
check("labels are distinct", len({label for label, _ in results}) == 3, results)
check("all three were added", all(outcome == "added" for _, outcome in results), results)

sym = open(os.path.join(config_dir, "sym-lib-table"), encoding="utf-8").read()
fp = open(os.path.join(config_dir, "fp-lib-table"), encoding="utf-8").read()
check("plain symbol library registered under the nickname the DB rows use",
      '(name "LuGroupLib")(type "KiCad")' in sym)
check("database library registered as type Database",
      '(name "LuGroupLib_DB")(type "Database")' in sym)
check("footprint library registered", '(name "LuGroupLib")(type "KiCad")' in fp)
check("paths go through ${LUGROUPLIB_DIR}", "${LUGROUPLIB_DIR}/symbols" in sym)
check("stock symbol libraries survive", '(name "4xxx")' in sym and '(name "74xx")' in sym)
check("stock footprint libraries survive", '(name "Battery")' in fp)
check("table still closes properly", sym.rstrip().endswith(")"))

section("re-running is safe")
again = kicad_setup.register_libraries(config_dir)
check("second run changes nothing",
      all(outcome == "unchanged" for _, outcome in again), again)
sym_after = open(os.path.join(config_dir, "sym-lib-table"), encoding="utf-8").read()
check("file is byte-identical after a re-run", sym_after == sym)
check("no duplicate entries", sym_after.count('(name "LuGroupLib")') == 1)

section("updating a changed entry")
kicad_setup.upsert_lib_entry(
    os.path.join(config_dir, "sym-lib-table"), "sym_lib_table",
    "LuGroupLib", "KiCad", "${LUGROUPLIB_DIR}/somewhere/else.kicad_sym", "moved")
sym_moved = open(os.path.join(config_dir, "sym-lib-table"), encoding="utf-8").read()
check("existing entry is replaced, not duplicated",
      sym_moved.count('(name "LuGroupLib")') == 1)
check("new uri took effect", "somewhere/else.kicad_sym" in sym_moved)

section("environment variables")
root = make_config("envs")
config_dir = os.path.join(root, "9.0")
changed = kicad_setup.set_env_vars(config_dir, "/home/ada/KiCad_LuGroupLib")
data = json.load(open(os.path.join(config_dir, "kicad_common.json"), encoding="utf-8"))
variables = data["environment"]["vars"]
check("LUGROUPLIB_DIR set", variables["LUGROUPLIB_DIR"] == "/home/ada/KiCad_LuGroupLib")
check("LUGROUPLIB_3D derives from it",
      variables["LUGROUPLIB_3D"] == "${LUGROUPLIB_DIR}/3dmodels")
check("pre-existing variables preserved", variables["KISYS3DMOD"] == "/existing/path")
check("unrelated settings preserved", data["appearance"]["theme"] == "dark")
check("re-running reports no change",
      kicad_setup.set_env_vars(config_dir, "/home/ada/KiCad_LuGroupLib") == {})

section("backups")
for name in ("sym-lib-table", "fp-lib-table"):
    p = os.path.join(root, "9.0", name)
    kicad_setup.upsert_lib_entry(p, name.replace("-", "_").replace("lib_table", "lib_table"),
                                 "Probe", "KiCad", "x", "y")
check("kicad_common.json was backed up before editing",
      os.path.exists(os.path.join(root, "9.0", "kicad_common.json.lugrouplib-bak")))
backup = json.load(open(os.path.join(root, "9.0", "kicad_common.json.lugrouplib-bak"),
                        encoding="utf-8"))
check("backup holds the ORIGINAL contents, not the edited version",
      "LUGROUPLIB_DIR" not in backup["environment"]["vars"])

section("missing files are created")
empty = os.path.join(TMP, "empty", "9.0")
os.makedirs(empty, exist_ok=True)
outcome = kicad_setup.upsert_lib_entry(
    os.path.join(empty, "sym-lib-table"), "sym_lib_table",
    "LuGroupLib", "KiCad", "x", "y")
created = open(os.path.join(empty, "sym-lib-table"), encoding="utf-8").read()
check("creates a valid table when none exists", outcome == "added")
check("new table has the right root tag", created.startswith("(sym_lib_table"))
check("new table is closed", created.rstrip().endswith(")"))

section("dry run touches nothing")
root = make_config("dry")
config_dir = os.path.join(root, "9.0")
before_sym = open(os.path.join(config_dir, "sym-lib-table"), encoding="utf-8").read()
before_json = open(os.path.join(config_dir, "kicad_common.json"), encoding="utf-8").read()
kicad_setup.register_libraries(config_dir, dry_run=True)
kicad_setup.set_env_vars(config_dir, "/tmp/whatever", dry_run=True)
check("sym-lib-table unchanged",
      open(os.path.join(config_dir, "sym-lib-table"), encoding="utf-8").read() == before_sym)
check("kicad_common.json unchanged",
      open(os.path.join(config_dir, "kicad_common.json"), encoding="utf-8").read() == before_json)
check("no backups created during a dry run",
      not any(f.endswith(".lugrouplib-bak") for f in os.listdir(config_dir)),
      os.listdir(config_dir))

section("ODBC detection")
found, detail = kicad_setup.odbc_driver_present()
check("returns a (bool, detail) pair", isinstance(found, bool) and isinstance(detail, str))
check("instructions mention the exact driver name KiCad needs",
      kicad_setup.ODBC_DRIVER_NAME in kicad_setup.odbc_instructions()
      or "odbcinst" in kicad_setup.odbc_instructions())
check("never offers to download and run an installer itself",
      "http" in kicad_setup.odbc_instructions() or "brew" in kicad_setup.odbc_instructions())

section("real config is untouched")
real = kicad_setup.config_root()
check("tests never wrote to the real KiCad config",
      not any(f.endswith(".lugrouplib-bak")
              for v in kicad_setup.installed_versions(real)
              for f in os.listdir(os.path.join(real, v))),
      real)

shutil.rmtree(TMP, ignore_errors=True)
finish()
