"""Generate ``library/LuGroupLib.kicad_dbl`` from the libraries table.

The .kicad_dbl is no longer hand-edited: every library row becomes one entry in the
``libraries`` array, which KiCad shows as a **sub-library** under the single LuGroupLib
nickname. That is what gives each sub-group its own node in the Symbol Chooser while
still needing only one entry in the user's symbol library table -- adding a library is
a server-side change that reaches everyone on their next sync, with nothing to
reconfigure locally.

Two details that are load-bearing:

* ``key`` is ``slug``, not ``name``. The key ends up inside the LIB_ID of every placed
  symbol (``LuGroupLib:SubLib/<key>``), and slugs are immutable, so renaming a part can
  never orphan it in an existing schematic.
* each entry points at that library's SQL view, which already filters out deprecated
  parts, so deprecating hides a part from the chooser without breaking schematics that
  already placed it.
"""
import json
import os

import config
import db

# Column -> KiCad field mapping, applied identically to every sub-library.
FIELDS = [
    {"column": "value", "name": "Value",
     "visible_on_add": True, "visible_in_chooser": True},
    {"column": "mpn", "name": "MPN",
     "visible_on_add": False, "visible_in_chooser": True, "show_name": True},
    {"column": "manufacturer", "name": "Manufacturer",
     "visible_on_add": False, "visible_in_chooser": True, "show_name": True},
    {"column": "category", "name": "Category",
     "visible_on_add": False, "visible_in_chooser": True, "show_name": True},
    {"column": "datasheet", "name": "Datasheet",
     "visible_on_add": False, "visible_in_chooser": False},
    # Stock, joined in by the per-library view. Visible in the chooser so "do we
    # already have this?" is answerable while picking a part, which is most of the
    # value of tracking inventory at all. It does mean any stock movement dirties
    # the database file and re-sends it on the next sync -- that file is small next
    # to the 3D models, so the trade is worth it.
    {"column": "quantity", "name": "In Stock",
     "visible_on_add": False, "visible_in_chooser": True, "show_name": True},
    {"column": "location", "name": "Location",
     "visible_on_add": False, "visible_in_chooser": True, "show_name": True},
]

PROPERTIES = {"description": "description", "keywords": "keywords"}

# ${CWD} resolves next to the .kicad_dbl, so the same file works on every machine.
# The driver name is exact and case-sensitive on Windows -- see docs/SETUP_KICAD.md.
CONNECTION_STRING = (
    "Driver={SQLite3 ODBC Driver};Database=${CWD}/"
    + os.path.basename(config.DB_PATH) + ";"
)


def build():
    """Write the .kicad_dbl for the current set of libraries. Returns the written dict."""
    libraries = db.list_libraries()
    doc = {
        "meta": {"version": 0},
        "name": config.LIB_NICKNAME,
        "description": "Lu group shared KiCad library (symbols, footprints, 3D models)",
        "source": {
            "type": "odbc",
            "dsn": "",
            "username": "",
            "password": "",
            "timeout_seconds": 5,
            "connection_string": CONNECTION_STRING,
        },
        "libraries": [
            {
                "name": lib["name"],
                "table": lib["view"],
                "key": "slug",
                "symbols": "symbols",
                "footprints": "footprints",
                "fields": FIELDS,
                "properties": PROPERTIES,
            }
            for lib in libraries
        ],
    }
    config.ensure_dirs()
    with open(config.DBL_FILE, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=4)
        fh.write("\n")
    return doc
