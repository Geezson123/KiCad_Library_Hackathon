# Deployment plan

Rolling LuGroupLib out in two phases: a **Tailscale test server** first, then a **public
VPS**. The mechanics of each step live in [SETUP_VPS.md](SETUP_VPS.md); this is the
sequence and what to prove before moving on.

The reason for two phases isn't caution for its own sake. Several things in this system
have never been exercised against the real world, and it's much cheaper to find that out
on a server only you can reach.

---

## What has never actually run

Everything below is implemented and covered by tests, but the tests stub the external
service. The first real call is where a wrong assumption surfaces. Treat these as the
main risks of phase 1.

| Unverified | Why it might not work first time | Where it bites |
|------------|----------------------------------|----------------|
| **Slack OIDC** | Every test signed in through the dev-login bypass. The real flow involves Slack's redirect, scopes, and team check. | Nobody can sign in |
| **SQLite ODBC on Windows** | The driver **is not currently installed** on the development machine. The `.kicad_dbl` asks for the exact name `SQLite3 ODBC Driver`. | Library appears in KiCad with zero parts |
| **SQLite ODBC on macOS** | Needs unixODBC plus a separately built driver, and the name usually differs. Documented, never run — no Mac was available. | Mac users can't see the library |
| **Mouser Search API** | Field names came from a published client library, not from a live response. | "Add from Mouser link" returns empty fields |
| **Claude API** | Both calls are tested against a stubbed SDK. | AI drafting and receipt reading fail (they degrade rather than crash) |

None of these block the phase-1 install — they're what phase 1 is *for*.

---

## Phase 1 — Tailscale test server

**Goal:** prove the whole system works end to end, on a server nobody outside your
tailnet can reach.

Tailscale is a good fit for more than privacy: `tailscale serve` gives a real HTTPS
certificate on a `*.ts.net` hostname, and Slack requires HTTPS for OAuth redirect URLs.
So the Slack flow can be tested properly in this phase rather than deferred.

### Setup

