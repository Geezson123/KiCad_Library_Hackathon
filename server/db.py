"""SQLite access layer.

This is the exact database KiCad reads over ODBC, so the column names here MUST match
the columns referenced in ``library/LuGroupLib.kicad_dbl``. Keep names simple (no spaces)
so the .kicad_dbl field mappings stay clean.
"""
import re
import sqlite3
import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS libraries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    kind        TEXT    NOT NULL DEFAULT 'group',
    description TEXT    NOT NULL DEFAULT '',
    owner_id    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT ''
);

-- Stock levels live in the KiCad-facing database (no personal data) so the
-- per-library views can join them in and answer "do we have this?" right in the
-- Symbol Chooser. Who moved the stock is audit data and lives in the app database.
CREATE TABLE IF NOT EXISTS inventory (
    part_id    INTEGER PRIMARY KEY,
    quantity   INTEGER NOT NULL DEFAULT 0,
    location   TEXT    NOT NULL DEFAULT '',
    min_qty    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL DEFAULT '',
    slug          TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL DEFAULT '',
    mpn           TEXT    NOT NULL DEFAULT '',
    manufacturer  TEXT    NOT NULL DEFAULT '',
    value         TEXT    NOT NULL DEFAULT '',
    description   TEXT    NOT NULL DEFAULT '',
    datasheet     TEXT    NOT NULL DEFAULT '',
    keywords      TEXT    NOT NULL DEFAULT '',
    symbols       TEXT    NOT NULL DEFAULT '',
    footprints    TEXT    NOT NULL DEFAULT '',
    model3d       TEXT    NOT NULL DEFAULT '',
    created_by    TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT '',
    owner_id      INTEGER NOT NULL DEFAULT 0,
    library_id    INTEGER NOT NULL DEFAULT 1,
    deprecated    INTEGER NOT NULL DEFAULT 0
);
"""

# Columns added after the first release. ``created_by`` stays as a denormalised display
# name so browsing needs no cross-database join; ``owner_id`` is the authoritative
# reference and is a bare integer, carrying no personal data into the sync bundle.
ADDED_COLUMNS = [
    ("owner_id", "INTEGER NOT NULL DEFAULT 0"),
    ("library_id", "INTEGER NOT NULL DEFAULT 1"),
    ("slug", "TEXT NOT NULL DEFAULT ''"),
    ("deprecated", "INTEGER NOT NULL DEFAULT 0"),
]

# Library kinds. 'group' = only members may add parts; 'common' = anyone may add, but
# each part stays editable only by its uploader and their invitees.
KIND_GROUP = "group"
KIND_COMMON = "common"
KINDS = (KIND_GROUP, KIND_COMMON)

# The library that existing parts are migrated into, and that the seed part lands in.
DEFAULT_LIBRARY = "General"


def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn):
    """Bring an existing database up to the current schema.

    The important change is that the ``.kicad_dbl`` key moved from ``name`` to ``slug``.
    A placed symbol's only link back to the library is its LIB_ID, which is built from
    the key -- so keying on an editable display name meant that renaming a part silently
    orphaned it in every schematic that used it. ``slug`` is assigned once at creation
    and never rewritten; ``name`` is now free to change.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(parts)")}
    if "name" not in have:
        conn.execute("ALTER TABLE parts ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    for col, decl in ADDED_COLUMNS:
        if col not in have:
            conn.execute(f"ALTER TABLE parts ADD COLUMN {col} {decl}")

    # Every part needs a home library; create the default one if the table is empty.
    if not conn.execute("SELECT 1 FROM libraries").fetchone():
        conn.execute(
            "INSERT INTO libraries (name, kind, description, owner_id, created_at)"
            " VALUES (?, ?, ?, 0, ?)",
            (DEFAULT_LIBRARY, KIND_COMMON,
             "Shared parts that are not specific to one sub-group.", now_iso()),
        )
    default_id = conn.execute(
        "SELECT id FROM libraries ORDER BY id LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "UPDATE parts SET library_id = ? WHERE library_id = 0 OR library_id IS NULL"
        " OR library_id NOT IN (SELECT id FROM libraries)", (default_id,)
    )

    # Backfill display names, then slugs, for rows predating each column.
    for row in conn.execute("SELECT * FROM parts WHERE name = '' OR name IS NULL").fetchall():
        conn.execute("UPDATE parts SET name = ? WHERE id = ?",
                     (_display_name(dict(row)), row["id"]))
    for row in conn.execute("SELECT * FROM parts WHERE slug = '' OR slug IS NULL").fetchall():
        base = _sanitize_key(dict(row)["name"] or _display_name(dict(row)))
        conn.execute("UPDATE parts SET slug = ? WHERE id = ?",
                     (_unique_slug(conn, base), row["id"]))

    # ``name`` is no longer the KiCad key, so it no longer has to be unique -- dropping
    # this is what lets a part be renamed without the old auto-mangling to "_2".
    conn.execute("DROP INDEX IF EXISTS idx_parts_name")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_parts_slug ON parts(slug)")
    rebuild_views(conn)


def _display_name(data):
    """Pick a human-readable base name for a part (before uniquifying)."""
    sym = data.get("symbols") or ""
    sym_name = sym.split(":", 1)[1] if ":" in sym else sym
    for cand in (data.get("mpn"), data.get("value"), sym_name, "part"):
        if cand and str(cand).strip():
            # Strip characters that would break a KiCad LIB_ID ("nickname:name").
            return re.sub(r"[:/\\]", "_", str(cand).strip())
    return "part"


def _sanitize_key(text):
    """Make a string safe to use as a KiCad symbol name.

    Symbol names may not contain spaces, ':' or '/'. The slash matters especially here:
    KiCad uses it as the separator between a sub-library name and the part name, so a
    stray one would split the LIB_ID in the wrong place.
    """
    text = re.sub(r"\s+", "_", (text or "").strip())
    text = re.sub(r"[^A-Za-z0-9_.+\-]", "", text)
    return text or "part"


def _unique_slug(conn, base):
    """Return ``base`` (or ``base_2``, ``base_3``…) not already used as a slug.

    Slugs are never reused or reassigned, so this runs once per part at creation.
    """
    candidate = base
    i = 2
    while conn.execute("SELECT 1 FROM parts WHERE slug = ?", (candidate,)).fetchone():
        candidate = f"{base}_{i}"
        i += 1
    return candidate


# Columns that must stay numeric. Text columns default to '' when absent, but an integer
# column would be silently written as '' by that same rule -- and 0 is falsy, so a plain
# ``value or ''`` would corrupt a legitimate zero.
INT_COLUMNS = {"owner_id", "library_id", "deprecated"}


def _coerce(col, value):
    """Normalise a column value: ints stay ints (defaulting to 0), text defaults to ''."""
    if col in INT_COLUMNS:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
    return value or ""


def insert_part(data):
    """Insert a part. ``data`` is a dict of column -> value. Returns new row id."""
    cols = [
        "name", "slug", "category", "mpn", "manufacturer", "value", "description",
        "datasheet", "keywords", "symbols", "footprints", "model3d", "created_by",
        "created_at", "owner_id", "library_id", "deprecated",
    ]
    with get_conn() as conn:
        name = (data.get("name") or "").strip() or _display_name(data)
        # The slug is the KiCad key and is fixed here, for good: it ends up inside the
        # LIB_ID of every schematic symbol placed from this part.
        data = dict(data, name=name, slug=_unique_slug(conn, _sanitize_key(name)))
        values = [_coerce(c, data.get(c)) for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO parts ({', '.join(cols)}) VALUES ({placeholders})", values
        )
        return cur.lastrowid


def update_part(part_id, data):
    """Update an existing part's editable columns. Returns the new display name.

    Deliberately excludes ``slug`` and ``library_id``: both feed the LIB_ID, so changing
    either would orphan the part in existing schematics. Parts are deprecated and
    re-created rather than moved between libraries.
    """
    cols = [
        "name", "category", "mpn", "manufacturer", "value", "description", "datasheet",
        "keywords", "symbols", "footprints", "model3d", "deprecated",
    ]
    with get_conn() as conn:
        name = (data.get("name") or "").strip() or _display_name(data)
        data = dict(data, name=name)
        sets = ", ".join(f"{c} = ?" for c in cols)
        values = [_coerce(c, data.get(c)) for c in cols] + [part_id]
        conn.execute(f"UPDATE parts SET {sets} WHERE id = ?", values)
        return name


def delete_part(part_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM parts WHERE id = ?", (part_id,))
        conn.execute("DELETE FROM inventory WHERE part_id = ?", (part_id,))


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------
class StockError(ValueError):
    """A stock movement was refused; the message is user-facing."""


def get_inventory(part_id):
    """Stock record for a part. Returns zeroed defaults if it has never been counted."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM inventory WHERE part_id = ?", (part_id,)
        ).fetchone()
    if row:
        return dict(row)
    return {"part_id": part_id, "quantity": 0, "location": "", "min_qty": 0,
            "updated_at": ""}


def set_stock_settings(part_id, location, min_qty):
    """Update where a part is kept and its reorder threshold (not the count itself)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO inventory (part_id, quantity, location, min_qty, updated_at)"
            " VALUES (?, 0, ?, ?, ?)"
            " ON CONFLICT(part_id) DO UPDATE SET location = excluded.location,"
            " min_qty = excluded.min_qty, updated_at = excluded.updated_at",
            (part_id, (location or "").strip(), max(0, int(min_qty or 0)), now_iso()),
        )


def adjust_stock(part_id, delta):
    """Apply a stock movement and return the new quantity.

    Refuses to go negative: a count that drifts below zero is always a data-entry
    mistake, and silently clamping it hides the error instead of surfacing it.
    """
    delta = int(delta)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM inventory WHERE part_id = ?", (part_id,)
        ).fetchone()
        current = row["quantity"] if row else 0
        new = current + delta
        if new < 0:
            raise StockError(
                f"That would take stock to {new}. There are only {current} on hand."
            )
        conn.execute(
            "INSERT INTO inventory (part_id, quantity, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(part_id) DO UPDATE SET quantity = excluded.quantity,"
            " updated_at = excluded.updated_at",
            (part_id, new, now_iso()),
        )
        return new


