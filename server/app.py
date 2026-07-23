"""LuGroupLib web app: browse parts, upload new parts, serve the sync bundle.

Run locally:   python app.py
Run on VPS:    gunicorn -w 1 -b 127.0.0.1:8000 app:app   (see docs/SETUP_VPS.md)
"""
import os
import secrets
import shutil
import tempfile

from flask import (
    Flask, render_template, request, redirect, url_for, flash, send_file, jsonify,
    abort, session,
)
from werkzeug.utils import secure_filename

import auth
import config
import csrf
import db
import dbl
import library

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB uploads

# Sessions authenticate users now, so a predictable key would let anyone forge one.
# Fall back to a random per-process key rather than a shared constant: that logs
# everyone out on restart, which is survivable, whereas a guessable key is not.
app.secret_key = os.environ.get("LUGROUPLIB_SECRET") or secrets.token_hex(32)
if not os.environ.get("LUGROUPLIB_SECRET"):
    app.logger.warning(
        "LUGROUPLIB_SECRET is not set - using a random key, so sessions will not "
        "survive a restart. Set it in production (see docs/SETUP_VPS.md)."
    )

# Session cookie hardening. SameSite=Lax alone blocks most cross-site form posts in
# current browsers; the CSRF tokens below are what make it hold regardless of browser.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("LUGROUPLIB_HTTPS", "") == "1",
)
csrf.init_app(app)

CATEGORIES = [
    "Resistor", "Capacitor", "Inductor", "Diode", "Transistor", "IC",
    "Connector", "Crystal/Oscillator", "Switch", "LED", "Module", "Other",
]


@app.context_processor
def inject_user():
    """Make the signed-in user and auth mode available to every template."""
    return {
        "current_user": auth.current_user(),
        "slack_enabled": config.slack_configured(),
        "dev_login": config.DEV_LOGIN,
        "lib_nickname": config.LIB_NICKNAME,
    }


# ---------------------------------------------------------------------------
# authentication
# ---------------------------------------------------------------------------
def _redirect_uri():
    return url_for("slack_callback", _external=True)


