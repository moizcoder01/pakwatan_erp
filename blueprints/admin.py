"""
blueprints/admin.py
--------------------
Admin-only privileged account operations (password resets, etc.)
that require the Supabase service-role key. Kept separate from
roles.py, which is read-only and uses the normal session client.
"""

from flask import Blueprint, redirect, url_for, flash, request
from decorators import login_required, roles_required
from supabase_client import get_admin_client

admin_bp = Blueprint("admin", __name__)

MIN_PASSWORD_LENGTH = 6


@admin_bp.route("/users/<user_id>/change-password", methods=["POST"])
@login_required
@roles_required("Admin")
def change_password(user_id):
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not new_password or not confirm_password:
        flash("Both password fields are required.", "error")
        return redirect(url_for("roles.index"))

    if new_password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("roles.index"))

    if len(new_password) < MIN_PASSWORD_LENGTH:
        flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.", "error")
        return redirect(url_for("roles.index"))

    try:
        admin_client = get_admin_client()
        admin_client.auth.admin.update_user_by_id(
            user_id, {"password": new_password}
        )
        flash("Password updated successfully.", "success")
    except Exception as e:
        # Don't leak internal error detail beyond what's useful — Supabase
        # errors here are typically safe (weak password, user not found, etc.)
        flash(f"Failed to update password: {str(e)}", "error")

    return redirect(url_for("roles.index"))