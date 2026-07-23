#!/usr/bin/env python3
"""Stage 1: authentication gating, dev sign-in, API tokens, and the privacy boundary
between the KiCad library database and the identity database."""
import io
import os
import zipfile

from harness import check, finish, make_client, section, setup

webapp, config, db = setup()


def client():
    return make_client(webapp)


section("anonymous access")
with client() as c:
    r = c.get("/")
    check("browse is public", r.status_code == 200, f"got {r.status_code}")

    r = c.get("/upload")
    check("upload redirects to login", r.status_code == 302 and "/login" in r.headers["Location"],
          f"got {r.status_code} -> {r.headers.get('Location')}")

    r = c.post("/part/1/delete")
    check("delete redirects to login", r.status_code == 302 and "/login" in r.headers["Location"],
          f"got {r.status_code}")

    r = c.get("/api/bundle")
    check("bundle is 401 without a token", r.status_code == 401, f"got {r.status_code}")
    check("401 body is JSON, not an HTML login page",
          r.is_json and "authentication" in r.get_json().get("error", ""))

    r = c.get("/login")
    check("login page renders", r.status_code == 200 and b"Developer sign-in" in r.data)

section("dev sign-in")
with client() as c:
    r = c.post("/dev-login", data={"name": "Ada"}, follow_redirects=True)
    check("dev login succeeds", r.status_code == 200 and b"Ada" in r.data)

    r = c.get("/upload")
    check("upload reachable once signed in", r.status_code == 200, f"got {r.status_code}")
    check("upload no longer asks for a typed name", b'name="created_by"' not in r.data)

    r = c.get("/api/bundle")
    check("bundle works with a session", r.status_code == 200, f"got {r.status_code}")

    # Issue a token, then use it from a *fresh* client with no session at all.
    r = c.post("/tokens", data={"label": "lab desktop"}, follow_redirects=True)
    check("token page issues a token", r.status_code == 200 and b"Your new token" in r.data)
    body = r.data.decode("utf-8")
    token = body.split('<pre class="token mono">')[1].split("</pre>")[0].strip()
    check("token looks like a secret", len(token) > 30, token[:12])

    r = c.post("/logout", follow_redirects=True)
    check("sign out works", r.status_code == 200 and b"Signed out" in r.data)

section("token auth (no session)")
with client() as c:
    r = c.get("/api/bundle", headers={"Authorization": "Bearer " + token})
    check("bearer header is accepted", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        zf = zipfile.ZipFile(io.BytesIO(r.data))
        names = zf.namelist()
        check("bundle contains the KiCad database", "lugrouplib.sqlite" in names)
        check("bundle does NOT contain the app database",
              not any("app.sqlite" in n for n in names), str(names))

    r = c.get("/api/bundle?token=" + token)
    check("?token= query param is accepted", r.status_code == 200, f"got {r.status_code}")

    r = c.get("/api/bundle", headers={"Authorization": "Bearer totally-wrong"})
    check("a bad token is rejected", r.status_code == 401, f"got {r.status_code}")

section("privacy boundary")
import config  # noqa: E402
check("app db lives outside the bundled library dir",
      os.path.abspath(config.LIBRARY_DIR) not in os.path.abspath(config.APP_DB_PATH),
      config.APP_DB_PATH)

finish()
