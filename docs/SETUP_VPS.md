# VPS setup (Ubuntu, 1 GB RAM)

The server runs only a Flask app + SQLite. No database server, no open DB port.

## 1. Install and run

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo mkdir -p /opt/hacklib && sudo chown $USER /opt/hacklib
git clone https://github.com/Geezson123/KiCad_Library_Hackathon /opt/hacklib
cd /opt/hacklib/server
python3 -m venv /opt/hacklib/venv
/opt/hacklib/venv/bin/pip install -r requirements.txt

# Smoke test (Ctrl-C to stop):
/opt/hacklib/venv/bin/python app.py
```

Visit `http://<VPS_IP>:8000` — you should see one seeded example part.

## 2. Run as a service (survives reboots)

```bash
sudo useradd -r -s /usr/sbin/nologin hacklib 2>/dev/null || true
sudo chown -R hacklib /opt/hacklib
sudo cp /opt/hacklib/deploy/hacklib.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hacklib
systemctl status hacklib --no-pager
```

Gunicorn with **1 worker** is intentional — it keeps memory to ~30–50 MB, which is
comfortable on a 1 GB VPS for a small group.

## 3. Firewall

Only the web port needs to be reachable by your group (the DB is never exposed):

```bash
sudo ufw allow 8000/tcp
sudo ufw enable
```

For a nicer setup put nginx in front on port 80/443 (optional; not required for the demo).

## 4. Health check

```bash
curl http://localhost:8000/api/health     # {"status":"ok","parts":N}
```

## Data & backups

Everything lives under `/opt/hacklib/library/` (the SQLite DB and all KiCad files). Back up
that one folder and you have backed up the whole library.

## Updating

```bash
cd /opt/hacklib && git pull
sudo systemctl restart hacklib
```
