"""
blueprints/clients.py
----------------------
Clients & Duty Locations Management Module.

Routes:
  - GET  /clients/               : List all corporate clients & duty locations with status filters
  - GET/POST /clients/add        : Register a new client / duty location
  - GET/POST /clients/edit/<id>  : View/Update client details & contract status
"""

from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from decorators import login_required
from supabase_client import get_session_client

clients_bp = Blueprint("clients", __name__)



@clients_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()

    query = client.table("clients").select("*").order("created_at", desc=True)

    if status_filter:
        query = query.eq("status", status_filter)

    try:
        res = query.execute()
        clients_list = res.data or []
    except Exception as e:
        flash(f"Error loading clients: {str(e)}", "error")
        clients_list = []

    # Get status counts for tab badges
    counts = {
        "All": 0,
        "Active": 0,
        "Inactive": 0,
        "Terminated": 0,
    }
    try:
        all_res = client.table("clients").select("status").execute()
        all_clients = all_res.data or []
        counts["All"] = len(all_clients)
        for c in all_clients:
            st = c.get("status")
            if st in counts:
                counts[st] += 1
    except Exception:
        pass

    # Count assigned guards per client for roster insights
    guard_counts = {}
    try:
        guards_res = client.table("guards").select("assigned_client_id").execute()
        for g in (guards_res.data or []):
            cid = g.get("assigned_client_id")
            if cid:
                guard_counts[cid] = guard_counts.get(cid, 0) + 1
    except Exception:
        pass

    return render_template(
        "clients/index.html",
        clients=clients_list,
        status_filter=status_filter,
        counts=counts,
        guard_counts=guard_counts,
    )


@clients_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    client = get_session_client()

    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        company_name = request.form.get("company_name", "").strip()
        contact_person = request.form.get("contact_person", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        contract_start = request.form.get("contract_start", "").strip() or None
        contract_end = request.form.get("contract_end", "").strip() or None
        billing_rate_raw = request.form.get("monthly_billing_rate", "").strip()
        status = request.form.get("status", "").strip() or "Active"

        if not client_name or not phone:
            flash("Client Name and Phone Number are required fields.", "error")
            return render_template("clients/add.html", form_data=request.form)

        try:
            monthly_billing_rate = float(billing_rate_raw) if billing_rate_raw else 0.0
        except ValueError:
            monthly_billing_rate = 0.0

        start_date_val = contract_start if contract_start else date.today().isoformat()
        payload = {
            "client_name": client_name,
            "company_name": company_name if company_name else None,
            "contact_person": contact_person if contact_person else None,
            "phone": phone,
            "email": email if email else None,
            "address": address if address else None,
            "contract_start": start_date_val,
            "contract_start_date": start_date_val,
            "contract_end": contract_end,
            "contract_end_date": contract_end,
            "monthly_billing_rate": monthly_billing_rate,
            "rate_per_guard": monthly_billing_rate,
            "status": status,
        }


        try:
            client.table("clients").insert(payload).execute()
            flash(f"Client '{client_name}' registered successfully!", "success")
            return redirect(url_for("clients.index"))
        except Exception as e:
            err_msg = str(e)
            if "PGRST204" in err_msg or "schema cache" in err_msg:
                flash(
                    "Database schema update required! Please run 'schema_chunk4.sql' in your Supabase SQL Editor to add client columns.",
                    "error"
                )
            else:
                flash(f"Failed to register client: {err_msg}", "error")
            return render_template("clients/add.html", form_data=request.form)

    return render_template("clients/add.html", form_data={})


@clients_bp.route("/edit/<client_id>", methods=["GET", "POST"])
@login_required
def edit(client_id):
    client = get_session_client()

    try:
        res = client.table("clients").select("*").eq("id", client_id).execute()
        client_data = res.data[0] if res.data else None
    except Exception as e:
        flash(f"Error loading client profile: {str(e)}", "error")
        return redirect(url_for("clients.index"))

    if not client_data:
        flash("Client record not found.", "error")
        return redirect(url_for("clients.index"))

    if request.method == "POST":
        client_name = request.form.get("client_name", "").strip()
        company_name = request.form.get("company_name", "").strip()
        contact_person = request.form.get("contact_person", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        contract_start = request.form.get("contract_start", "").strip() or None
        contract_end = request.form.get("contract_end", "").strip() or None
        billing_rate_raw = request.form.get("monthly_billing_rate", "").strip()
        status = request.form.get("status", "").strip() or "Active"

        if not client_name or not phone:
            flash("Client Name and Phone Number are required fields.", "error")
            return render_template("clients/edit.html", client=client_data)

        try:
            monthly_billing_rate = float(billing_rate_raw) if billing_rate_raw else 0.0
        except ValueError:
            monthly_billing_rate = 0.0

        start_date_val = contract_start if contract_start else date.today().isoformat()
        payload = {
            "client_name": client_name,
            "company_name": company_name if company_name else None,
            "contact_person": contact_person if contact_person else None,
            "phone": phone,
            "email": email if email else None,
            "address": address if address else None,
            "contract_start": start_date_val,
            "contract_start_date": start_date_val,
            "contract_end": contract_end,
            "contract_end_date": contract_end,
            "monthly_billing_rate": monthly_billing_rate,
            "rate_per_guard": monthly_billing_rate,
            "status": status,
        }


        try:
            client.table("clients").update(payload).eq("id", client_id).execute()
            flash(f"Client record '{client_name}' updated successfully!", "success")
            return redirect(url_for("clients.index"))
        except Exception as e:
            flash(f"Failed to update client profile: {str(e)}", "error")
            return render_template("clients/edit.html", client=client_data)

    return render_template("clients/edit.html", client=client_data)
