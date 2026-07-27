"""
blueprints/deployments.py
-------------------------
Guard Deployment & Shift Scheduling Matrix Module.

Routes:
  - GET  /deployments/               : Active deployments matrix joining Guards and Clients
  - GET/POST /deployments/assign     : Form to assign a Guard to a Client site with Day/Night shift
  - GET/POST /deployments/release/<id>: End/release a deployment shift & update guard status
"""

from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from decorators import login_required
from supabase_client import get_session_client

deployments_bp = Blueprint("deployments", __name__)


def _get_guards_and_clients(client):
    """Fetch active/available guards and active clients for assignment dropdowns."""
    guards = []
    clients_list = []
    try:
        g_res = client.table("guards").select("id, guard_id, full_name, status, verification_status").order("full_name").execute()
        guards = g_res.data or []
    except Exception:
        pass

    try:
        c_res = client.table("clients").select("id, client_name, company_name, status").order("client_name").execute()
        clients_list = c_res.data or []
    except Exception:
        pass

    return guards, clients_list


@deployments_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()
    shift_filter = request.args.get("shift", "").strip()

    query = client.table("deployments").select(
        "id, guard_id, client_id, shift_type, start_date, end_date, status, created_at, guards(id, guard_id, full_name, phone, status), clients(id, client_name, address)"
    ).order("created_at", desc=True)

    if status_filter:
        query = query.eq("status", status_filter)
    if shift_filter:
        query = query.eq("shift_type", shift_filter)

    try:
        res = query.execute()
        deployments_list = res.data or []
    except Exception as e:
        flash(f"Error loading deployment roster: {str(e)}", "error")
        deployments_list = []

    # Calculate status summary counters
    counts = {
        "All": 0,
        "Active": 0,
        "Completed": 0,
        "Reassigned": 0,
        "Day": 0,
        "Night": 0,
    }
    try:
        all_res = client.table("deployments").select("status, shift_type").execute()
        all_deps = all_res.data or []
        counts["All"] = len(all_deps)
        for d in all_deps:
            st = d.get("status")
            sf = d.get("shift_type")
            if st in counts:
                counts[st] += 1
            if sf in counts:
                counts[sf] += 1
    except Exception:
        pass

    return render_template(
        "deployments/index.html",
        deployments=deployments_list,
        status_filter=status_filter,
        shift_filter=shift_filter,
        counts=counts,
    )


@deployments_bp.route("/assign", methods=["GET", "POST"])
@login_required
def assign():
    client = get_session_client()

    if request.method == "POST":
        guard_id = request.form.get("guard_id", "").strip()
        client_id = request.form.get("client_id", "").strip()
        shift_type = request.form.get("shift_type", "Day").strip()
        start_date = request.form.get("start_date", "").strip() or date.today().isoformat()
        end_date = request.form.get("end_date", "").strip() or None

        if not guard_id or not client_id:
            flash("Please select both a Guard and a Client site for deployment.", "error")
            guards, clients_list = _get_guards_and_clients(client)
            return render_template("deployments/assign.html", guards=guards, clients=clients_list, form_data=request.form)

        payload = {
            "guard_id": guard_id,
            "client_id": client_id,
            "shift_type": shift_type,
            "start_date": start_date,
            "end_date": end_date,
            "status": "Active",
        }

        try:
            # 1. Insert deployment record
            client.table("deployments").insert(payload).execute()

            # 2. Update guard record status to Active and set assigned_client_id
            guard_update = {
                "assigned_client_id": client_id,
                "status": "Active",
            }
            try:
                client.table("guards").update(guard_update).eq("id", guard_id).execute()
            except Exception:
                pass

            flash("Guard successfully deployed to site!", "success")
            return redirect(url_for("deployments.index"))
        except Exception as e:
            err_msg = str(e)
            if "PGRST204" in err_msg or "schema cache" in err_msg:
                flash(
                    "Database schema update required! Please run 'schema_chunk5.sql' in your Supabase SQL Editor to create the deployments table.",
                    "error"
                )
            else:
                flash(f"Failed to assign deployment: {err_msg}", "error")

            guards, clients_list = _get_guards_and_clients(client)
            return render_template("deployments/assign.html", guards=guards, clients=clients_list, form_data=request.form)

    guards, clients_list = _get_guards_and_clients(client)
    return render_template("deployments/assign.html", guards=guards, clients=clients_list, form_data={})


@deployments_bp.route("/release/<deployment_id>", methods=["GET", "POST"])
@login_required
def release(deployment_id):
    client = get_session_client()

    try:
        res = client.table("deployments").select("*").eq("id", deployment_id).execute()
        dep = res.data[0] if res.data else None
    except Exception as e:
        flash(f"Error loading deployment details: {str(e)}", "error")
        return redirect(url_for("deployments.index"))

    if not dep:
        flash("Deployment record not found.", "error")
        return redirect(url_for("deployments.index"))

    try:
        today_str = date.today().isoformat()
        # 1. Update deployment record status to Completed
        client.table("deployments").update({
            "status": "Completed",
            "end_date": today_str
        }).eq("id", deployment_id).execute()

        # 2. Unassign client from guard profile
        if dep.get("guard_id"):
            client.table("guards").update({
                "assigned_client_id": None
            }).eq("id", dep.get("guard_id")).execute()

        flash("Deployment shift completed and guard released to available pool.", "success")
    except Exception as e:
        flash(f"Failed to release deployment: {str(e)}", "error")

    return redirect(url_for("deployments.index"))
