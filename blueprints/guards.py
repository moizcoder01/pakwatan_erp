"""
blueprints/guards.py
---------------------
Guards Management Module & Waiting List Applicants Pool.

Routes:
  - GET  /guards/               : List all guards / candidates with status filtering
  - GET/POST /guards/add        : Register a new guard or waiting list applicant
  - GET/POST /guards/edit/<id>  : View/Update guard profile & change status
"""

import random
import string
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from decorators import login_required
from supabase_client import get_session_client
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify

guards_bp = Blueprint("guards", __name__)


def _generate_guard_id(client):
    """Auto-generates a unique Guard ID like PK-G-1005 if none provided."""
    try:
        res = client.table("guards").select("guard_id").execute()
        existing_ids = [r.get("guard_id") for r in (res.data or []) if r.get("guard_id")]
        
        # Extract numerical suffix if standard format
        nums = []
        for gid in existing_ids:
            if gid and gid.startswith("PK-G-"):
                try:
                    nums.append(int(gid.replace("PK-G-", "")))
                except ValueError:
                    pass
        
        next_num = max(nums) + 1 if nums else 1001
        return f"PK-G-{next_num}"
    except Exception:
        suffix = ''.join(random.choices(string.digits, k=4))
        return f"PK-G-{suffix}"


def _get_active_clients(client):
    """Fetch active clients list for dropdown selection."""
    try:
        res = client.table("clients").select("id, client_name").execute()
        return res.data or []
    except Exception:
        return []


@guards_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()

    # Query guards with assigned client info + assigned weapon info
    query = client.table("guards").select(
        "id, guard_id, full_name, cnic, phone, gender, emergency_contact, address, "
        "blood_group, verification_status, status, assigned_client_id, created_at, "
        "clients(client_name), weapons(id, weapon_type, serial_number)"
        # If Supabase raises an "ambiguous relationship" / "more than one relationship
        # was found" error, replace the weapons(...) segment above with the explicit
        # FK hint instead:
        # "weapons!weapons_assigned_guard_id_fkey(id, weapon_type, serial_number)"
    ).order("created_at", desc=True)

    if status_filter:
        query = query.eq("status", status_filter)

    try:
        res = query.execute()
        guards = res.data or []
    except Exception as e:
        flash(f"Error fetching guards data: {str(e)}", "error")
        guards = []

    # weapons(...) comes back as a LIST on this side (reverse FK: weapons ->
    # guards), even though a guard only ever has 0 or 1 assigned weapon in
    # practice. Flatten it here so the template doesn't need list-vs-none logic.
    for g in guards:
        weapon_rows = g.get("weapons") or []
        g["assigned_weapon"] = weapon_rows[0] if weapon_rows else None

    # Get status summary counts for tab badges
    counts = {
        "All": 0,
        "Active": 0,
        "Waiting List": 0,
        "Inactive": 0,
        "Suspended": 0,
    }
    try:
        all_res = client.table("guards").select("status").execute()
        all_guards = all_res.data or []
        counts["All"] = len(all_guards)
        for g in all_guards:
            st = g.get("status")
            if st in counts:
                counts[st] += 1
    except Exception:
        pass

    return render_template(
        "guards/index.html",
        guards=guards,
        status_filter=status_filter,
        counts=counts,
    )
def _guard_lookup_select():
    return (
        "id, guard_id, full_name, cnic, phone, gender, emergency_contact, address, "
        "blood_group, verification_status, status, assigned_client_id, base_salary, created_at, "
        "clients(id, client_name, company_name), weapons(id, weapon_type, serial_number, status)"
    )


@guards_bp.route("/lookup")
@login_required
def lookup():
    client = get_session_client()
    guard_id_query = request.args.get("guard_id", "").strip()

    if not guard_id_query:
        return jsonify({"success": False, "error": "Please enter a Guard ID to search."}), 400

    try:
        res = client.table("guards").select(_guard_lookup_select()) \
            .eq("guard_id", guard_id_query).limit(1).execute()
        guard = res.data[0] if res.data else None

        if not guard:
            res_fallback = client.table("guards").select(_guard_lookup_select()) \
                .ilike("guard_id", f"%{guard_id_query}%").limit(1).execute()
            guard = res_fallback.data[0] if res_fallback.data else None
    except Exception as e:
        return jsonify({"success": False, "error": f"Lookup failed: {str(e)}"}), 500

    if not guard:
        return jsonify({"success": False, "error": f"No guard found matching Guard ID '{guard_id_query}'."}), 404

    weapon_rows = guard.get("weapons") or []
    guard["assigned_weapon"] = weapon_rows[0] if weapon_rows else None

    pending_advances, pending_total = [], 0.0
    try:
        adv_res = client.table("salary_advances").select(
            "id, amount, reason, advance_date, auto_deduct_next_month, is_deducted"
        ).eq("guard_id", guard["id"]).eq("is_deducted", False) \
         .order("advance_date", desc=True).execute()
        pending_advances = adv_res.data or []
        pending_total = sum(float(a["amount"]) for a in pending_advances)
    except Exception:
        pass

    guard["pending_advances"] = pending_advances
    guard["pending_advances_total"] = pending_total

    return jsonify({"success": True, "data": guard})


