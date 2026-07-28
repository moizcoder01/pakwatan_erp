"""
blueprints/roles.py
--------------------
User Roles & Access — read-only view (Admin only).

Displays every user profile provisioned via Supabase Auth + the `profiles`
table (see auth.py, which reads full_name/role/client_id/is_active from
this same table at login). Create/edit/deactivate workflows are a later
phase — for now this gives Admins visibility into who has ERP access.
"""

from flask import Blueprint, render_template, flash
from decorators import login_required, roles_required
from supabase_client import get_session_client

roles_bp = Blueprint("roles", __name__)


@roles_bp.route("/")
@login_required
@roles_required("Admin")
def index():
    client = get_session_client()

    try:
        res = client.table("profiles").select("*").execute()
        profiles = res.data or []
    except Exception as e:
        flash(f"Error loading user profiles: {str(e)}", "error")
        profiles = []

    # Map client_id -> client_name for any Client-role profiles
    client_names = {}
    try:
        clients_res = client.table("clients").select("id, client_name").execute()
        client_names = {c["id"]: c["client_name"] for c in (clients_res.data or [])}
    except Exception:
        pass

    return render_template(
        "roles/index.html",
        profiles=profiles,
        client_names=client_names,
    )