def list_inventory(query="", library_id=None, low_only=False):
    """Parts with their stock, for the inventory page."""
    sql = (
        "SELECT p.*, COALESCE(i.quantity, 0) AS quantity,"
        " COALESCE(i.location, '') AS location,"
        " COALESCE(i.min_qty, 0) AS min_qty, i.updated_at AS stock_updated_at"
        " FROM parts p LEFT JOIN inventory i ON i.part_id = p.id WHERE 1=1"
    )
    args = []
    if query:
        like = f"%{query}%"
        sql += (" AND (p.mpn LIKE ? OR p.name LIKE ? OR p.manufacturer LIKE ?"
                " OR COALESCE(i.location, '') LIKE ?)")
        args += [like] * 4
    if library_id:
        sql += " AND p.library_id = ?"
        args.append(int(library_id))
    if low_only:
        # A threshold of 0 means "not tracked" -- don't report every uncounted part.
        sql += " AND COALESCE(i.min_qty, 0) > 0 AND COALESCE(i.quantity, 0) <= i.min_qty"
    sql += " ORDER BY p.name"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def find_part_by_mpn(mpn):
    """Match a receipt line to a part by manufacturer part number, case-insensitively."""
    text = (mpn or "").strip()
    if not text:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM parts WHERE mpn <> '' AND mpn = ? COLLATE NOCASE", (text,)
        ).fetchone()
        return dict(row) if row else None


