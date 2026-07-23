#!/usr/bin/env python3
"""CSRF: forged requests are blocked, legitimate ones still work, and the token-
authenticated sync client is correctly exempt."""
import re

from harness import check, finish, section, setup

webapp, config, db = setup()


def scrape_token(html):
    """Pull the token out of a rendered form, exactly as a browser would."""
    m = re.search(r'name="_csrf" value="([^"]+)"', html)
    return m.group(1) if m else None


section("token is rendered into forms")
with webapp.app.test_client() as c:
    html = c.get("/login").data.decode()
    tok = scrape_token(html)
    check("login form carries a CSRF token", bool(tok), html[:200])
    check("token is high-entropy", tok and len(tok) > 30, tok)

section("the legitimate path still works")
with webapp.app.test_client() as c:
    tok = scrape_token(c.get("/login").data.decode())
    r = c.post("/dev-login", data={"name": "Ada", "_csrf": tok}, follow_redirects=True)
    check("sign-in succeeds with a valid token", b"Ada" in r.data)

    # A real form on a real page, submitted normally.
    tok = scrape_token(c.get("/libraries/new").data.decode())
    r = c.post("/libraries/new",
               data={"name": "Legit", "kind": "group", "_csrf": tok},
               follow_redirects=True)
    check("library creation succeeds with a valid token", b"Library created" in r.data)

section("forged requests are rejected")
with webapp.app.test_client() as c:
    tok = scrape_token(c.get("/login").data.decode())
    c.post("/dev-login", data={"name": "Ada", "_csrf": tok}, follow_redirects=True)

    # This is the attack: the victim is signed in (cookie is sent automatically), but
    # the attacker's page cannot read the session to learn the token.
    r = c.post("/libraries/new", data={"name": "Forged", "kind": "group"})
    check("POST with NO token is rejected", r.status_code == 400, r.status_code)

    r = c.post("/libraries/new",
               data={"name": "Forged2", "kind": "group", "_csrf": "guessed-wrong"})
    check("POST with a WRONG token is rejected", r.status_code == 400, r.status_code)

    r = c.post("/logout")
    check("even sign-out is protected", r.status_code == 400, r.status_code)

    names = [l["name"] for l in webapp.db.list_libraries()]
    check("no forged library was created",
          "Forged" not in names and "Forged2" not in names, names)

section("destructive routes are covered")
with webapp.app.test_client() as c:
    tok = scrape_token(c.get("/login").data.decode())
    c.post("/dev-login", data={"name": "Dave", "librarian": "1", "_csrf": tok},
           follow_redirects=True)
    part_id = webapp.db.list_parts()[0]["id"]
    r = c.post(f"/part/{part_id}/delete")
    check("part deletion without a token is rejected", r.status_code == 400, r.status_code)
    check("the part still exists", webapp.db.get_part(part_id) is not None)

section("bearer-token callers are exempt")
with webapp.app.test_client() as c:
    tok = scrape_token(c.get("/login").data.decode())
    c.post("/dev-login", data={"name": "Ada", "_csrf": tok}, follow_redirects=True)
    user = [u for u in webapp.auth.list_users() if u["name"] == "Ada"][0]
    api_token = webapp.auth.issue_token(user["id"], "test")

with webapp.app.test_client() as c:
    # The sync client authenticates by header, which a browser will not attach
    # cross-site, so CSRF does not apply to it. GET today, but Stage 5 adds POSTs.
    r = c.get("/api/bundle", headers={"Authorization": "Bearer " + api_token})
    check("bundle still works for the sync client", r.status_code == 200, r.status_code)

section("expired session gives a redirect, not a bare 400")
with webapp.app.test_client() as c:
    # No session at all -> looks like a logged-out user, not an attack.
    r = c.post("/libraries/new", data={"name": "X", "kind": "group"})
    check("no-session POST redirects to sign in",
          r.status_code == 302 and "/login" in r.headers.get("Location", ""),
          f"{r.status_code} {r.headers.get('Location')}")

section("cookie hardening")
cfg = webapp.app.config
check("session cookie is HttpOnly", cfg["SESSION_COOKIE_HTTPONLY"] is True)
check("session cookie is SameSite=Lax", cfg["SESSION_COOKIE_SAMESITE"] == "Lax")
check("Secure flag is opt-in via LUGROUPLIB_HTTPS",
      cfg["SESSION_COOKIE_SECURE"] is False)

finish()
