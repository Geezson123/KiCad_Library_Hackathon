"""Cross-site request forgery protection.

Sessions are cookie-borne, which means the browser attaches them to *any* request it
makes to this origin -- including one triggered by a form on someone else's page. So a
malicious page could, while a librarian is signed in, silently POST to
/part/7/delete or /libraries/3/manage. CSRF tokens close that: the attacker's page can
cause the request but cannot read our session to learn the token to put in it.

Enforced with a global ``before_request`` hook rather than a per-route decorator, so a
new state-changing route is protected by default and would have to opt *out*. Getting
this wrong fails closed (a rejected request) rather than open.
"""
import hmac
import secrets

from flask import session, request, abort, flash, redirect, url_for
from markupsafe import Markup

FIELD = "_csrf"
SESSION_KEY = "_csrf_token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def token():
    """The session's CSRF token, created on first use."""
    if SESSION_KEY not in session:
        session[SESSION_KEY] = secrets.token_urlsafe(32)
    return session[SESSION_KEY]


def input_tag():
    """Hidden field to drop inside every POST form: ``{{ csrf_input() }}``."""
    return Markup(f'<input type="hidden" name="{FIELD}" value="{token()}">')


def _uses_bearer_token():
    """True when the caller authenticated with an Authorization header.

    Such a request carries no ambient credential -- a browser will not attach the
    header on a cross-site form post -- so CSRF does not apply. Deliberately checks
    only the header and not the ``?token=`` query parameter, which an attacker could
    put in their own form's action URL.
    """
    return request.headers.get("Authorization", "").startswith("Bearer ")


def protect():
    if request.method not in UNSAFE_METHODS or _uses_bearer_token():
        return None

    expected = session.get(SESSION_KEY, "")
    if not expected:
        # No token in the session at all: it expired, or the server restarted with a
        # fresh secret key. That is an ordinary logged-out user, not an attack, so send
        # them to sign in rather than showing a bare 400.
        flash("Your session expired. Please sign in and try again.", "error")
        return redirect(url_for("login"))

    sent = request.form.get(FIELD) or request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(str(expected), str(sent)):
        abort(400, "CSRF token missing or invalid. Reload the page and try again.")
    return None


def init_app(app):
    app.before_request(protect)
    app.jinja_env.globals["csrf_input"] = input_tag
    app.jinja_env.globals["csrf_token"] = token
