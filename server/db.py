"""SQLite access layer.

This is the exact database KiCad reads over ODBC, so the column names here MUST match
the columns referenced in ``library/HackLib.kicad_dbl``. Keep names simple (no spaces)
so the .kicad_dbl field mappings stay clean.
"""
import re
import sqlite3
import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL DEFAULT '',
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
    created_at    TEXT    NOT NULL DEFAULT ''
);
"""


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

    The ``name`` column was added after the first version: KiCad shows the ``key``
    column value as the part name in the Symbol Chooser, so we key on ``name`` (a
    unique, human-readable string) instead of the numeric ``id``.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(parts)")}
    if "name" not in have:
        conn.execute("ALTER TABLE parts ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    # Backfill any rows that have no name yet (old rows, or the seed before this change).
    rows = conn.execute("SELECT * FROM parts WHERE name = '' OR name IS NULL").fetchall()
    for row in rows:
        base = _display_name(dict(row))
        conn.execute(
            "UPDATE parts SET name = ? WHERE id = ?",
            (_unique_name(conn, base), row["id"]),
        )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_parts_name ON parts(name)")


def _display_name(data):
    """Pick a human-readable base name for a part (before uniquifying)."""
    sym = data.get("symbols") or ""
    sym_name = sym.split(":", 1)[1] if ":" in sym else sym
    for cand in (data.get("mpn"), data.get("value"), sym_name, "part"):
        if cand and str(cand).strip():
            # Strip characters that would break a KiCad LIB_ID ("nickname:name").
            return re.sub(r"[:/\\]", "_", str(cand).strip())
    return "part"


def _unique_name(conn, base, exclude_id=None):
    """Return ``base`` (or ``base_2``, ``base_3``…) not already used in ``name``."""
    sql = "SELECT 1 FROM parts WHERE name = ?"
    args = [base]
    if exclude_id is not None:
        sql += " AND id <> ?"
        args.append(exclude_id)
    candidate = base
    i = 2
    while conn.execute(sql, [candidate] + args[1:]).fetchone():
        candidate = f"{base}_{i}"
        i += 1
    return candidate


def insert_part(data):
    """Insert a part. ``data`` is a dict of column -> value. Returns new row id."""
    cols = [
        "name", "category", "mpn", "manufacturer", "value", "description", "datasheet",
        "keywords", "symbols", "footprints", "model3d", "created_by", "created_at",
    ]
    with get_conn() as conn:
        base = (data.get("name") or "").strip() or _display_name(data)
        data = dict(data, name=_unique_name(conn, re.sub(r"[:/\\]", "_", base)))
        values = [data.get(c, "") or "" for c in cols]
        placeholders = ", ".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO parts ({', '.join(cols)}) VALUES ({placeholders})", values
        )
        return cur.lastrowid


def list_parts(query="", category=""):
    sql = "SELECT * FROM parts WHERE 1=1"
    args = []
    if query:
        like = f"%{query}%"
        sql += (
            " AND (mpn LIKE ? OR value LIKE ? OR description LIKE ?"
            " OR manufacturer LIKE ? OR keywords LIKE ? OR category LIKE ?)"
        )
        args += [like] * 6
    if category:
        sql += " AND category = ?"
        args.append(category)
    sql += " ORDER BY id DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_part(part_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
        return dict(row) if row else None


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
