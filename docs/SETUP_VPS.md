# VPS setup

How to install and run the LuGroupLib server. For *when* to do which parts of this, see
the [deployment plan](DEPLOYMENT.md) — it covers the Tailscale test server first and the
public VPS after.

Target: Ubuntu 22.04+ with 1 GB RAM. The app is Flask plus two SQLite files — no database
server, nothing listening on a database port.

---

## 1. Install

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
```

```bash
sudo mkdir -p /opt/lugrouplib && sudo chown "$USER" /opt/lugrouplib
git clone https://github.com/Geezson123/KiCad_Library_Hackathon /opt/lugrouplib
python3 -m venv /opt/lugrouplib/venv
/opt/lugrouplib/venv/bin/pip install -r /opt/lugrouplib/server/requirements.txt
```

## 2. Configure

Secrets go in an environment file, not in the systemd unit (which is world-readable and
tracked in git).

```bash
sudo install -m 600 -o root -g root /opt/lugrouplib/deploy/lugrouplib.env.example /etc/lugrouplib.env
sudo nano /etc/lugrouplib.env
```

At minimum set `LUGROUPLIB_SECRET`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

The file itself documents every other variable. The ones that matter first:

- **`LUGROUPLIB_SLACK_*`** — sign-in. Covered in [section 5](#5-slack-sign-in).
- **`LUGROUPLIB_LIBRARIANS`** — your own Slack user ID. Without this, nobody is a master
  librarian and there's no one who can promote anyone.
- **`LUGROUPLIB_HTTPS=1`** — once TLS is in front.

## 3. Run as a service

```bash
sudo useradd -r -s /usr/sbin/nologin lugrouplib 2>/dev/null || true
sudo chown -R lugrouplib /opt/lugrouplib
sudo cp /opt/lugrouplib/deploy/lugrouplib.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lugrouplib
systemctl status lugrouplib --no-pager
```

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expect `{"parts":1,"status":"ok"}`.

The unit binds to **127.0.0.1** deliberately. Something in front terminates TLS, so the
app is never directly reachable. Pick one of the next two sections for that.

## 4a. Expose it over Tailscale (test server)

Tailscale gives you a real HTTPS certificate on your tailnet without opening a single
port to the internet — which also satisfies Slack's requirement that OAuth redirect URLs
use HTTPS.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

In the [Tailscale admin console](https://login.tailscale.com/admin/dns), enable
**MagicDNS** and **HTTPS Certificates** for the tailnet. Then:

```bash
sudo tailscale serve --bg 8000
```

```bash
tailscale serve status
```

That publishes `https://<machine>.<tailnet>.ts.net` to everyone on your tailnet, proxying
to the app on localhost. Members install Tailscale, join the tailnet, and use that URL —
the same one goes in `client_config.json` for sync.

> **Do not run `tailscale funnel`.** That publishes to the whole internet, which is
> exactly what this phase is avoiding.

No firewall rules are needed: nothing is listening publicly.

## 4b. Expose it publicly (production)

Point a DNS record at the VPS, then let Caddy handle TLS:

```bash
sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
lugrouplib.example.edu {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
sudo ufw allow 80,443/tcp && sudo ufw enable
```

Caddy obtains and renews a Let's Encrypt certificate automatically. Port 8000 stays
closed — only Caddy talks to the app.

Set `LUGROUPLIB_HTTPS=1` in `/etc/lugrouplib.env` and restart, so session cookies are
marked Secure.

## 5. Slack sign-in

1. Create an app at <https://api.slack.com/apps> → **From scratch**, in your lab
   workspace.
2. **OAuth & Permissions → Redirect URLs**, add exactly:
   `https://<your-host>/auth/slack/callback`
   Slack requires HTTPS here — which is why sections 4a and 4b both set up TLS.
3. **User Token Scopes**: `openid`, `profile`, `email`.
4. Copy the **Client ID** and **Client Secret** into `/etc/lugrouplib.env`.
5. Set `LUGROUPLIB_SLACK_TEAM_ID` to your workspace ID, so only your workspace can sign
   in.
6. Set `LUGROUPLIB_LIBRARIANS` to your Slack user ID (Slack profile → **Copy member ID**).

```bash
sudo systemctl restart lugrouplib
```

Sign in once and confirm a ★ appears next to your name — that's master librarian.

> The redirect URL must match the host members actually use. If you move from a Tailscale
> hostname to a public domain, add the new URL to the Slack app (you can list both).

## 6. Optional features

Both degrade gracefully when unset — the app runs fine without either.

- **`LUGROUPLIB_MOUSER_KEY`** — free from <https://www.mouser.com/api-hub/>. Enables
  "Add from Mouser link".
- **`ANTHROPIC_API_KEY`** — enables AI metadata drafting and receipt reading.

At lab volume the AI features cost roughly **$5–6 a year**, so the model is a quality
knob rather than a cost one. If you want to compare anyway, `LUGROUPLIB_AI_MODEL` takes
any of `claude-opus-4-8` (default), `claude-sonnet-5`, or `claude-haiku-4-5` — the app
adjusts its request parameters per model, so no code change is needed. Restart the
service and the review screens name the model that produced each draft, so you can
judge the difference on your own parts instead of on benchmarks.

## 7. Backups

Two files matter, and they are not interchangeable:

| Path | Contents | If you lose it |
|------|----------|----------------|
| `/opt/lugrouplib/library/` | Every part, symbol, footprint, 3D model, and stock count | The library is gone |
| `/opt/lugrouplib/server/app.sqlite` | Users, tokens, memberships, stock history | Everyone re-signs-in and re-issues tokens; library survives |

```bash
sudo tar czf /var/backups/lugrouplib-$(date +%F).tgz \
    /opt/lugrouplib/library /opt/lugrouplib/server/app.sqlite
```

A nightly cron job of that line is enough. SQLite files are copied safely this way as
long as the service is idle-ish; for a lab-sized group that's fine, but if you want
guarantees, `sudo systemctl stop lugrouplib` first.

Members' machines each hold a full copy of the library, so a lost server can be
reconstructed from any synced laptop — but nothing else can be, so back up anyway.

## 8. Updating

```bash
cd /opt/lugrouplib && sudo -u lugrouplib git pull
sudo /opt/lugrouplib/venv/bin/pip install -r server/requirements.txt
sudo systemctl restart lugrouplib
```

Database migrations run automatically at startup. Take a backup first anyway.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Service won't start | `journalctl -u lugrouplib -n 50 --no-pager` |
| 502 from Caddy/Tailscale | App isn't running, or isn't on 127.0.0.1:8000 |
| Sign-in loops back to the login page | Redirect URL in the Slack app doesn't exactly match the host you're using |
| "Sign-in expired or was tampered with" | Usually a stale tab after a restart. If persistent, `LUGROUPLIB_SECRET` is unset, so the key changes each restart |
| Everyone logged out after a deploy | Same cause — set `LUGROUPLIB_SECRET` |
| Nobody is a librarian | `LUGROUPLIB_LIBRARIANS` was empty at first sign-in. Set it and sign in again |
| Sync clients get 401 | Their token was revoked, or `app.sqlite` was restored from a backup that predates it |
