"""Manage the on-disk KiCad artifacts that back each database row.

KiCad database libraries only store a *reference* to a symbol/footprint (e.g.
``HackLib:R_10K``). The real geometry lives in ``HackLib.kicad_sym`` and the
``HackLib.pretty`` folder. This module keeps those in sync with the DB:

* merge an uploaded ``.kicad_sym`` into the single aggregated symbol library
* copy an uploaded ``.kicad_mod`` into the footprint library
* copy an uploaded 3D model and point the footprint at it via ``${HACKLIB_3D}``
* build the download bundle (a zip of the whole ``library/`` directory)
"""
import os
import re
import shutil
import tempfile

from kiutils.symbol import SymbolLib
from kiutils.footprint import Footprint, Model

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


# ---------------------------------------------------------------------------
# footprints
# ---------------------------------------------------------------------------
def add_footprint_from_file(uploaded_path, desired_name=None, model_basename=None):
    """Copy an uploaded .kicad_mod into HackLib.pretty and normalise its 3D path.

    If ``model_basename`` is given, the footprint's 3D model is set to
    ``${HACKLIB_3D}/<model_basename>``. Any pre-existing model paths are rewritten
    to the same env-var-relative form so they resolve after a sync.

    Returns the final footprint name.
    """
    fp = Footprint.from_file(uploaded_path)
    base = desired_name or fp.entryName or os.path.splitext(os.path.basename(uploaded_path))[0]

    config.ensure_dirs()
    existing = {
        os.path.splitext(f)[0]
        for f in os.listdir(config.FOOTPRINTS_DIR)
        if f.endswith(".kicad_mod")
    }
    name = _unique(sanitize_name(base), existing)
    fp.entryName = name

    if model_basename:
        fp.models = [Model(path=f"${{HACKLIB_3D}}/{model_basename}")]
    else:
        for m in fp.models:
            m.path = f"${{HACKLIB_3D}}/{os.path.basename(m.path)}"

    out = os.path.join(config.FOOTPRINTS_DIR, name + ".kicad_mod")
    fp.to_file(out)
    return name


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
