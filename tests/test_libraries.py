#!/usr/bin/env python3
"""Stage 2 + 3: library creation, immutable slugs, the generated .kicad_dbl, per-library
views, permissions, name freezing, and deprecation."""
import io
import json
import os
import sqlite3
import zipfile

from harness import (REPO_ROOT as REPO, check, finish, make_client, section,
                     setup)

webapp, config, db = setup()


def client():
    return make_client(webapp)


def sign_in(client, name, librarian=False):
    data = {"name": name}
    if librarian:
        data["librarian"] = "1"
    client.post("/dev-login", data=data, follow_redirects=True)


def upload(client, library_id, mpn):
    sym = os.path.join(REPO, "examples", "R_10K.kicad_sym")
    with open(sym, "rb") as fh:
        blob = fh.read()
    return client.post("/upload", data={
        "library_id": str(library_id), "category": "Resistor", "mpn": mpn,
        "manufacturer": "Yageo", "value": "10K", "description": "test part",
        "symbol": (io.BytesIO(blob), "R_10K.kicad_sym"),
    }, content_type="multipart/form-data", follow_redirects=True)


section("migration of existing data")
parts = db.list_parts()
check("existing part survived migration", len(parts) == 1, len(parts))
p = parts[0]
check("got a library_id", p["library_id"] > 0, p["library_id"])
check("got a slug", bool(p["slug"]), p["slug"])
check("slug has no '/' or ':' (LIB_ID separators)",
      "/" not in p["slug"] and ":" not in p["slug"], p["slug"])
check("not deprecated by default", p["deprecated"] == 0)
libs = db.list_libraries()
check("default library created", len(libs) == 1 and libs[0]["name"] == "General", libs)

section("generated .kicad_dbl")
doc = json.load(open(config.DBL_FILE, encoding="utf-8"))
check("nickname preserved", doc["name"] == "LuGroupLib", doc["name"])
check("one sub-library entry per library", len(doc["libraries"]) == 1, doc["libraries"])
entry = doc["libraries"][0]
check("sub-library is named", entry["name"] == "General", entry)
check("key is the immutable slug, not the editable name", entry["key"] == "slug", entry["key"])
check("points at the library's view", entry["table"] == libs[0]["view"], entry["table"])

section("SQL views")
conn = sqlite3.connect(config.DB_PATH)
views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")]
check("view exists for the library", libs[0]["view"] in views, views)
n = conn.execute(f'SELECT COUNT(*) FROM "{libs[0]["view"]}"').fetchone()[0]
check("view returns the library's parts", n == 1, n)
conn.close()

section("creating libraries")
with client() as c:
    sign_in(c, "Ada")
    r = c.post("/libraries/new", data={
        "name": "RF_Frontend", "kind": "group", "description": "RF team"},
        follow_redirects=True)
    check("created a sub-group library", r.status_code == 200 and b"RF_Frontend" in r.data)

    r = c.post("/libraries/new", data={
        "name": "Passives", "kind": "common", "description": "jellybeans"},
        follow_redirects=True)
    check("created a common library", r.status_code == 200 and b"Passives" in r.data)

    r = c.post("/libraries/new", data={"name": "Bad Name", "kind": "group"},
               follow_redirects=True)
    check("rejects a name with a space", b"no spaces" in r.data or b"only letters" in r.data.lower())

    r = c.post("/libraries/new", data={"name": "RF/Front", "kind": "group"},
               follow_redirects=True)
    check("rejects a name with '/'", b"no spaces" in r.data or b"only letters" in r.data.lower())

    r = c.post("/libraries/new", data={"name": "RF_Frontend", "kind": "group"},
               follow_redirects=True)
    check("rejects a duplicate name", b"already exists" in r.data)

by_name = {l["name"]: l for l in db.list_libraries()}
rf, passives = by_name["RF_Frontend"], by_name["Passives"]
check("both libraries persisted", rf and passives)

doc = json.load(open(config.DBL_FILE, encoding="utf-8"))
check(".kicad_dbl now has 3 sub-libraries", len(doc["libraries"]) == 3,
      [e["name"] for e in doc["libraries"]])

section("permissions: adding parts")
with client() as c:
    sign_in(c, "Ada")  # owner of both new libraries
    r = upload(c, rf["id"], "RF-PART-1")
    check("owner can add to their sub-group library", b"Added part" in r.data)

with client() as c:
    sign_in(c, "Bob")  # not a member of RF_Frontend
    r = c.post("/upload", data={"library_id": str(rf["id"]), "mpn": "X"},
               content_type="multipart/form-data")
    check("non-member is refused (403) on a sub-group library", r.status_code == 403,
          r.status_code)

    r = upload(c, passives["id"], "BOB-COMMON-1")
    check("anyone can add to a common library", b"Added part" in r.data)

section("permissions: editing parts")
bob_part = [p for p in db.list_parts() if p["mpn"] == "BOB-COMMON-1"][0]
rf_part = [p for p in db.list_parts() if p["mpn"] == "RF-PART-1"][0]

