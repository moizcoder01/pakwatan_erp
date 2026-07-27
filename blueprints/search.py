"""
blueprints/search.py
---------------------
Universal global search across Guards, Clients, and Incidents.

NOTE ON "Incidents": Phase 1's schema has a client-facing ticket system
called `complaints` (client_id, complaint_details, resolution_status) —
there isn't a separate "incidents" table. This route treats that table
as the Incidents category. If a distinct internal incident-report table
(e.g. patrol-logged security events, separate from client complaints)
is wanted, that's a quick addition in a later phase — flagging the
assumption here rather than guessing silently.

Role scoping:
  - Admin / Ops : search across everything.
  - Client      : results limited to their own client record, guards
                   assigned to them, and complaints they raised.
"""

from flask import Blueprint, render_template, request, session

from decorators import login_required
from supabase_client import get_session_client

search_bp = Blueprint("search", __name__)

MIN_QUERY_LENGTH = 2
RESULT_LIMIT = 10


def _search_guards(client, term, client_id=None):
    query = (
        client.table("guards")
        .select("id, full_name, cnic, phone, city, duty_status, assigned_client_id")
        .or_(f"full_name.ilike.%{term}%,cnic.ilike.%{term}%,phone.ilike.%{term}%")
        .limit(RESULT_LIMIT)
    )
    if client_id:
        query = query.eq("assigned_client_id", client_id)
    try:
        return query.execute().data or []
    except Exception:
        return []


def _search_clients(client, term, client_id=None):
    query = (
        client.table("clients")
        .select("id, client_name, contact_person, phone, city, status")
        .or_(f"client_name.ilike.%{term}%,contact_person.ilike.%{term}%,phone.ilike.%{term}%")
        .limit(RESULT_LIMIT)
    )
    if client_id:
        query = query.eq("id", client_id)
    try:
        return query.execute().data or []
    except Exception:
        return []


def _search_complaints(client, term, client_id=None):
    query = (
        client.table("complaints")
        .select("id, complaint_details, resolution_status, logged_at, clients(client_name), guards(full_name)")
        .ilike("complaint_details", f"%{term}%")
        .limit(RESULT_LIMIT)
    )
    if client_id:
        query = query.eq("client_id", client_id)
    try:
        return query.execute().data or []
    except Exception:
        return []


@search_bp.route("/search")
@login_required
def index():
    user = session["user"]
    term = request.args.get("q", "").strip()

    guards, clients_found, complaints = [], [], []

    if len(term) >= MIN_QUERY_LENGTH:
        supa = get_session_client()
        scoping_client_id = user.get("client_id") if user["role"] == "Client" else None

        guards = _search_guards(supa, term, scoping_client_id)
        clients_found = _search_clients(supa, term, scoping_client_id)
        complaints = _search_complaints(supa, term, scoping_client_id)

    return render_template(
        "search_results.html",
        term=term,
        query_too_short=(0 < len(term) < MIN_QUERY_LENGTH),
        guards=guards,
        clients_found=clients_found,
        complaints=complaints,
    )