1. [Install and configure](SETUP_VPS.md#1-install) the app on the VPS.
2. Set `LUGROUPLIB_SECRET` and `LUGROUPLIB_LIBRARIANS`.
3. [Expose it over Tailscale](SETUP_VPS.md#4a-expose-it-over-tailscale-test-server).
4. Note the `https://<machine>.<tailnet>.ts.net` URL — it's both the website address and
   the sync server URL.

> While Slack isn't configured yet you can set `LUGROUPLIB_DEV_LOGIN=1` to get in. It is
> genuinely safe *only* because the tailnet is private, and it must come out before
> phase 2. Every page shows a warning banner while it's on.

### Prove it works

Work down this list. Each item is one of the unverified rows above, or a thing that only
breaks with real users.

- [ ] **ODBC driver on your own machine.** Install it, then `python client/install.py
      --dry-run` reports it found. This is the single most common failure and it's worth
      clearing before anything else.
- [ ] **Installer.** Run `client/install.bat`. Confirm it registers `LuGroupLib`,
      `LuGroupLib_DB`, and the footprint library, and sets the path variables.
- [ ] **KiCad sees the library.** Press `A`; `LuGroupLib_DB → General` shows the seeded
      resistor with its fields. Place it and confirm the footprint and 3D model come with
      it.
- [ ] **Slack sign-in.** Configure the [Slack app](SETUP_VPS.md#5-slack-sign-in) with the
      `.ts.net` redirect URL. Sign in, confirm the ★ appears, then **unset
      `LUGROUPLIB_DEV_LOGIN`** and confirm you can still get in.
- [ ] **Somebody else signs in.** A second person proves the team restriction and that
      non-librarians get the right permissions.
- [ ] **Create the real libraries.** Decide the sub-group names *now*, with the people
      concerned — [names lock permanently](USER_GUIDE.md#creating-one) once a library
      holds its first part. This is the decision that's expensive to get wrong.
- [ ] **Add a part by hand,** sync on a second machine, confirm it appears.
- [ ] **Permissions.** Have a non-member try to add to a sub-group library and confirm
      they're refused.
- [ ] **Incremental sync.** Sync twice; the second should say "Already up to date."
- [ ] **Mouser lookup,** if you've set a key. Paste a real product URL and check the
      fields come back sensibly — this is where a wrong API field name shows up.
- [ ] **Receipt ingestion,** if AI is configured. Use a genuine Mouser order PDF.
- [ ] **A Mac user,** if the group has any. This is the biggest unknown; give it real
      time rather than assuming.
- [ ] **Restore from backup.** Take a backup, wipe, restore. An untested backup isn't one.

### Ready for phase 2 when

Everyone who needs the library can sign in, sync, and place a part from KiCad on their
own machine — including at least one Mac, if you have Macs.

---

## Phase 2 — Public VPS

**Goal:** same system, reachable without Tailscale.

### Setup

1. Fresh VPS, [same install](SETUP_VPS.md#1-install).
2. DNS record pointing at it.
3. [Caddy in front](SETUP_VPS.md#4b-expose-it-publicly-production) for TLS.
4. `LUGROUPLIB_HTTPS=1`.
5. Add the new redirect URL to the Slack app. You can keep both listed, so the test
   server keeps working.

### Migrating the data

Both databases move together, and the order matters — copy them while the service is
stopped.

```bash
# On the test server
sudo systemctl stop lugrouplib
sudo tar czf /tmp/lugrouplib-migrate.tgz \
    /opt/lugrouplib/library /opt/lugrouplib/server/app.sqlite
```

```bash
# On the new server, after installing but before first start
sudo tar xzf lugrouplib-migrate.tgz -C /
sudo chown -R lugrouplib /opt/lugrouplib
sudo systemctl start lugrouplib
```

Carrying `app.sqlite` across keeps user accounts, library memberships, sync tokens, and
stock history. Leaving it behind means everyone re-signs-in and re-issues tokens — the
library itself would survive, but the membership and audit trail would not.

### Cutover

- [ ] `LUGROUPLIB_DEV_LOGIN` is **not** set anywhere. Check `/etc/lugrouplib.env` and
      `systemctl show lugrouplib -p Environment`.
- [ ] `LUGROUPLIB_SECRET` is set and different from the test server's.
- [ ] `LUGROUPLIB_HTTPS=1`.
- [ ] `LUGROUPLIB_SLACK_TEAM_ID` is set — without it, **any** Slack account on earth can
      sign in.
- [ ] Port 8000 is not reachable from outside; only 80/443 are open.
- [ ] Sign-in works on the public URL.
- [ ] Nightly backups are running and a restore has been tested.
- [ ] Members update `client_config.json` to the new URL, or re-run `install.py`.

### After cutover

Keep the Tailscale box for a couple of weeks as a rollback, then retire it. Don't leave
it running indefinitely with `LUGROUPLIB_DEV_LOGIN` set and forgotten.

---

## Things worth deciding before phase 2

**Library names.** The single hardest thing to change later. A library name is baked into
every schematic symbol placed from it, and locks as soon as the library holds a part.

**Who the master librarians are.** At least two, so nobody is blocked when one is away.

**Whether AI features stay on.** Both cost money per call and both are optional. The
Mouser lookup is useful without AI; receipt reading isn't.

**Backup destination.** `/var/backups` on the same VPS protects against mistakes, not
against losing the VPS. Push the tarball somewhere else.

---

## Known gaps

Honest list of what isn't built, so nobody discovers it at an awkward moment.

- **No rate limiting.** A determined user could hammer `/api/bundle`. Fine for a lab
  behind Slack sign-in; worth adding if the group grows.
- **Read access is all-or-nothing.** Every signed-in member can see and sync every part
  in every library. Permissions govern writing only. This was a deliberate choice — say
  so if anyone assumes otherwise.
- **No web UI for granting master librarian.** It's the `LUGROUPLIB_LIBRARIANS`
  environment variable plus a restart.
- **Symbols are always manual.** Neither Mouser nor the AI produces `.kicad_sym` files.
- **Deleting a part breaks schematics that used it.** Deprecating exists precisely to
  avoid this; the UI warns, but nothing prevents it.
