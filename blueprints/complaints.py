"""
blueprints/complaints.py
-------------------------
Client Complaints Ticket System.

Routes:
  - GET  /complaints/                : List all complaints with resolution status filtering
  - GET/POST /complaints/add         : Log a new client complaint
  - GET/POST /complaints/update/<id> : View a complaint & update its resolution status
"""

from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash
from decorators import login_required
from supabase_client import get_session_client

complaints_bp = Blueprint("complaints", __name__)


def _get_active_clients(client):
    try:
        res = client.table("clients").select("id, client_name").order("client_name").execute()
        return res.data or []
    except Exception:
        return []


def _get_active_guards(client):
    try:
        res = (
            client.table("guards")
            .select("id, full_name")
            .eq("is_active", True)
            .order("full_name")
            .execute()
        )
        return res.data or []
    except Exception:
        return []


@complaints_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()

    query = client.table("complaints").select(
        "id, complaint_details, logged_at, resolution_status, resolved_at, "
        "resolution_notes, clients(client_name), guards(full_name)"
    ).order("logged_at", desc=True)

    if status_filter:
        query = query.eq("resolution_status", status_filter)

    try:
        res = query.execute()
        complaints = res.data or []
    except Exception as e:
        flash(f"Error loading complaints: {str(e)}", "error")
        complaints = []

    counts = {"All": 0, "Unresolved": 0, "Resolved": 0}
    try:
        all_res = client.table("complaints").select("resolution_status").execute()
        all_complaints = all_res.data or []
        counts["All"] = len(all_complaints)
        for c in all_complaints:
            st = c.get("resolution_status")
            if st in counts:
                counts[st] += 1
    except Exception:
        pass

    return render_template(
        "complaints/index.html",
        complaints=complaints,
        status_filter=status_filter,
        counts=counts,
    )


@complaints_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    client = get_session_client()

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        guard_id = request.form.get("guard_id", "").strip() or None
        complaint_details = request.form.get("complaint_details", "").strip()

        if not client_id or not complaint_details:
            flash("Client and Complaint Details are required.", "error")
            clients = _get_active_clients(client)
            guards = _get_active_guards(client)
            return render_template(
                "complaints/add.html", clients=clients, guards=guards, form_data=request.form
            )

        payload = {
            "client_id": client_id,
            "guard_id": guard_id,
            "complaint_details": complaint_details,
            "resolution_status": "Unresolved",
        }

        try:
            client.table("complaints").insert(payload).execute()
            flash("Complaint ticket logged successfully.", "success")
            return redirect(url_for("complaints.index"))
        except Exception as e:
            flash(f"Failed to log complaint: {str(e)}", "error")
            clients = _get_active_clients(client)
            guards = _get_active_guards(client)
            return render_template(
                "complaints/add.html", clients=clients, guards=guards, form_data=request.form
            )

    clients = _get_active_clients(client)
    guards = _get_active_guards(client)
    return render_template("complaints/add.html", clients=clients, guards=guards, form_data={})


@complaints_bp.route("/update/<complaint_id>", methods=["GET", "POST"])
@login_required
def update(complaint_id):
    client = get_session_client()

    try:
        res = client.table("complaints").select(
            "id, complaint_details, logged_at, resolution_status, resolved_at, "
            "resolution_notes, client_id, guard_id, clients(client_name), guards(full_name)"
        ).eq("id", complaint_id).execute()
        complaint = res.data[0] if res.data else None
    except Exception as e:
        flash(f"Error loading complaint: {str(e)}", "error")
        return redirect(url_for("complaints.index"))

    if not complaint:
        flash("Complaint record not found.", "error")
        return redirect(url_for("complaints.index"))

    if request.method == "POST":
        resolution_status = request.form.get("resolution_status", "").strip() or "Unresolved"
        resolution_notes = request.form.get("resolution_notes", "").strip() or None

        payload = {
            "resolution_status": resolution_status,
            "resolution_notes": resolution_notes,
            # DB constraint requires resolved_at set when Resolved, null otherwise.
            "resolved_at": datetime.now(timezone.utc).isoformat() if resolution_status == "Resolved" else None,
        }

        try:
            client.table("complaints").update(payload).eq("id", complaint_id).execute()
            flash("Complaint status updated successfully.", "success")
            return redirect(url_for("complaints.index"))
        except Exception as e:
            flash(f"Failed to update complaint: {str(e)}", "error")

    return render_template("complaints/update.html", complaint=complaint)