"""
blueprints/auth.py
-------------------
Login / logout and session management, backed by Supabase Auth.

Flow:
  1. User submits email + password on /login.
  2. We call supabase.auth.sign_in_with_password(...).
  3. On success, we look up their role/full_name/client_id from the
     `profiles` table (created in schema_phase2.sql).
  4. We store a small, signed-cookie session containing the user's id,
     email, role, full_name, client_id, and the Supabase access/refresh
     tokens — NOT the password.
  5. Every subsequent request can rebuild a user-scoped Supabase client
     from those tokens via supabase_client.get_session_client().
"""

from datetime import timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from supabase_client import get_anon_client
from config import SESSION_LIFETIME_MINUTES

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user"):
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or url_for("dashboard.index")

        if not email or not password:
            flash("Email and password are both required.", "error")
            return render_template("login.html", next=next_url)

        client = get_anon_client()
        try:
            auth_response = client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:  # noqa: BLE001 - surface auth errors to the login form
            flash(f"Login failed: {exc}", "error")
            return render_template("login.html", next=next_url)

        supa_user = auth_response.user
        supa_session = auth_response.session
        if not supa_user or not supa_session:
            flash("Login failed: invalid email or password.", "error")
            return render_template("login.html", next=next_url)

        # Look up this user's role/profile (created automatically by the
        # handle_new_user trigger from schema_phase2.sql).
        profile_result = (
            client.table("profiles")
            .select("full_name, role, client_id, is_active")
            .eq("id", supa_user.id)
            .single()
            .execute()
        )
        profile = profile_result.data

        if not profile:
            flash(
                "Login succeeded but no ERP profile was found for this account. "
                "Ask an Admin to provision your role.",
                "error",
            )
            return render_template("login.html", next=next_url)

        if not profile.get("is_active", True):
            flash("This account has been deactivated. Contact an Admin.", "error")
            return render_template("login.html", next=next_url)

        session.permanent = True
        session["user"] = {
            "id": supa_user.id,
            "email": supa_user.email,
            "full_name": profile.get("full_name") or supa_user.email,
            "role": profile.get("role", "Ops"),
            "client_id": profile.get("client_id"),
        }
        session["supabase_tokens"] = {
            "access_token": supa_session.access_token,
            "refresh_token": supa_session.refresh_token,
        }

        flash(f"Welcome back, {session['user']['full_name']}.", "success")
        return redirect(next_url)

    next_url = request.args.get("next") or url_for("dashboard.index")
    return render_template("login.html", next=next_url)


@auth_bp.route("/logout")
def logout():
    tokens = session.get("supabase_tokens")
    if tokens:
        try:
            client = get_anon_client()
            client.auth.sign_out()
        except Exception:
            pass  # best-effort — we clear the local session regardless

    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("auth.login"))


def init_session_lifetime(app):
    """Called once from app.py to make Flask sessions expire after inactivity."""
    app.permanent_session_lifetime = timedelta(minutes=SESSION_LIFETIME_MINUTES)