def _safe_next(target):
    """Only ever redirect to a path on this site, never an attacker-supplied host."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("browse")


@app.route("/login")
def login():
    if auth.current_user():
        return redirect(url_for("browse"))
    session["next"] = _safe_next(request.args.get("next", ""))
    if not config.slack_configured():
        # No Slack app configured yet: show the sign-in page, which explains how to
        # set it up and offers dev login when that is switched on.
        return render_template("login.html")
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    return redirect(auth.slack_authorize_url(_redirect_uri(), state))


@app.route("/auth/slack/callback")
def slack_callback():
    # The state parameter ties this callback to the /login that started it; without the
    # check, an attacker could feed us their own authorization code (login CSRF).
    expected = session.pop("oauth_state", None)
    if not expected or request.args.get("state") != expected:
        flash("Sign-in expired or was tampered with. Please try again.", "error")
        return redirect(url_for("login"))

    if request.args.get("error"):
        flash("Slack sign-in was cancelled.", "error")
        return redirect(url_for("browse"))

    try:
        profile = auth.slack_exchange(request.args.get("code", ""), _redirect_uri())
    except Exception as exc:  # noqa: BLE001 - show the reason rather than a 500
        flash(f"Slack sign-in failed: {exc}", "error")
        return redirect(url_for("browse"))

    user = auth.upsert_user(
        profile["slack_id"], profile["email"], profile["name"], profile["avatar_url"]
    )
    auth.login_user(user)
    flash(f"Signed in as {user['name']}.", "success")
    return redirect(_safe_next(session.pop("next", "")))


@app.route("/logout", methods=["POST"])
def logout():
    auth.logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("browse"))


@app.route("/dev-login", methods=["POST"])
def dev_login():
    """DEVELOPMENT ONLY - signs in as any name, with no credential of any kind.

    Gated on LUGROUPLIB_DEV_LOGIN=1 so it 404s unless deliberately switched on. It
    exists so the app is runnable before a Slack app has been registered.
    """
    if not config.DEV_LOGIN:
        abort(404)
    name = (request.form.get("name") or "").strip() or "Dev User"
    # Namespaced so a dev account can never collide with a real Slack id.
    user = auth.upsert_user(f"dev:{name.lower()}", f"{name.lower()}@dev.local", name)
    if request.form.get("librarian"):
        auth.set_librarian(user["id"], True)
        user = auth.get_user(user["id"])
    auth.login_user(user)
    flash(f"Signed in as {user['name']} (dev login).", "success")
    return redirect(url_for("browse"))

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
    auth.init_app_db()
    dbl.build()  # keep the .kicad_dbl in step with the libraries table
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
        # owner_id 0 = nobody: the seed part is editable only by a master librarian.
        "created_by": "seed",
        "owner_id": 0,
        "created_at": db.now_iso(),
    })


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.route("/")
def browse():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    library_id = request.args.get("library", "").strip()
    parts = db.list_parts(q, category, library_id or None)
    libraries = db.list_libraries()
    return render_template(
        "browse.html", parts=parts, q=q, category=category,
        categories=db.list_categories(), total=db.count_parts(),
        libraries=libraries, library_id=library_id,
        library_names={l["id"]: l["name"] for l in libraries},
    )


@app.route("/part/<int:part_id>")
def part_detail(part_id):
    part = db.get_part(part_id)
    if not part:
        abort(404)
    lib = db.get_library(part["library_id"])
    user = auth.current_user()
    editors = [auth.get_user(uid) for uid in auth.part_editor_ids(part_id)]
    return render_template(
        "part.html", part=part, lib=lib,
        can_edit=auth.can_edit_part(user, part, lib),
        editors=[e for e in editors if e],
        all_users=auth.list_users() if user else [],
    )


# ---------------------------------------------------------------------------
# libraries
# ---------------------------------------------------------------------------
@app.route("/libraries")
def libraries():
    user = auth.current_user()
    libs = db.list_libraries()
    for lib in libs:
        lib["can_add"] = auth.can_add_part(user, lib)
        lib["can_admin"] = auth.can_admin_library(user, lib)
    return render_template("libraries.html", libraries=libs)


@app.route("/libraries/new", methods=["GET", "POST"])
@auth.login_required
def new_library():
    if request.method == "GET":
        return render_template("library_new.html", kinds=db.KINDS)
    user = auth.current_user()
    try:
        lib_id = db.create_library(
            request.form.get("name", ""), request.form.get("kind", db.KIND_GROUP),
            request.form.get("description", ""), user["id"],
        )
    except db.LibraryNameError as exc:
        flash(str(exc), "error")
        return redirect(url_for("new_library"))
    dbl.build()
    flash("Library created. It appears in KiCad as a sub-library after the next sync.",
          "success")
    return redirect(url_for("library_detail", library_id=lib_id))


@app.route("/libraries/<int:library_id>")
def library_detail(library_id):
    lib = db.get_library(library_id)
    if not lib:
        abort(404)
    user = auth.current_user()
    members = [auth.get_user(uid) for uid in auth.member_ids(library_id)]
    return render_template(
        "library_detail.html", lib=lib,
        parts=db.list_parts(library_id=library_id),
        owner=auth.get_user(lib["owner_id"]),
        members=[m for m in members if m],
        all_users=auth.list_users() if user else [],
        can_admin=auth.can_admin_library(user, lib),
        can_add=auth.can_add_part(user, lib),
    )


@app.route("/libraries/<int:library_id>/manage", methods=["POST"])
@auth.login_required
def manage_library(library_id):
    lib = db.get_library(library_id)
    if not lib:
        abort(404)
    if not auth.can_admin_library(auth.current_user(), lib):
        abort(403)

    action = request.form.get("action", "")
    try:
        if action == "rename":
            db.rename_library(library_id, request.form.get("name", ""))
            dbl.build()
            flash("Library renamed.", "success")
        elif action == "delete":
            db.delete_library(library_id)
            dbl.build()
            flash("Library deleted.", "success")
            return redirect(url_for("libraries"))
        elif action == "add_member":
            auth.add_member(library_id, int(request.form["user_id"]))
            flash("Member added.", "success")
        elif action == "remove_member":
            auth.remove_member(library_id, int(request.form["user_id"]))
            flash("Member removed.", "success")
    except db.LibraryNameError as exc:
        flash(str(exc), "error")
    return redirect(url_for("library_detail", library_id=library_id))


@app.route("/part/<int:part_id>/editors", methods=["POST"])
@auth.login_required
def part_editors(part_id):
    part = db.get_part(part_id)
    if not part:
        abort(404)
    lib = db.get_library(part["library_id"])
    if not auth.can_edit_part(auth.current_user(), part, lib):
        abort(403)
    if request.form.get("action") == "remove":
        auth.remove_part_editor(part_id, int(request.form["user_id"]))
        flash("Editor removed.", "success")
    else:
        auth.add_part_editor(part_id, int(request.form["user_id"]))
        flash("Editor invited — they can now edit this part.", "success")
    return redirect(url_for("part_detail", part_id=part_id))


@app.route("/upload", methods=["GET", "POST"])
@auth.login_required
def upload():
    user = auth.current_user()
    allowed = [l for l in db.list_libraries() if auth.can_add_part(user, l)]

    if request.method == "GET":
        if not allowed:
            flash("You are not a member of any library yet. Create one, or ask a "
                  "library owner to add you.", "error")
            return redirect(url_for("libraries"))
        return render_template("upload.html", categories=CATEGORIES, libraries=allowed)

    f = request.form
    lib = db.get_library(f.get("library_id", type=int) or 0)
    if not lib:
        flash("Pick a library to upload into.", "error")
        return redirect(url_for("upload"))
    if not auth.can_add_part(user, lib):
        abort(403)
    symbol_file = request.files.get("symbol")
    footprint_file = request.files.get("footprint")
    model_file = request.files.get("model")

    if not symbol_file or not symbol_file.filename:
        flash("A symbol file (.kicad_sym) is required.", "error")
        return redirect(url_for("upload"))

    tmpdir = tempfile.mkdtemp(prefix="lugrouplib_up_")
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
            # created_by is a denormalised display name so browsing needs no join into
            # the (deliberately separate) app database; owner_id is authoritative.
            "created_by": user["name"],
            "owner_id": user["id"],
            "library_id": lib["id"],
            "created_at": db.now_iso(),
        })
        flash(f"Added part #{part_id} ({sym_name}). Sync KiCad to see it.", "success")
        return redirect(url_for("part_detail", part_id=part_id))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route("/part/<int:part_id>/edit", methods=["GET", "POST"])
@auth.login_required
def edit_part(part_id):
    part = db.get_part(part_id)
    if not part:
        abort(404)
    lib = db.get_library(part["library_id"])
    if not auth.can_edit_part(auth.current_user(), part, lib):
        abort(403)
    if request.method == "GET":
        return render_template("edit.html", part=part, lib=lib, categories=CATEGORIES)

    f = request.form
    symbol_file = request.files.get("symbol")
    footprint_file = request.files.get("footprint")
    model_file = request.files.get("model")

    symbols_val = part["symbols"]
    footprints_val = part["footprints"]
    model_val = part["model3d"]

    tmpdir = tempfile.mkdtemp(prefix="lugrouplib_edit_")
    try:
        # --- new 3D model (optional) ---
        new_model = None
        if model_file and model_file.filename:
            mdl_path = os.path.join(tmpdir, secure_filename(model_file.filename))
            model_file.save(mdl_path)
            new_model = library.add_model_file(mdl_path)

        # --- new footprint (optional): replaces the old one ---
        if footprint_file and footprint_file.filename:
            fp_path = os.path.join(tmpdir, secure_filename(footprint_file.filename))
            footprint_file.save(fp_path)
            try:
                fp_name = library.add_footprint_from_file(
                    fp_path, model_basename=new_model or library.ref_name(model_val) or None
                )
            except Exception as exc:  # noqa: BLE001
                flash(f"Could not read footprint file: {exc}", "error")
                return redirect(url_for("edit_part", part_id=part_id))
            old_fp = library.ref_name(footprints_val)
            if old_fp and old_fp != fp_name and not db.asset_in_use(
                "footprints", footprints_val, exclude_id=part_id
            ):
                library.remove_footprint(old_fp)
            footprints_val = f"{config.LIB_NICKNAME}:{fp_name}"
        elif new_model:
            # Footprint unchanged but a new 3D model was uploaded — relink it.
            library.relink_model(library.ref_name(footprints_val), new_model)

        # --- 3D model bookkeeping / cleanup ---
        if new_model:
            if model_val and model_val != new_model and not db.asset_in_use(
                "model3d", model_val, exclude_id=part_id
            ):
                library.remove_model(model_val)
            model_val = new_model

        # --- new symbol (optional): replaces the old one ---
        if symbol_file and symbol_file.filename:
            sym_path = os.path.join(tmpdir, secure_filename(symbol_file.filename))
            symbol_file.save(sym_path)
            try:
                sym_name = library.add_symbol_from_file(sym_path)
            except Exception as exc:  # noqa: BLE001
                flash(f"Could not read symbol file: {exc}", "error")
                return redirect(url_for("edit_part", part_id=part_id))
            old_sym = library.ref_name(symbols_val)
            if old_sym and old_sym != sym_name and not db.asset_in_use(
                "symbols", symbols_val, exclude_id=part_id
            ):
                library.remove_symbol(old_sym)
            symbols_val = f"{config.LIB_NICKNAME}:{sym_name}"

        new_name = db.update_part(part_id, {
            "name": f.get("name", "").strip(),
            "category": f.get("category", "").strip(),
            "mpn": f.get("mpn", "").strip(),
            "manufacturer": f.get("manufacturer", "").strip(),
            "value": f.get("value", "").strip(),
            "description": f.get("description", "").strip(),
            "datasheet": f.get("datasheet", "").strip(),
            "keywords": f.get("keywords", "").strip(),
            "symbols": symbols_val,
            "footprints": footprints_val,
            "model3d": model_val,
            "deprecated": 1 if f.get("deprecated") else 0,
        })
        flash(f"Updated part #{part_id} ({new_name}). Sync to update KiCad.", "success")
        return redirect(url_for("part_detail", part_id=part_id))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route("/part/<int:part_id>/delete", methods=["POST"])
@auth.login_required
def delete_part(part_id):
    part = db.get_part(part_id)
    if not part:
        abort(404)
    if not auth.can_edit_part(auth.current_user(), part, db.get_library(part["library_id"])):
        abort(403)
    # Remove backing assets only if no other part still references them.
    if not db.asset_in_use("symbols", part["symbols"], exclude_id=part_id):
        library.remove_symbol(library.ref_name(part["symbols"]))
    if not db.asset_in_use("footprints", part["footprints"], exclude_id=part_id):
        library.remove_footprint(library.ref_name(part["footprints"]))
    if not db.asset_in_use("model3d", part["model3d"], exclude_id=part_id):
        library.remove_model(part["model3d"])
    db.delete_part(part_id)
    flash(f"Deleted part #{part_id} ({part['name']}). Sync to remove it from your "
          f"computer (restart KiCad to clear footprints).", "success")
    return redirect(url_for("browse"))


@app.route("/tokens", methods=["GET", "POST"])
@auth.login_required
def tokens():
    """Issue and revoke the API tokens the sync client and KiCad plugin authenticate with."""
    user = auth.current_user()
    fresh = None
    if request.method == "POST":
        if request.form.get("revoke"):
            auth.revoke_token(user["id"], int(request.form["revoke"]))
            flash("Token revoked. Any machine using it will stop syncing.", "success")
        else:
            fresh = auth.issue_token(user["id"], request.form.get("label", ""))
            flash("Token created — copy it now, it is not shown again.", "success")
    return render_template("tokens.html", tokens=auth.list_tokens(user["id"]), fresh=fresh)


@app.route("/api/bundle")
def api_bundle():
    """Return a zip of the whole library/ folder for the sync client.

    Authenticated by an API token (Authorization: Bearer, or ?token=) or a browser
    session. Read access is deliberately all-or-nothing: every member sees every
    part, so there is one bundle rather than one per user.
    """
    if auth.bundle_user() is None:
        # 401 + WWW-Authenticate so the sync client can report "bad token" rather than
        # silently unzipping an HTML login page.
        return jsonify({
            "error": "authentication required",
            "detail": "Create a sync token at /tokens and put it in your client config.",
        }), 401, {"WWW-Authenticate": "Bearer"}
    # Regenerate rather than trusting that whatever last touched the libraries table
    # remembered to. The bundle is the only copy anyone downstream ever sees, so it is
    # the right place to guarantee the .kicad_dbl matches the database.
    dbl.build()
    zip_path = library.build_bundle_zip()
    return send_file(
        zip_path, as_attachment=True, download_name="lugrouplib_bundle.zip",
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
        debug=os.environ.get("LUGROUPLIB_DEBUG", "1") == "1",
        use_reloader=False,
    )
