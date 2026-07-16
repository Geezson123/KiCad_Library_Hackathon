"""Central paths and constants for the HackLib server.

The whole system revolves around a single ``library/`` directory that is BOTH the
web app's store and the KiCad-facing library bundle. The download "sync" is just a
zip of this directory, so every artifact KiCad needs lives under LIBRARY_DIR.
"""
import os

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SERVER_DIR)

# Allow override so the app can be relocated on the VPS without code changes.
LIBRARY_DIR = os.environ.get(
    "HACKLIB_LIBRARY_DIR", os.path.join(REPO_ROOT, "library")
)

# KiCad-facing artifacts (all inside the synced bundle)
DB_PATH = os.path.join(LIBRARY_DIR, "hacklib.sqlite")
SYMBOLS_LIB = os.path.join(LIBRARY_DIR, "symbols", "HackLib.kicad_sym")
FOOTPRINTS_DIR = os.path.join(LIBRARY_DIR, "footprints", "HackLib.pretty")
MODELS_DIR = os.path.join(LIBRARY_DIR, "3dmodels")
DBL_FILE = os.path.join(LIBRARY_DIR, "HackLib.kicad_dbl")

# Example seed assets (real, placeable parts so the demo is never empty)
EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")

# The single nickname every part is filed under. Keeps the KiCad symbol/footprint
# library tables to one entry each.
LIB_NICKNAME = "HackLib"

# .kicad_sym format version written by kiutils. KiCad auto-migrates older versions.
SYMLIB_VERSION = "20211014"


def ensure_dirs():
    """Create the managed library directory tree if it does not exist yet."""
    for path in (
        LIBRARY_DIR,
        os.path.dirname(SYMBOLS_LIB),
        FOOTPRINTS_DIR,
        MODELS_DIR,
    ):
        os.makedirs(path, exist_ok=True)
