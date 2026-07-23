#!/usr/bin/env python3
"""Stage 5: incremental sync.

Runs the app on a real socket rather than through Flask's test client, so the client's
actual urllib code path -- headers, streaming downloads, 401 handling -- is what gets
exercised.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request

from harness import REPO_ROOT, check, finish, make_client, section, setup

webapp, config, db = setup()

sys.path.insert(0, os.path.join(REPO_ROOT, "client"))
import lugrouplib_core as core  # noqa: E402

from werkzeug.serving import make_server  # noqa: E402

TMP = tempfile.mkdtemp(prefix="lgl_sync_")
LOCAL = os.path.join(TMP, "KiCad_LuGroupLib")

# --- serve the app on a real port -------------------------------------------------
server = make_server("127.0.0.1", 0, webapp.app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"

# A token, created directly -- the token UI itself is covered in test_auth.py.
user = webapp.auth.upsert_user("dev:sync", "sync@dev.local", "Sync Tester")
TOKEN = webapp.auth.issue_token(user["id"], "test")


def sign_in(client, name):
    client.post("/dev-login", data={"name": name}, follow_redirects=True)


def upload_part(mpn, library_id):
    c = make_client(webapp)
    sign_in(c, "Sync Tester")
    with open(os.path.join(REPO_ROOT, "examples", "R_10K.kicad_sym"), "rb") as fh:
        sym = fh.read()
    with open(os.path.join(REPO_ROOT, "examples", "R_0603.kicad_mod"), "rb") as fh:
        fp = fh.read()
    return c.post("/upload", data={
        "library_id": str(library_id), "category": "Resistor", "mpn": mpn,
        "value": "10K", "symbol": (io.BytesIO(sym), "R_10K.kicad_sym"),
        "footprint": (io.BytesIO(fp), "R_0603.kicad_mod"),
    }, content_type="multipart/form-data", follow_redirects=True)


def fetch(path, token=TOKEN):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    return urllib.request.urlopen(req, timeout=15)


library_id = db.list_libraries()[0]["id"]

section("manifest")
with fetch("/api/manifest") as r:
    files = json.loads(r.read().decode())["files"]
check("manifest lists the KiCad database", "lugrouplib.sqlite" in files, sorted(files))
check("manifest lists the generated .kicad_dbl", "LuGroupLib.kicad_dbl" in files)
check("manifest uses forward slashes on every platform",
      all("\\" not in p for p in files), [p for p in files if "\\" in p])
check("hashes look like sha256",
      all(len(h) == 64 for h in files.values()))
check("manifest never exposes the identity database",
      not any("app.sqlite" in p for p in files), sorted(files))

section("bundle-vs-incremental policy")
# Tested directly rather than by varying library size: this library has only a handful
# of files, so a real first install here legitimately stays incremental.
check("large first install uses the bundle", core.should_use_bundle(300, 300))
check("most-of-library change uses the bundle", core.should_use_bundle(200, 300))
check("one changed file stays incremental", not core.should_use_bundle(1, 300))
check("a third of the library stays incremental", not core.should_use_bundle(100, 300))
check("a small library stays incremental even when fully missing",
      not core.should_use_bundle(7, 7))
check("nothing to do never triggers a bundle", not core.should_use_bundle(0, 300))

section("first install")
result = core.sync(BASE, LOCAL, token=TOKEN)
check("everything arrived", result["added"] == len(files), result)
check("files landed on disk", os.path.isfile(os.path.join(LOCAL, "lugrouplib.sqlite")))
check("bytes were actually transferred", result["bytes"] > 0, result)

section("a second sync transfers nothing")
result = core.sync(BASE, LOCAL, token=TOKEN)
check("switched to incremental", result["mode"] == "incremental", result)
check("nothing added", result["added"] == 0, result)
check("nothing updated", result["updated"] == 0, result)
check("no bytes transferred", result["bytes"] == 0, result)
check("everything counted as unchanged", result["unchanged"] == len(files), result)
check("summary says so", core.describe(result) == "Already up to date.", core.describe(result))

section("adding a part transfers only what changed")
upload_part("NEW-PART-0001", library_id)
result = core.sync(BASE, LOCAL, token=TOKEN)
moved = result["added"] + result["updated"]
check("incremental path used", result["mode"] == "incremental", result)
check("something transferred", moved > 0, result)
check("only a handful of files moved, not the whole library",
      moved < result["unchanged"], result)
check("the new footprint arrived",
      any(n.startswith("R_0603") for n in
          os.listdir(os.path.join(LOCAL, "footprints", "LuGroupLib.pretty"))),
      os.listdir(os.path.join(LOCAL, "footprints", "LuGroupLib.pretty")))

section("local corruption repairs itself")
sym_path = os.path.join(LOCAL, "symbols", "LuGroupLib.kicad_sym")
with open(sym_path, "w", encoding="utf-8") as fh:
    fh.write("corrupted\n")
result = core.sync(BASE, LOCAL, token=TOKEN)
check("the damaged file was re-fetched", result["updated"] >= 1, result)
check("contents restored", open(sym_path, encoding="utf-8").read() != "corrupted\n")

section("server-side deletion prunes locally")
part = [p for p in db.list_parts() if p["mpn"] == "NEW-PART-0001"][0]
before = os.listdir(os.path.join(LOCAL, "footprints", "LuGroupLib.pretty"))
c = make_client(webapp)
sign_in(c, "Sync Tester")
c.post(f"/part/{part['id']}/delete", follow_redirects=True)
result = core.sync(BASE, LOCAL, token=TOKEN)
after = os.listdir(os.path.join(LOCAL, "footprints", "LuGroupLib.pretty"))
check("a local file was removed", result["deleted"] >= 1, result)
check("the footprint really is gone", len(after) < len(before), (before, after))

section("path traversal is refused")
for attack in ("../server/app.sqlite", "..%2Fserver%2Fapp.sqlite",
               "....//server/app.sqlite", "/etc/passwd"):
    try:
        with fetch("/api/file/" + attack) as r:
            body = r.read()
        blocked = False
    except urllib.error.HTTPError as exc:
        blocked = exc.code in (400, 403, 404)
    except Exception:
        blocked = True
    check(f"refused: {attack}", blocked)

section("a legitimate file still downloads")
with fetch("/api/file/lugrouplib.sqlite") as r:
    blob = r.read()
check("served the real database", blob[:15] == b"SQLite format 3", blob[:15])

section("authentication")
for path in ("/api/manifest", "/api/file/lugrouplib.sqlite"):
    try:
        fetch(path, token=None)
        denied = False
    except urllib.error.HTTPError as exc:
        denied = exc.code == 401
    check(f"401 without a token: {path}", denied)

try:
    core.sync(BASE, os.path.join(TMP, "nope"), token="bogus-token")
    raised = False
except core.AuthError as exc:
    raised = "/tokens" in str(exc)
except Exception:
    raised = False
check("a bad token raises AuthError pointing at /tokens", raised)

section("forcing a full sync")
result = core.sync(BASE, LOCAL, token=TOKEN, full=True)
check("full=True uses the bundle", result["mode"] == "bundle", result)

server.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
finish()