def asset_in_use(column, value, exclude_id=None):
    """True if any (other) part still references this symbol/footprint/model value.

    Used before deleting a shared asset so we never orphan a part that reuses it.
    """
    if column not in ("symbols", "footprints", "model3d") or not value:
        return False
    sql = f"SELECT 1 FROM parts WHERE {column} = ?"
    args = [value]
    if exclude_id is not None:
        sql += " AND id <> ?"
        args.append(exclude_id)
    with get_conn() as conn:
        return conn.execute(sql, args).fetchone() is not None


def list_parts(query="", category="", library_id=None, include_deprecated=True):
    sql = "SELECT * FROM parts WHERE 1=1"
    args = []
    if query:
        like = f"%{query}%"
        sql += (
            " AND (mpn LIKE ? OR value LIKE ? OR description LIKE ?"
            " OR manufacturer LIKE ? OR keywords LIKE ? OR category LIKE ?"
            " OR name LIKE ?)"
        )
        args += [like] * 7
    if category:
        sql += " AND category = ?"
        args.append(category)
    if library_id:
        sql += " AND library_id = ?"
        args.append(int(library_id))
    if not include_deprecated:
        sql += " AND deprecated = 0"
    sql += " ORDER BY id DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_part(part_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# libraries
# ---------------------------------------------------------------------------
# KiCad sub-library names may not contain '/', ':' or whitespace: the name is prefixed
# onto every symbol name placed from it, and '/' is the separator between the two.
_LIBRARY_NAME_RE = re.compile(r"^[A-Za-z0-9_.+\-]{1,48}$")


class LibraryNameError(ValueError):
    """The proposed library name is not usable as a KiCad sub-library name."""


def validate_library_name(name):
    """Raise LibraryNameError unless ``name`` is a legal KiCad sub-library name."""
    name = (name or "").strip()
    if not name:
        raise LibraryNameError("Give the library a name.")
    if not _LIBRARY_NAME_RE.match(name):
        raise LibraryNameError(
            "Use only letters, numbers, and _ . + - (no spaces, no '/' or ':'). "
            "KiCad puts this name in front of every symbol placed from the library."
        )
    return name


