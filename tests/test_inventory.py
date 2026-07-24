#!/usr/bin/env python3
"""Stage 7: inventory and Mouser receipt ingestion.

Claude is stubbed throughout — the point is the stock arithmetic, the audit trail,
and the review-before-apply boundary, not the model.
"""
import json
import sqlite3
import sys
import types

from harness import check, finish, make_client, section, setup

webapp, config, db = setup()

import ai   # noqa: E402
import dbl  # noqa: E402


def client():
    return make_client(webapp)


def sign_in(c, name="Stock Tester"):
    c.post("/dev-login", data={"name": name}, follow_redirects=True)


def fake_anthropic(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    block = types.SimpleNamespace(type="text", text=text)
    response = types.SimpleNamespace(content=[block], stop_reason=stop_reason)
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return response

    module = types.ModuleType("anthropic")
    module.Anthropic = lambda **kw: types.SimpleNamespace(
        messages=types.SimpleNamespace(create=create))
    sys.modules["anthropic"] = module
    return captured


part = db.list_parts()[0]
PART_ID = part["id"]

section("stock arithmetic")
check("uncounted parts read as zero", db.get_inventory(PART_ID)["quantity"] == 0)
check("receiving stock adds", db.adjust_stock(PART_ID, 100) == 100)
check("consuming stock subtracts", db.adjust_stock(PART_ID, -30) == 70)

try:
    db.adjust_stock(PART_ID, -1000)
    refused = False
except db.StockError as exc:
    refused = "only 70" in str(exc)
check("going negative is refused, not clamped", refused)
check("the refused move changed nothing", db.get_inventory(PART_ID)["quantity"] == 70)

section("location and reorder level")
db.set_stock_settings(PART_ID, "Drawer B3", 25)
inv = db.get_inventory(PART_ID)
check("location saved", inv["location"] == "Drawer B3", inv)
check("reorder level saved", inv["min_qty"] == 25, inv)
check("settings do not disturb the count", inv["quantity"] == 70, inv)
check("timestamped", bool(inv["updated_at"]))

section("low-stock detection")
check("not low at 70 against 25", db.list_inventory(low_only=True) == [])
db.adjust_stock(PART_ID, -50)  # -> 20, below the level of 25
low = db.list_inventory(low_only=True)
check("low once under the level", len(low) == 1 and low[0]["id"] == PART_ID, low)
db.set_stock_settings(PART_ID, "Drawer B3", 0)
check("a level of 0 means untracked, not always-low", db.list_inventory(low_only=True) == [])
db.set_stock_settings(PART_ID, "Drawer B3", 25)

section("stock reaches KiCad")
conn = sqlite3.connect(config.DB_PATH)
view = db.list_libraries()[0]["view"]
cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{view}")')]
check("view exposes quantity", "quantity" in cols, cols)
check("view exposes location", "location" in cols, cols)
row = conn.execute(f'SELECT quantity, location FROM "{view}" WHERE id = ?',
                   (PART_ID,)).fetchone()
check("view reports the live count", row[0] == 20, row)
check("view reports the location", row[1] == "Drawer B3", row)
conn.close()

doc = dbl.build()
fields = {f["column"] for f in doc["libraries"][0]["fields"]}
check(".kicad_dbl surfaces quantity", "quantity" in fields, sorted(fields))
check(".kicad_dbl surfaces location", "location" in fields, sorted(fields))

section("a part with no inventory row still appears in KiCad")
# Regression guard: an INNER JOIN here would silently hide every uncounted part
# from the Symbol Chooser.
new_id = db.insert_part({"name": "UNCOUNTED_PART", "mpn": "UNCOUNTED-1",
                         "library_id": part["library_id"], "created_at": db.now_iso()})
conn = sqlite3.connect(config.DB_PATH)
row = conn.execute(f'SELECT quantity FROM "{view}" WHERE id = ?', (new_id,)).fetchone()
conn.close()
check("uncounted part is still visible", row is not None)
check("and reads as zero, not null", row and row[0] == 0, row)

section("audit trail")
with client() as c:
    sign_in(c, "Ada")
    r = c.post(f"/inventory/{PART_ID}/adjust",
               data={"delta": "-5", "reason": "used on rev B"}, follow_redirects=True)
    check("adjustment applied via the UI", b"15 in stock" in r.data, r.data[-300:])

history = webapp.auth.stock_history(PART_ID)
check("the move was logged", len(history) >= 1, history)
latest = history[0]
check("delta recorded", latest["delta"] == -5, latest)
check("resulting count recorded", latest["resulting"] == 15, latest)
check("reason recorded", latest["reason"] == "used on rev B", latest)
check("mover recorded", latest["user_name"] == "Ada", latest)

with client() as c:
    sign_in(c, "Ada")
    r = c.post(f"/inventory/{PART_ID}/adjust", data={"delta": "-9999"},
               follow_redirects=True)
    check("an impossible adjustment is refused in the UI", b"only 15" in r.data)
check("and left the count alone", db.get_inventory(PART_ID)["quantity"] == 15)

section("audit log stays out of the sync bundle")
conn = sqlite3.connect(config.DB_PATH)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
conn.close()
check("stock_moves is not in the KiCad database", "stock_moves" not in tables, tables)
check("inventory counts are (no personal data)", "inventory" in tables, tables)

section("matching receipt lines to parts")
check("matches MPN case-insensitively",
      (db.find_part_by_mpn(part["mpn"].lower()) or {}).get("id") == PART_ID)
check("unknown MPN returns nothing", db.find_part_by_mpn("NO-SUCH-PART-9999") is None)
check("blank MPN returns nothing", db.find_part_by_mpn("") is None)

section("reading a receipt changes nothing")
config.ANTHROPIC_API_KEY = "test-key"
captured = fake_anthropic({
    "order_number": "71234567",
    "items": [
        {"mpn": part["mpn"], "mouser_pn": "603-X", "description": "10k resistor",
         "quantity": 200},
        {"mpn": "NOT-IN-LIBRARY-1", "mouser_pn": "999-Y", "description": "mystery part",
         "quantity": 5},
        {"mpn": "", "mouser_pn": "", "description": "Shipping", "quantity": 1},
        {"mpn": "ZERO-QTY-PART", "mouser_pn": "000-Z", "description": "zero", "quantity": 0},
    ],
    "notes": "one line was unreadable",
})

before = db.get_inventory(PART_ID)["quantity"]
with client() as c:
    sign_in(c, "Ada")
    r = c.post("/inventory/receipt", data={"text": "Mouser order confirmation..."},
               follow_redirects=True)
    body = r.data.decode()
    check("review page rendered", r.status_code == 200 and "Review order" in body)
    check("order number shown", "71234567" in body)
    check("matched line listed", part["mpn"] in body)
    check("unmatched line flagged", "no matching part" in body)
    check("blank-MPN line dropped", "Shipping" not in body)
    check("zero-quantity line dropped", "ZERO-QTY-PART" not in body)
    check("projected stock shown", f"{before + 200}" in body)
    check("reader notes surfaced", "unreadable" in body)

check("NO stock moved during review", db.get_inventory(PART_ID)["quantity"] == before)

section("applying the receipt")
with client() as c:
    sign_in(c, "Ada")
    r = c.post("/inventory/receipt/apply",
               data={"order_number": "71234567", "apply": str(PART_ID),
                     f"qty_{PART_ID}": "200"}, follow_redirects=True)
    check("apply confirms", b"Stocked 1 line" in r.data, r.data[-300:])
check("stock increased", db.get_inventory(PART_ID)["quantity"] == before + 200)
latest = webapp.auth.stock_history(PART_ID)[0]
check("logged as a receipt", latest["reason"] == "receipt", latest)
check("order number kept as the reference", latest["reference"] == "71234567", latest)

section("PDF receipts go to Claude as a document block")
captured = fake_anthropic({"order_number": "", "items": [], "notes": "n"})
try:
    ai.read_receipt(pdf_bytes=b"%PDF-1.4 fake")
except ai.ReceiptError:
    pass
content = captured.get("messages", [{}])[0].get("content", [])
kinds = [b.get("type") for b in content if isinstance(b, dict)]
check("a document block is sent", "document" in kinds, kinds)
check("document precedes the question", kinds and kinds[0] == "document", kinds)

section("receipt failure modes")
fake_anthropic("not json at all")
try:
    ai.read_receipt(text="whatever")
    raised = False
except ai.ReceiptError as exc:
    raised = "unparseable" in str(exc)
check("unparseable output raises rather than reporting an empty order", raised)

fake_anthropic("{}", stop_reason="refusal")
try:
    ai.read_receipt(text="whatever")
    raised = False
except ai.ReceiptError as exc:
    raised = "declined" in str(exc)
check("a refusal raises", raised)

config.ANTHROPIC_API_KEY = ""
try:
    ai.read_receipt(text="whatever")
    raised = False
except ai.ReceiptError as exc:
    raised = "ANTHROPIC_API_KEY" in str(exc)
check("no key gives actionable guidance", raised)

try:
    ai.read_receipt()
    raised = False
except ai.ReceiptError:
    raised = True
check("no input at all is refused", raised)

section("permissions")
with client() as c:
    r = c.get("/inventory")
    check("browsing inventory is public", r.status_code == 200, r.status_code)

    r = c.post(f"/inventory/{PART_ID}/adjust", data={"delta": "5"})
    check("anonymous adjustment redirects to login",
          r.status_code == 302 and "/login" in r.headers.get("Location", ""),
          r.status_code)

    r = c.post("/inventory/receipt/apply", data={"apply": str(PART_ID)})
    check("anonymous receipt apply redirects to login",
          r.status_code == 302 and "/login" in r.headers.get("Location", ""))

check("no stock moved anonymously",
      db.get_inventory(PART_ID)["quantity"] == before + 200)

finish()
