"""SQLite access layer.

This is the exact database KiCad reads over ODBC, so the column names here MUST match
the columns referenced in ``library/HackLib.kicad_dbl``. Keep names simple (no spaces)
so the .kicad_dbl field mappings stay clean.
"""
import sqlite3
import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
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


def insert_part(data):
    """Insert a part. ``data`` is a dict of column -> value. Returns new row id."""
    cols = [
        "category", "mpn", "manufacturer", "value", "description", "datasheet",
        "keywords", "symbols", "footprints", "model3d", "created_by", "created_at",
    ]
    values = [data.get(c, "") or "" for c in cols]
    placeholders = ", ".join("?" for _ in cols)
    with get_conn() as conn:
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
