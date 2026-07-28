"""
Chunk 8 — Weapons & Armory Inventory Management
Routes: armory overview, register weapon, assign/unassign to guard,
procurement (CapEx) log.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from supabase_client import get_session_client
from decorators import login_required  # Ya jo decorator chal raha hai
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

weapons_bp = Blueprint("weapons", __name__, url_prefix="/weapons")

VALID_STATUSES = ("In Storage", "Assigned", "Under Repair", "Decommissioned")
WEAPON_TYPES = ("9mm Pistol", "12-Gauge Shotgun", "Rifle", "Other")

# =============================================================================
# ARMORY OVERVIEW
# =============================================================================
@weapons_bp.route("/")
@login_required
def index():
    supabase = get_session_client()
    status_filter = request.args.get("status", "")

    query = supabase.table("weapons").select(
        "*, guards(id, full_name)"
    ).order("created_at", desc=True)

    if status_filter in VALID_STATUSES:
        query = query.eq("status", status_filter)

    try:
        weapons = query.execute().data or []
        all_weapons = supabase.table("weapons").select("status").execute().data or []
    except Exception as err:
        flash(f"Error loading armory records: {err}", "danger")
        weapons, all_weapons = [], []

    counts = {"All": len(all_weapons)}
    for s in VALID_STATUSES:
        counts[s] = sum(1 for w in all_weapons if w.get("status") == s)

    return render_template(
        "weapons/index.html",
        weapons=weapons,
        counts=counts,
        status_filter=status_filter,
        valid_statuses=VALID_STATUSES,
    )
def _weapon_lookup_select():
    return (
        "id, weapon_type, serial_number, license_number, city, storage_address, "
        "status, assigned_guard_id, created_at, guards(id, full_name, guard_id, status)"
    )


@weapons_bp.route("/lookup")
@login_required
def lookup():
    supabase = get_session_client()
    serial_query = request.args.get("serial_number", "").strip()

    if not serial_query:
        return jsonify({"success": False, "error": "Please enter a Serial Number to search."}), 400

    try:
        res = supabase.table("weapons").select(_weapon_lookup_select()) \
            .eq("serial_number", serial_query).limit(1).execute()
        weapon = res.data[0] if res.data else None

        if not weapon:
            res_fallback = supabase.table("weapons").select(_weapon_lookup_select()) \
                .ilike("serial_number", f"%{serial_query}%").limit(1).execute()
            weapon = res_fallback.data[0] if res_fallback.data else None
    except Exception as e:
        return jsonify({"success": False, "error": f"Lookup failed: {str(e)}"}), 500

    if not weapon:
        return jsonify({"success": False, "error": f"No weapon found matching Serial Number '{serial_query}'."}), 404

    last_purchase = None
    try:
        purch_res = supabase.table("weapon_purchases").select(
            "vendor_name, purchase_cost, purchase_date, invoice_reference"
        ).eq("weapon_id", weapon["id"]).order("purchase_date", desc=True).limit(1).execute()
        last_purchase = purch_res.data[0] if purch_res.data else None
    except Exception:
        pass

    weapon["last_purchase"] = last_purchase
    return jsonify({"success": True, "data": weapon})

# =============================================================================
# REGISTER NEW WEAPON
# =============================================================================
@weapons_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    supabase = get_session_client()
    if request.method == "POST":
        weapon_type = request.form.get("weapon_type", "").strip()
        serial_number = request.form.get("serial_number", "").strip()
        license_number = request.form.get("license_number", "").strip()
        city = request.form.get("city", "").strip()
        storage_address = request.form.get("storage_address", "").strip()

        if not weapon_type or not serial_number or not license_number:
            flash("Weapon type, serial number, and license number are required.", "danger")
            return render_template("weapons/add.html", form=request.form, weapon_types=WEAPON_TYPES)

        try:
            duplicate = supabase.table("weapons").select("id") \
                .eq("serial_number", serial_number).execute()
            if duplicate.data:
                flash(f"A weapon with serial number '{serial_number}' is already registered.", "danger")
                return render_template("weapons/add.html", form=request.form, weapon_types=WEAPON_TYPES)

            supabase.table("weapons").insert({
                "weapon_type": weapon_type,
                "serial_number": serial_number,
                "license_number": license_number,
                "city": city or None,
                "storage_address": storage_address or None,
                "status": "In Storage",
            }).execute()

            flash(f"Weapon '{serial_number}' registered into the armory.", "success")
            return redirect(url_for("weapons.index"))

        except Exception as err:
            flash(f"Error registering weapon: {err}", "danger")
            return render_template("weapons/add.html", form=request.form, weapon_types=WEAPON_TYPES)

    return render_template("weapons/add.html", form={}, weapon_types=WEAPON_TYPES)


# =============================================================================
# ASSIGN / UNASSIGN TO GUARD
# =============================================================================
@weapons_bp.route("/assign/<uuid:weapon_id>", methods=["GET", "POST"])
@login_required
def assign(weapon_id):
    supabase = get_session_client()
    weapon_res = supabase.table("weapons").select("*, guards(id, full_name)") \
        .eq("id", str(weapon_id)).limit(1).execute()

    if not weapon_res.data:
        flash("Weapon not found.", "danger")
        return redirect(url_for("weapons.index"))

    weapon = weapon_res.data[0]

    if request.method == "POST":
        guard_id = request.form.get("guard_id") or None

        try:
            if guard_id:
                supabase.table("weapons").update({
                    "assigned_guard_id": guard_id,
                    "status": "Assigned",
                }).eq("id", str(weapon_id)).execute()
                flash("Weapon assigned successfully.", "success")
            else:
                supabase.table("weapons").update({
                    "assigned_guard_id": None,
                    "status": "In Storage",
                }).eq("id", str(weapon_id)).execute()
                flash("Weapon unassigned and returned to storage.", "success")

            return redirect(url_for("weapons.index"))

        except Exception as err:
            flash(f"Error updating assignment: {err}", "danger")

    # Assumption: guards.status == 'Active' marks an on-duty/available guard.
    # Change this line if your guards.py uses a different field/value.
    guards_res = supabase.table("guards").select("id, full_name") \
        .eq("status", "Active").order("full_name").execute()
    active_guards = guards_res.data or []

    return render_template("weapons/assign.html", weapon=weapon, active_guards=active_guards)


# =============================================================================
# PROCUREMENT / CAPEX LOG
# =============================================================================
@weapons_bp.route("/purchases")
@login_required
def purchases():
    supabase = get_session_client()
    try:
        purchase_rows = supabase.table("weapon_purchases").select(
            "*, weapons(weapon_type, serial_number)"
        ).order("purchase_date", desc=True).execute().data or []
        weapons_for_dropdown = supabase.table("weapons").select(
            "id, weapon_type, serial_number"
        ).order("serial_number").execute().data or []
    except Exception as err:
        flash(f"Error loading procurement log: {err}", "danger")
        purchase_rows, weapons_for_dropdown = [], []

    total_capex = sum(float(p["purchase_cost"]) for p in purchase_rows)

    return render_template(
        "weapons/purchases.html",
        purchases=purchase_rows,
        total_capex=total_capex,
        weapons_for_dropdown=weapons_for_dropdown,
    )


@weapons_bp.route("/purchases/add", methods=["POST"])
@login_required
def add_purchase():
    supabase = get_session_client()
    weapon_id = request.form.get("weapon_id")
    vendor_name = request.form.get("vendor_name", "").strip()
    purchase_cost = request.form.get("purchase_cost", "").strip()
    purchase_date = request.form.get("purchase_date", "").strip()
    invoice_reference = request.form.get("invoice_reference", "").strip()
    notes = request.form.get("notes", "").strip()

    if not weapon_id or not vendor_name or not purchase_cost or not purchase_date:
        flash("Weapon, vendor, cost, and purchase date are required.", "danger")
        return redirect(url_for("weapons.purchases"))

    try:
        supabase.table("weapon_purchases").insert({
            "weapon_id": weapon_id,
            "vendor_name": vendor_name,
            "purchase_cost": purchase_cost,
            "purchase_date": purchase_date,
            "invoice_reference": invoice_reference or None,
            "notes": notes or None,
        }).execute()
        flash("Purchase recorded in the procurement log.", "success")
    except Exception as err:
        flash(f"Error recording purchase: {err}", "danger")

    return redirect(url_for("weapons.purchases"))