with client() as c:
    sign_in(c, "Carol")
    r = c.get(f"/part/{bob_part['id']}/edit")
    check("outsider cannot edit a common-library part", r.status_code == 403, r.status_code)

with client() as c:
    sign_in(c, "Bob")
    r = c.get(f"/part/{bob_part['id']}/edit")
    check("uploader can edit their own part", r.status_code == 200, r.status_code)
    # Bob invites Carol.
    carol = [u for u in webapp.auth.list_users() if u["name"] == "Carol"][0]
    c.post(f"/part/{bob_part['id']}/editors", data={"user_id": str(carol["id"])},
           follow_redirects=True)

with client() as c:
    sign_in(c, "Carol")
    r = c.get(f"/part/{bob_part['id']}/edit")
    check("invited editor can now edit it", r.status_code == 200, r.status_code)
    r = c.get(f"/part/{rf_part['id']}/edit")
    check("invite does NOT leak to other parts", r.status_code == 403, r.status_code)

with client() as c:
    sign_in(c, "Dave", librarian=True)
    r = c.get(f"/part/{bob_part['id']}/edit")
    check("master librarian can edit anything", r.status_code == 200, r.status_code)

with client() as c:
    sign_in(c, "Ada")
    ada = [u for u in webapp.auth.list_users() if u["name"] == "Ada"][0]
    bob = [u for u in webapp.auth.list_users() if u["name"] == "Bob"][0]
    c.post(f"/libraries/{rf['id']}/manage",
           data={"action": "add_member", "user_id": str(bob["id"])}, follow_redirects=True)
with client() as c:
    sign_in(c, "Bob")
    r = c.get(f"/part/{rf_part['id']}/edit")
    check("sub-group membership grants edit across the library",
          r.status_code == 200, r.status_code)

section("name freezing")
with client() as c:
    sign_in(c, "Ada")
    r = c.post(f"/libraries/{rf['id']}/manage",
               data={"action": "rename", "name": "RF_Renamed"}, follow_redirects=True)
    check("rename refused once the library holds parts", b"would break the link" in r.data)

    # Create it through the UI so Ada actually owns it (a direct db call would leave
    # owner_id=0, and only a librarian could then administer it).
    c.post("/libraries/new", data={"name": "Scratch", "kind": "group"},
           follow_redirects=True)
    empty_id = {l["name"]: l for l in db.list_libraries()}["Scratch"]["id"]
    r = c.post(f"/libraries/{empty_id}/manage",
               data={"action": "rename", "name": "Scratch2"}, follow_redirects=True)
    check("rename allowed while empty", b"Library renamed" in r.data)

section("deprecation hides from KiCad but keeps the row")
conn = sqlite3.connect(config.DB_PATH)
view = db.get_library(passives["id"])["view"]
before = conn.execute(f'SELECT COUNT(*) FROM "{view}"').fetchone()[0]
conn.close()
with client() as c:
    sign_in(c, "Bob")
    c.post(f"/part/{bob_part['id']}/edit", data={
        "name": bob_part["name"], "category": "Resistor", "mpn": bob_part["mpn"],
        "deprecated": "1"}, content_type="multipart/form-data", follow_redirects=True)
conn = sqlite3.connect(config.DB_PATH)
after = conn.execute(f'SELECT COUNT(*) FROM "{view}"').fetchone()[0]
still_there = conn.execute("SELECT COUNT(*) FROM parts WHERE id = ?",
                           (bob_part["id"],)).fetchone()[0]
conn.close()
check("deprecated part drops out of the KiCad view", after == before - 1, f"{before}->{after}")
check("but the row still exists (schematics keep resolving)", still_there == 1)

section("slug stability across a rename")
with client() as c:
    sign_in(c, "Ada")
    c.post(f"/part/{rf_part['id']}/edit", data={
        "name": "Completely_Different_Name", "category": "Resistor", "mpn": "RF-PART-1"},
        content_type="multipart/form-data", follow_redirects=True)
after = db.get_part(rf_part["id"])
check("display name changed", after["name"] == "Completely_Different_Name", after["name"])
check("slug did NOT change (LIB_ID stays valid)", after["slug"] == rf_part["slug"],
      f"{rf_part['slug']} -> {after['slug']}")

section("bundle")
with client() as c:
    sign_in(c, "Ada")
    r = c.get("/api/bundle")
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = zf.namelist()
    check("bundle carries the generated .kicad_dbl", "LuGroupLib.kicad_dbl" in names, names)
    bundled = json.loads(zf.read("LuGroupLib.kicad_dbl"))
    check("bundled .kicad_dbl has every sub-library",
          len(bundled["libraries"]) == len(db.list_libraries()),
          [e["name"] for e in bundled["libraries"]])
    check("no app database in the bundle", not any("app.sqlite" in n for n in names))

finish()
