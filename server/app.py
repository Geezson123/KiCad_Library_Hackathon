"""HackLib web app: browse parts, upload new parts, serve the sync bundle.

Run locally:   python app.py
Run on VPS:    gunicorn -w 1 -b 127.0.0.1:8000 app:app   (see docs/SETUP_VPS.md)
"""
import os
import tempfile

from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_file, jsonify,
    abort,
)
from werkzeug.utils import secure_filename

import config
import db
import library

app = Flask(__name__)
app.secret_key = os.environ.get("HACKLIB_SECRET", "hacklib-demo-secret")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB uploads

CATEGORIES = [
    "Resistor", "Capacitor", "Inductor", "Diode", "Transistor", "IC",
    "Connector", "Crystal/Oscillator", "Switch", "LED", "Module", "Other",
]


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------
def seed_if_empty():
    """Load a real example resistor so browse/demo is never empty."""
    db.init_db()
    if db.count_parts() > 0:
        return
    sym = os.path.join(config.EXAMPLES_DIR, "R_10K.kicad_sym")
    fp = os.path.join(config.EXAMPLES_DIR, "R_0603.kicad_mod")
    mdl = os.path.join(config.EXAMPLES_DIR, "R_0603.wrl")
    if not (os.path.exists(sym) and os.path.exists(fp)):
        return
    sym_name = library.add_symbol_from_file(sym, "R_10K")
    model_name = library.add_model_file(mdl) if os.path.exists(mdl) else ""
    fp_name = library.add_footprint_from_file(fp, "R_0603", model_name or None)
    db.insert_part({
        "category": "Resistor",
        "mpn": "RC0603FR-0710KL",
        "manufacturer": "Yageo",
        "value": "10K",
        "description": "10 kOhm +/-1% 0.1W 0603 chip resistor",
        "datasheet": "https://www.yageo.com/upload/media/product/productsearch/datasheet/rchip/PYu-RC_Group_51_RoHS_L_12.pdf",
        "keywords": "resistor 10k 0603 smd",
        "symbols": f"{config.LIB_NICKNAME}:{sym_name}",
        "footprints": f"{config.LIB_NICKNAME}:{fp_name}",
        "model3d": model_name,
        "created_by": "seed",
        "created_at": db.now_iso(),
    })


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.route("/")
def browse():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    parts = db.list_parts(q, category)
    return render_template(
        "browse.html", parts=parts, q=q, category=category,
        categories=db.list_categories(), total=db.count_parts(),
    )


@app.route("/part/<int:part_id>")
def part_detail(part_id):
    part = db.get_part(part_id)
    if not part:
        abort(404)
    return render_template("part.html", part=part)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_template("upload.html", categories=CATEGORIES)

    f = request.form
    symbol_file = request.files.get("symbol")
    footprint_file = request.files.get("footprint")
    model_file = request.files.get("model")

    if not symbol_file or not symbol_file.filename:
        flash("A symbol file (.kicad_sym) is required.", "error")
        return redirect(url_for("upload"))

    tmpdir = tempfile.mkdtemp(prefix="hacklib_up_")
    try:
        # --- symbol (required) ---
        sym_path = os.path.join(tmpdir, secure_filename(symbol_file.filename))
        symbol_file.save(sym_path)
        try:
            sym_name = library.add_symbol_from_file(sym_path)
        except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
            flash(f"Could not read symbol file: {exc}", "error")
            return redirect(url_for("upload"))

        # --- 3D model (optional) ---
        model_name = ""
        if model_file and model_file.filename:
            mdl_path = os.path.join(tmpdir, secure_filename(model_file.filename))
            model_file.save(mdl_path)
            model_name = library.add_model_file(mdl_path)

        # --- footprint (optional) ---
        fp_ref = ""
        if footprint_file and footprint_file.filename:
            fp_path = os.path.join(tmpdir, secure_filename(footprint_file.filename))
            footprint_file.save(fp_path)
            try:
                fp_name = library.add_footprint_from_file(
                    fp_path, model_basename=model_name or None
                )
                fp_ref = f"{config.LIB_NICKNAME}:{fp_name}"
            except Exception as exc:  # noqa: BLE001
                flash(f"Could not read footprint file: {exc}", "error")
                return redirect(url_for("upload"))

        part_id = db.insert_part({
            "category": f.get("category", "").strip(),
            "mpn": f.get("mpn", "").strip(),
            "manufacturer": f.get("manufacturer", "").strip(),
            "value": f.get("value", "").strip(),
            "description": f.get("description", "").strip(),
            "datasheet": f.get("datasheet", "").strip(),
            "keywords": f.get("keywords", "").strip(),
            "symbols": f"{config.LIB_NICKNAME}:{sym_name}",
            "footprints": fp_ref,
            "model3d": model_name,
            "created_by": f.get("created_by", "").strip() or "anonymous",
            "created_at": db.now_iso(),
        })
        flash(f"Added part #{part_id} ({sym_name}). Sync KiCad to see it.", "success")
        return redirect(url_for("part_detail", part_id=part_id))
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route("/api/bundle")
def api_bundle():
    """Return a zip of the whole library/ folder for the sync client."""
    zip_path = library.build_bundle_zip()
    return send_file(
        zip_path, as_attachment=True, download_name="hacklib_bundle.zip",
        mimetype="application/zip",
    )


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "parts": db.count_parts()})


# Ensure the schema exists and the demo seed is present on import so the app works
# under gunicorn (which never executes the __main__ block below).
try:
    seed_if_empty()
except Exception as _exc:  # noqa: BLE001 - never let seeding break startup
    app.logger.warning("seed skipped: %s", _exc)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        debug=os.environ.get("HACKLIB_DEBUG", "1") == "1",
        use_reloader=False,
    )