def _view_name(lib):
    """SQL view backing one sub-library. The id keeps it unique even if two names
    normalise to the same identifier; the name keeps it readable when debugging."""
    suffix = re.sub(r"[^a-z0-9]+", "_", lib["name"].lower()).strip("_")
    return f"lib_{lib['id']}_{suffix}"


def rebuild_views(conn):
    """Recreate one view per library. Each becomes a sub-library in the .kicad_dbl.

    Deprecated parts are filtered out here, so they vanish from KiCad's chooser while
    staying resolvable for schematics that already placed them -- which is the whole
    point of deprecating instead of deleting.
    """
    existing = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE 'lib_%'"
        )
    }
    wanted = set()
    for row in conn.execute("SELECT * FROM libraries ORDER BY id"):
        view = _view_name(dict(row))
        wanted.add(view)
        conn.execute(f'DROP VIEW IF EXISTS "{view}"')
        # LEFT JOIN, not INNER: a part with no inventory row has never been counted,
        # which must read as quantity 0 rather than vanishing from KiCad entirely.
        conn.execute(
            f'CREATE VIEW "{view}" AS SELECT p.*,'
            " COALESCE(i.quantity, 0) AS quantity,"
            " COALESCE(i.location, '') AS location"
            " FROM parts p LEFT JOIN inventory i ON i.part_id = p.id"
            f" WHERE p.library_id = {int(row['id'])} AND p.deprecated = 0"
        )
    for stale in existing - wanted:
        conn.execute(f'DROP VIEW IF EXISTS "{stale}"')


def list_libraries():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM libraries ORDER BY name").fetchall()
        out = []
        for r in rows:
            lib = dict(r)
            lib["view"] = _view_name(lib)
            lib["part_count"] = conn.execute(
                "SELECT COUNT(*) FROM parts WHERE library_id = ?", (lib["id"],)
            ).fetchone()[0]
            out.append(lib)
        return out


def get_library(library_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM libraries WHERE id = ?", (library_id,)
        ).fetchone()
        if not row:
            return None
        lib = dict(row)
        lib["view"] = _view_name(lib)
        lib["part_count"] = conn.execute(
            "SELECT COUNT(*) FROM parts WHERE library_id = ?", (lib["id"],)
        ).fetchone()[0]
        return lib


def create_library(name, kind, description, owner_id):
    name = validate_library_name(name)
    if kind not in KINDS:
        raise LibraryNameError("Pick either a sub-group or a common library.")
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM libraries WHERE name = ? COLLATE NOCASE",
                        (name,)).fetchone():
            raise LibraryNameError(f"A library called {name} already exists.")
        cur = conn.execute(
            "INSERT INTO libraries (name, kind, description, owner_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, kind, (description or "").strip(), int(owner_id), now_iso()),
        )
        rebuild_views(conn)
        return cur.lastrowid


def rename_library(library_id, name):
    """Rename a library -- only allowed while it is empty.

    Once a part exists, the library name is baked into that part's LIB_ID in every
    schematic that placed it, so a rename would orphan them. Empty libraries have no
    such references, which makes early typo fixes free.
    """
    name = validate_library_name(name)
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM parts WHERE library_id = ?", (library_id,)
        ).fetchone()[0]
        if count:
            raise LibraryNameError(
                f"{name} already has {count} part(s). Renaming it now would break the "
                "link to every schematic symbol placed from it."
            )
        if conn.execute("SELECT 1 FROM libraries WHERE name = ? COLLATE NOCASE AND id <> ?",
                        (name, library_id)).fetchone():
            raise LibraryNameError(f"A library called {name} already exists.")
        conn.execute("UPDATE libraries SET name = ? WHERE id = ?", (name, library_id))
        rebuild_views(conn)


def delete_library(library_id):
    """Delete a library. Refused while it still holds parts, for the same reason."""
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM parts WHERE library_id = ?", (library_id,)
        ).fetchone()[0]
        if count:
            raise LibraryNameError(
                f"This library still holds {count} part(s). Delete or deprecate them first."
            )
        if conn.execute("SELECT COUNT(*) FROM libraries").fetchone()[0] <= 1:
            raise LibraryNameError("There has to be at least one library.")
        conn.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
        rebuild_views(conn)


def list_categories():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM parts WHERE category <> '' ORDER BY category"
        ).fetchall()
        return [r[0] for r in rows]


def count_parts():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat(sep=" ")
