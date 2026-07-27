"""
decorators.py
-------------
Route guards for Phase 2 authentication and role-based access control.

- @login_required        -> any logged-in user (Admin, Ops, or Client)
- @roles_required(...)   -> only the listed roles may proceed; everyone
                             else gets a 403 (if logged in) or is sent
                             to the login screen (if not).
"""

from functools import wraps
from flask import session, redirect, url_for, flash, abort, request


def current_user():
    """Returns the logged-in user's session dict, or None."""
    return session.get("user")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*allowed_roles):
    """
    Usage: @roles_required("Admin", "Ops")
    Must be stacked UNDER @login_required (or it implies login itself).
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.path))
            if user.get("role") not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
