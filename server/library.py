"""Manage the on-disk KiCad artifacts that back each database row.

KiCad database libraries only store a *reference* to a symbol/footprint (e.g.
``HackLib:R_10K``). The real geometry lives in ``HackLib.kicad_sym`` and the
``HackLib.pretty`` folder. This module keeps those in sync with the DB:

* merge an uploaded ``.kicad_sym`` into the single aggregated symbol library
* copy an uploaded ``.kicad_mod`` into the footprint library (verbatim)
* copy an uploaded 3D model and point the footprint at it via ``${HACKLIB_3D}``
* build the download bundle (a zip of the whole ``library/`` directory)

Footprints are copied byte-for-byte (only the 3D model path is rewritten). We do NOT
round-trip them through kiutils: vendor footprints are frequently in the legacy KiCad-5
``(module …)`` format, and re-serializing them drops the version header / mangles arcs so
KiCad refuses to load the result. KiCad reads legacy footprints natively, so a verbatim
copy is the most compatible option.
"""
import os
import re
import shutil
import tempfile

from kiutils.symbol import SymbolLib

import config

MODEL_EXTS = (".step", ".stp", ".stpz", ".wrl", ".wings")


# ---------------------------------------------------------------------------
# name helpers
# ---------------------------------------------------------------------------
def sanitize_name(name):
    """KiCad-safe library item name: keep it simple and space-free."""
    name = (name or "").strip()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^A-Za-z0-9_.+\-]", "", name)
    return name or "part"


def _unique(name, existing):
    if name not in existing:
        return name
    i = 2
    while f"{name}_{i}" in existing:
        i += 1
    return f"{name}_{i}"


# ---------------------------------------------------------------------------
# symbols
# ---------------------------------------------------------------------------
def _load_symlib():
    if os.path.exists(config.SYMBOLS_LIB):
        return SymbolLib.from_file(config.SYMBOLS_LIB)
    lib = SymbolLib(version=config.SYMLIB_VERSION, generator="hacklib")
    lib.filePath = config.SYMBOLS_LIB
    return lib


def add_symbol_from_file(uploaded_path, desired_name=None):
    """Merge the first symbol from ``uploaded_path`` into HackLib.kicad_sym.

    Returns the final (possibly de-duplicated) symbol name.
    """
    incoming = SymbolLib.from_file(uploaded_path)
    if not incoming.symbols:
        raise ValueError("No symbols found in the uploaded .kicad_sym file.")
    sym = incoming.symbols[0]

    lib = _load_symlib()
    existing = {s.entryName for s in lib.symbols}
    old_name = sym.entryName
    new_name = _unique(sanitize_name(desired_name or old_name), existing)

    # Rename the parent and any child unit symbols (kiutils stores unit sub-symbols
    # whose entryName is prefixed with the parent name, e.g. "R_10K_0_1").
    if old_name:
        for unit in sym.units:
            if unit.entryName and unit.entryName.startswith(old_name):
                unit.entryName = new_name + unit.entryName[len(old_name):]
    sym.entryName = new_name
    sym.libraryNickname = None

    lib.symbols.append(sym)
    config.ensure_dirs()
    lib.to_file(config.SYMBOLS_LIB)
    return new_name


def remove_symbol(name):
    """Remove a symbol (by entryName) from the aggregated HackLib.kicad_sym."""
    if not name or not os.path.exists(config.SYMBOLS_LIB):
        return
    lib = SymbolLib.from_file(config.SYMBOLS_LIB)
    lib.symbols = [s for s in lib.symbols if s.entryName != name]
    lib.to_file(config.SYMBOLS_LIB)


def ref_name(ref):
    """Return the bare item name from a 'HackLib:Name' reference (or '' if empty)."""
    if not ref:
        return ""
    return ref.split(":", 1)[1] if ":" in ref else ref


# ---------------------------------------------------------------------------
# 3D models
# ---------------------------------------------------------------------------
def add_model_file(uploaded_path, desired_filename=None):
    """Copy a 3D model into 3dmodels/. Returns the stored basename."""
    config.ensure_dirs()
    base = desired_filename or os.path.basename(uploaded_path)
    name, ext = os.path.splitext(base)
    base = sanitize_name(name) + ext.lower()
    existing = set(os.listdir(config.MODELS_DIR))
    if base in existing:
        stem, ext = os.path.splitext(base)
        base = _unique(stem, {os.path.splitext(e)[0] for e in existing}) + ext
    shutil.copyfile(uploaded_path, os.path.join(config.MODELS_DIR, base))
    return base


