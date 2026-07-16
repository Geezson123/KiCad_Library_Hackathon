# Demo script — 7/17

Goal: **upload a part in the web GUI → click Sync on the Windows laptop → the part appears
in KiCad.**

## The day before (rehearse this end to end at least once)

- [ ] VPS running the app ([SETUP_VPS.md](SETUP_VPS.md)); `curl .../api/health` returns ok.
- [ ] Demo laptop fully set up per [SETUP_KICAD.md](SETUP_KICAD.md):
      **64-bit SQLite ODBC driver installed**, Python installed, `client_config.json`
      pointing at the VPS, env vars + symbol/footprint/database libraries registered.
- [ ] Run `sync.bat` once; open KiCad and confirm the seeded **R_10K** resistor shows in
      the Symbol Chooser under `HackLib_DB → Parts` and places with its footprint.
- [ ] Have a fresh part ready to upload (files + metadata) so you're not authoring during
      the demo. A second resistor value works great; `examples/` files can be reused.

## Live demo (about 3 minutes)

1. **Show the library.** Open the web GUI in a browser → the Browse page lists existing
   parts. Search to show filtering.
2. **Upload a part.** Click **Upload part**, fill in Category/MPN/Value/etc., attach the
   `.kicad_sym`, `.kicad_mod`, and `.step/.wrl` files, submit. The part detail page shows
   its `HackLib:` symbol/footprint references.
3. **Sync on the laptop.** Switch to the Windows laptop, double-click **`sync.bat`**. It
   reports the files it pulled.
4. **Show it in KiCad.** In the Symbol Chooser, click **Refresh** (or it's already open) →
   the new part appears under `HackLib_DB → Parts` with its fields. Place it on the
   schematic; point out that the footprint (and 3D model) came along automatically.

## One-liner for the audience

> "The web app manages the SQLite database *and* the actual KiCad symbol/footprint/3D
> files together. Sync is one click because the whole library ships as one bundle — and
> the VPS only runs a tiny Flask app, so it's happy on 1 GB of RAM."

## If something goes wrong (fallbacks)

- **Sync fails / network flaky:** you already synced the day before; just show the seeded
  part flow in KiCad. Or run `sync.bat --server http://VPS_IP:8000`.
- **KiCad doesn't show the new part:** click **Refresh** in the chooser, or restart KiCad.
- **ODBC/database error on the laptop:** the driver isn't the 64-bit `SQLite3 ODBC
  Driver` — this is why we install and test it the day before.
- **Total server outage:** the browser GUI and KiCad both work off local/synced data for
  the KiCad half; demo the upload GUI from a locally-run server (`python app.py`).
