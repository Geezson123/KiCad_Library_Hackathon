"""Shared scaffolding for the LuGroupLib verification suites.

Plain scripts rather than pytest: the project deliberately carries no development
dependencies (the sync client is stdlib-only by design), and these run the same way
on a maintainer's laptop and on the VPS.

Run one suite directly, or all of them with ``python tests/run_all.py``.

Every suite runs against throwaway copies of BOTH databases. That is not just tidiness:
creating a library writes to ``library/lugrouplib.sqlite``, so a suite that isolates only
the app database will quietly add test rows to the real KiCad library.
"""
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_ROOT, "server")

CSRF_TOKEN = "test-csrf-token"

_results = {"passed": [], "failed": []}


def isolate():
    """Point the app at throwaway databases. Returns the temp directory."""
    tmp = tempfile.mkdtemp(prefix="lgl_test_")
    # Copy the real library so migrations are exercised against genuine data.
    shutil.copytree(os.path.join(REPO_ROOT, "library"), os.path.join(tmp, "library"))
    os.environ["LUGROUPLIB_LIBRARY_DIR"] = os.path.join(tmp, "library")
    os.environ["LUGROUPLIB_APP_DB"] = os.path.join(tmp, "app.sqlite")
    os.environ["LUGROUPLIB_DEV_LOGIN"] = "1"
    os.environ["LUGROUPLIB_SECRET"] = "test-secret"
    if SERVER_DIR not in sys.path:
        sys.path.insert(0, SERVER_DIR)
    return tmp


def setup():
    """Isolate, import the server, and hand back the modules a suite needs."""
    isolate()
    import app as webapp
    import config
    import db
    webapp.app.config["TESTING"] = True
    return webapp, config, db


def section(title):
    print(f"\n== {title} ==")


def check(label, cond, detail=""):
    _results["passed" if cond else "failed"].append(label)
    suffix = f"  -- {detail}" if detail and not cond else ""
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{suffix}")


def make_client(webapp):
    """Test client that carries a CSRF token, the way a rendered form does.

    Forgery itself is covered in test_csrf.py, which scrapes real tokens out of real
    pages; here the token is just part of an otherwise legitimate request.
    """
    c = webapp.app.test_client()
    with c.session_transaction() as s:
        s["_csrf_token"] = CSRF_TOKEN
    _post = c.post

    def post(*args, **kwargs):
        data = kwargs.get("data")
        if data is None:
            data = kwargs["data"] = {}
        if isinstance(data, dict):
            data.setdefault("_csrf", CSRF_TOKEN)
        return _post(*args, **kwargs)

    c.post = post
    return c


def finish():
    """Print the tally and exit non-zero if anything failed."""
    passed, failed = _results["passed"], _results["failed"]
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    sys.exit(1 if failed else 0)


def counts():
    return len(_results["passed"]), len(_results["failed"])