@guards_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    client = get_session_client()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        guard_id_input = request.form.get("guard_id", "").strip()
        cnic = request.form.get("cnic", "").strip()
        phone = request.form.get("phone", "").strip()
        gender = request.form.get("gender", "").strip() or "Male"
        emergency_contact = request.form.get("emergency_contact", "").strip()
        address = request.form.get("address", "").strip()
        blood_group = request.form.get("blood_group", "").strip()
        verification_status = request.form.get("verification_status", "").strip() or "Pending"
        status = request.form.get("status", "").strip() or "Active"
        assigned_client_id = request.form.get("assigned_client_id", "").strip() or None

        if not full_name or not phone:
            flash("Full Name and Phone Number are required.", "error")
            clients = _get_active_clients(client)
            return render_template("guards/add.html", clients=clients, form_data=request.form)

        # Generate Guard ID if left blank
        guard_id = guard_id_input if guard_id_input else _generate_guard_id(client)

        base_salary_raw = request.form.get("base_salary", "").strip()
        try:
            base_salary = float(base_salary_raw) if base_salary_raw else 0.0
        except ValueError:
            base_salary = 0.0

        payload = {
            "guard_id": guard_id,
            "full_name": full_name,
            "cnic": cnic if cnic else None,
            "phone": phone,
            "gender": gender,
            "emergency_contact": emergency_contact if emergency_contact else None,
            "address": address if address else None,
            "blood_group": blood_group if blood_group else None,
            "verification_status": verification_status,
            "status": status,
            "assigned_client_id": assigned_client_id,
            "base_salary": base_salary,
        }


        try:
            client.table("guards").insert(payload).execute()
            flash(f"Guard record for '{full_name}' ({guard_id}) created successfully!", "success")
            
            # If registered as Waiting List, redirect to Waiting List view
            if status == "Waiting List":
                return redirect(url_for("guards.index", status="Waiting List"))
            return redirect(url_for("guards.index"))
        except Exception as e:
            err_msg = str(e)
            if "PGRST204" in err_msg or "schema cache" in err_msg:
                flash(
                    "Database schema update required! Please run the 'schema_chunk3.sql' script in your Supabase SQL Editor to add the new columns ('blood_group', 'guard_id', etc.).",
                    "error"
                )
            else:
                flash(f"Failed to register guard: {err_msg}", "error")
            clients = _get_active_clients(client)
            return render_template("guards/add.html", clients=clients, form_data=request.form)


    clients = _get_active_clients(client)
    return render_template("guards/add.html", clients=clients, form_data={})


@guards_bp.route("/edit/<guard_id_param>", methods=["GET", "POST"])
@login_required
def edit(guard_id_param):
    client = get_session_client()

    # Retrieve existing record by UUID id or guard_id string
    try:
        res = client.table("guards").select("*").eq("id", guard_id_param).execute()
        guard = res.data[0] if res.data else None
        if not guard:
            res_alt = client.table("guards").select("*").eq("guard_id", guard_id_param).execute()
            guard = res_alt.data[0] if res_alt.data else None
    except Exception as e:
        flash(f"Error loading guard details: {str(e)}", "error")
        return redirect(url_for("guards.index"))

    if not guard:
        flash("Guard record not found.", "error")
        return redirect(url_for("guards.index"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        guard_id = request.form.get("guard_id", "").strip()
        cnic = request.form.get("cnic", "").strip()
        phone = request.form.get("phone", "").strip()
        gender = request.form.get("gender", "").strip() or "Male"
        emergency_contact = request.form.get("emergency_contact", "").strip()
        address = request.form.get("address", "").strip()
        blood_group = request.form.get("blood_group", "").strip()
        verification_status = request.form.get("verification_status", "").strip() or "Pending"
        status = request.form.get("status", "").strip() or "Active"
        assigned_client_id = request.form.get("assigned_client_id", "").strip() or None

        if not full_name or not phone:
            flash("Full Name and Phone Number are required.", "error")
            clients = _get_active_clients(client)
            return render_template("guards/edit.html", guard=guard, clients=clients)

        base_salary_raw = request.form.get("base_salary", "").strip()
        try:
            base_salary = float(base_salary_raw) if base_salary_raw else 0.0
        except ValueError:
            base_salary = 0.0

        payload = {
            "guard_id": guard_id,
            "full_name": full_name,
            "cnic": cnic if cnic else None,
            "phone": phone,
            "gender": gender,
            "emergency_contact": emergency_contact if emergency_contact else None,
            "address": address if address else None,
            "blood_group": blood_group if blood_group else None,
            "verification_status": verification_status,
            "status": status,
            "assigned_client_id": assigned_client_id,
            "base_salary": base_salary,
        }


        try:
            client.table("guards").update(payload).eq("id", guard["id"]).execute()
            flash(f"Guard record '{full_name}' updated successfully!", "success")
            return redirect(url_for("guards.index"))
        except Exception as e:
            flash(f"Failed to update guard details: {str(e)}", "error")
            clients = _get_active_clients(client)
            return render_template("guards/edit.html", guard=guard, clients=clients)

    clients = _get_active_clients(client)
    return render_template("guards/edit.html", guard=guard, clients=clients)
