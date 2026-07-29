"""
blueprints/advances.py
-----------------------
Guard Salary Advance Ledger — logging + lifecycle tracking.

An advance starts life as `is_deducted = false` ("Pending"). It is
automatically cleared to `is_deducted = true` ("Deducted") the moment
it gets swept into a payroll run — see blueprints/payroll.py, which is
the ONLY place that ever flips is_deducted. This module only creates
and lists advances; it never marks them deducted itself.

Routes:
  - GET      /advances/          : Ledger of all salary advances (Pending + Deducted)
  - GET/POST /advances/add       : Log a new advance for a guard
"""

from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from decorators import login_required
from supabase_client import get_session_client

advances_bp = Blueprint("advances", __name__)


def _get_guards_list(client):
    """Active guards for the advance-logging dropdown."""
    try:
        res = (
            client.table("guards")
            .select("id, guard_id, full_name, base_salary")
            .eq("is_active", True)
            .order("full_name")
            .execute()
        )
        return res.data or []
    except Exception:
        try:
            res = client.table("guards").select("id, guard_id, full_name, base_salary").order("full_name").execute()
            return res.data or []
        except Exception:
            return []


@advances_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()  # "Pending" | "Deducted" | ""

    query = (
        client.table("salary_advances")
        .select(
            "id, guard_id, amount, reason, advance_date, auto_deduct_next_month, "
            "is_deducted, deducted_on, deducted_in_payroll_id, created_at, "
            "guards(id, guard_id, full_name)"
        )
        .order("advance_date", desc=True)
    )
    if status_filter == "Pending":
        query = query.eq("is_deducted", False)
    elif status_filter == "Deducted":
        query = query.eq("is_deducted", True)

    try:
        advances = query.execute().data or []
    except Exception as e:
        flash(f"Error loading salary advances: {str(e)}", "error")
        advances = []

    counts = {"All": 0, "Pending": 0, "Deducted": 0}
    totals = {"pending_total": 0.0, "deducted_total": 0.0}
    try:
        all_res = client.table("salary_advances").select("is_deducted, amount").execute()
        rows = all_res.data or []
        counts["All"] = len(rows)
        for row in rows:
            amt = float(row.get("amount") or 0)
            if row.get("is_deducted"):
                counts["Deducted"] += 1
                totals["deducted_total"] += amt
            else:
                counts["Pending"] += 1
                totals["pending_total"] += amt
    except Exception:
        pass

    return render_template(
        "advances/index.html",
        advances=advances,
        status_filter=status_filter,
        counts=counts,
        totals=totals,
    )


@advances_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    client = get_session_client()

    if request.method == "POST":
        guard_id = request.form.get("guard_id", "").strip()
        amount_raw = request.form.get("amount", "").strip()
        reason = request.form.get("reason", "").strip()
        advance_date = request.form.get("advance_date", "").strip() or date.today().isoformat()
        auto_deduct = request.form.get("auto_deduct_next_month") == "on"

        guards = _get_guards_list(client)

        if not guard_id:
            flash("Please select a guard for this advance.", "error")
            return render_template("advances/add.html", guards=guards, form_data=request.form)

        try:
            amount = float(amount_raw)
        except ValueError:
            amount = 0.0

        if amount <= 0:
            flash("Advance amount must be greater than zero.", "error")
            return render_template("advances/add.html", guards=guards, form_data=request.form)

        if not reason:
            flash("Please provide a reason for this advance (required for the ledger).", "error")
            return render_template("advances/add.html", guards=guards, form_data=request.form)

        payload = {
            "guard_id": guard_id,
            "amount": amount,
            "reason": reason,
            "advance_date": advance_date,
            "auto_deduct_next_month": auto_deduct,
            "is_deducted": False,
        }

        try:
            client.table("salary_advances").insert(payload).execute()
            flash("Salary advance logged. It will be auto-deducted on the next payroll run for this guard.", "success")
            return redirect(url_for("advances.index"))
        except Exception as e:
            err_msg = str(e)
            if "PGRST204" in err_msg or "schema cache" in err_msg:
                flash("salary_advances table/columns missing. Run schema.sql (and schema_chunk10.sql) in Supabase SQL Editor, then try again.", "error")
            else:
                flash(f"Failed to log salary advance: {err_msg}", "error")
            return render_template("advances/add.html", guards=guards, form_data=request.form)

    guards = _get_guards_list(client)
    return render_template(
        "advances/add.html",
        guards=guards,
        form_data={"advance_date": date.today().isoformat()},
    )
    