def remove_model(basename):
    """Delete a 3D model file from 3dmodels/."""
    if not basename:
        return
    path = os.path.join(config.MODELS_DIR, basename)
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# footprints
# ---------------------------------------------------------------------------
# Matches a `(model <path> …)` opening, capturing the path token (quoted or bareword).
_MODEL_RE = re.compile(r'(\(model\s+)("[^"]*"|[^\s()]+)')


def _rewrite_model_paths(text, model_basename):
    """Point every 3D model reference at ``${HACKLIB_3D}/<basename>`` so it resolves
    on any machine after a sync, regardless of the vendor's original path."""
    def repl(match):
        raw = match.group(2).strip('"')
        base = model_basename or os.path.basename(raw.replace("\\", "/"))
        return '%s"${HACKLIB_3D}/%s"' % (match.group(1), base)
    return _MODEL_RE.sub(repl, text)


def _apply_model(text, model_basename):
    """Rewrite existing model paths, or insert a model block if there is none."""
    if "(model" in text:
        return _rewrite_model_paths(text, model_basename)
    if model_basename:
        idx = text.rstrip().rfind(")")
        if idx != -1:
            block = (
                '  (model "${HACKLIB_3D}/%s"\n'
                "    (offset (xyz 0 0 0))\n"
                "    (scale (xyz 1 1 1))\n"
                "    (rotate (xyz 0 0 0))\n  )\n" % model_basename
            )
            return text[:idx] + block + text[idx:]
    return text


def _read_text(path):
    raw = open(path, "rb").read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def add_footprint_from_file(uploaded_path, desired_name=None, model_basename=None):
    """Copy an uploaded .kicad_mod into HackLib.pretty verbatim, rewriting only the 3D
    model path. Works for both modern ``(footprint …)`` and legacy ``(module …)`` files.

    If ``model_basename`` is given it becomes the model path; otherwise any existing model
    reference is rewritten to ``${HACKLIB_3D}/<its basename>``. Returns the footprint name
    (which is the file name KiCad shows in the library).
    """
    config.ensure_dirs()
    base = desired_name or os.path.splitext(os.path.basename(uploaded_path))[0]
    existing = {
        os.path.splitext(f)[0]
        for f in os.listdir(config.FOOTPRINTS_DIR)
        if f.endswith(".kicad_mod")
    }
    name = _unique(sanitize_name(base), existing)

    text = _apply_model(_read_text(uploaded_path), model_basename)

    out = os.path.join(config.FOOTPRINTS_DIR, name + ".kicad_mod")
    # newline="" prevents Windows from doubling CR in CRLF files (\r\n -> \r\r\n), which
    # would corrupt vendor footprints saved with Windows line endings.
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return name


def remove_footprint(name):
    """Delete a footprint file from HackLib.pretty."""
    if not name:
        return
    path = os.path.join(config.FOOTPRINTS_DIR, name + ".kicad_mod")
    if os.path.exists(path):
        os.remove(path)


def relink_model(footprint_name, model_basename):
    """Repoint an existing footprint's 3D model at ``${HACKLIB_3D}/<model_basename>``.

    Used on edit when a new 3D model is uploaded but the footprint is unchanged.
    """
    if not footprint_name:
        return
    path = os.path.join(config.FOOTPRINTS_DIR, footprint_name + ".kicad_mod")
    if not os.path.exists(path):
        return
    text = _apply_model(_read_text(path), model_basename)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# bundle
# ---------------------------------------------------------------------------
def build_bundle_zip():
    """Zip the entire library/ directory. Returns the path to the created .zip.

    Entries are stored relative to LIBRARY_DIR so extracting the zip into the
    client's local folder drops HackLib.kicad_dbl, hacklib.sqlite, symbols/, etc.
    directly in place.
    """
    tmp_base = os.path.join(tempfile.gettempdir(), "hacklib_bundle")
    zip_path = shutil.make_archive(tmp_base, "zip", root_dir=config.LIBRARY_DIR)
    return zip_path
