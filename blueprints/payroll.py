"""
blueprints/payroll.py
---------------------
Attendance Tracking & Automated Payroll Ledger Module.

Routes:
  - GET  /payroll/                 : Calculated payroll ledger with net salaries & payment statuses
  - GET/POST /payroll/mark-attendance: Log daily attendance status & overtime hours for guards
  - GET/POST /payroll/generate     : Auto-calculate net salary & generate monthly salary slip
  - GET/POST /payroll/pay/<id>     : Mark salary slip status as Paid
"""

from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from decorators import login_required
from supabase_client import get_session_client

payroll_bp = Blueprint("payroll", __name__)


def _get_guards_list(client):
    """Fetch security guards list for dropdown selection."""
    try:
        res = client.table("guards").select("id, guard_id, full_name, base_salary, status").order("full_name").execute()
        return res.data or []
    except Exception:
        return []


def _normalize_attendance_row(row):
    """Unify date fields across Phase-1 (attendance_date) and Chunk 6 (date) schemas."""
    normalized = dict(row)
    normalized["display_date"] = (
        normalized.get("attendance_date") or normalized.get("date")
    )
    return normalized


def _fetch_recent_attendance(client, limit=15):
    """Fetch recent attendance logs for active guards with schema-compatible fallbacks."""
    select_with_active = (
        "id, attendance_date, status, overtime_hours, reason_for_absence, "
        "guards!inner(full_name, guard_id, is_active)"
    )
    select_basic = (
        "id, attendance_date, status, overtime_hours, reason_for_absence, "
        "guards(full_name, guard_id)"
    )

    for select_cols, filter_active in ((select_with_active, True), (select_basic, False)):
        try:
            query = (
                client.table("attendance")
                .select(select_cols)
                .order("attendance_date", desc=True)
                .limit(limit)
            )
            if filter_active:
                query = query.eq("guards.is_active", True)
            rows = query.execute().data or []
            return [_normalize_attendance_row(row) for row in rows]
        except Exception:
            continue

    return []


@payroll_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()
    month_filter = request.args.get("month", "").strip()

    query = client.table("payroll").select(
        "id, guard_id, month, base_salary, bonus, deductions, net_salary, status, created_at, guards(id, guard_id, full_name, cnic, phone, base_salary)"
    ).order("created_at", desc=True)

    if status_filter:
        query = query.eq("status", status_filter)
    if month_filter:
        query = query.eq("month", month_filter)

    try:
        res = query.execute()
        payroll_list = res.data or []
    except Exception as e:
        flash(f"Error loading payroll ledger: {str(e)}", "error")
        payroll_list = []

    # Calculate status counts and financial totals
    counts = {"All": 0, "Pending": 0, "Paid": 0}
    financials = {"total_expense": 0.0, "total_paid": 0.0, "total_pending": 0.0}

    try:
        all_res = client.table("payroll").select("status, net_salary").execute()
        all_payrolls = all_res.data or []
        counts["All"] = len(all_payrolls)
        for p in all_payrolls:
            st = p.get("status")
            net = float(p.get("net_salary") or 0.0)
            if st in counts:
                counts[st] += 1
            financials["total_expense"] += net
            if st == "Paid":
                financials["total_paid"] += net
            elif st == "Pending":
                financials["total_pending"] += net
    except Exception:
        pass

    return render_template(
        "payroll/index.html",
        payrolls=payroll_list,
        status_filter=status_filter,
        month_filter=month_filter,
        counts=counts,
        financials=financials,
    )


@payroll_bp.route("/mark-attendance", methods=["GET", "POST"])
@login_required
def mark_attendance():
    client = get_session_client()

    if request.method == "POST":
        guard_id = request.form.get("guard_id", "").strip()
        att_date = request.form.get("date", "").strip() or date.today().isoformat()
        status = request.form.get("status", "Present").strip()
        overtime_raw = request.form.get("overtime_hours", "").strip()

        if not guard_id:
            flash("Please select a Guard to log attendance.", "error")
            guards = _get_guards_list(client)
            return render_template(
                "payroll/attendance.html",
                guards=guards,
                recent_attendance=[],
                form_data=request.form,
            )

        try:
            overtime_hours = float(overtime_raw) if overtime_raw else 0.0
        except ValueError:
            overtime_hours = 0.0

        # Phase-1 schema used attendance_date (NOT NULL) + stricter status labels.
        # Chunk 6 adds date / overtime_hours. Write both date fields for compatibility.
        db_status = "On Leave" if status == "Leave" else status
        payload = {
            "guard_id": guard_id,
            "date": att_date,
            "attendance_date": att_date,
            "status": db_status,
            "overtime_hours": overtime_hours,
        }
        if db_status in ("Absent", "On Leave"):
            payload["reason_for_absence"] = request.form.get("reason_for_absence", "").strip() or status

        try:
            client.table("attendance").insert(payload).execute()
            flash("Attendance record saved successfully!", "success")
            return redirect(url_for("payroll.mark_attendance"))
        except Exception as e:
            err_msg = str(e)
            if "overtime_hours" in err_msg or "PGRST204" in err_msg:
                flash(
                    "Attendance table is missing Chunk 6 columns. Re-run the updated schema_chunk6.sql in Supabase SQL Editor (it ALTERs the existing Phase-1 attendance table), then try again.",
                    "error",
                )
            else:
                flash(f"Failed to log attendance: {err_msg}", "error")
            guards = _get_guards_list(client)
            return render_template(
                "payroll/attendance.html",
                guards=guards,
                recent_attendance=[],
                form_data=request.form,
            )

    recent_attendance = _fetch_recent_attendance(client)

    guards = _get_guards_list(client)
    return render_template(
        "payroll/attendance.html",
        guards=guards,
        recent_attendance=recent_attendance,
        form_data={"date": date.today().isoformat()},
    )


@payroll_bp.route("/generate", methods=["GET", "POST"])
@login_required
def generate():
    client = get_session_client()

    if request.method == "POST":
        guard_id = request.form.get("guard_id", "").strip()
        month = request.form.get("month", "").strip() or date.today().strftime("%B %Y")
        base_salary_raw = request.form.get("base_salary", "").strip()
        bonus_raw = request.form.get("bonus", "").strip()
        deductions_raw = request.form.get("deductions", "").strip()
        status = request.form.get("status", "Pending").strip()

        if not guard_id or not month:
            flash("Please select a Guard and specify the Month.", "error")
            guards = _get_guards_list(client)
            return render_template(
                "payroll/generate.html",
                guards=guards,
                default_month=date.today().strftime("%B %Y"),
                form_data=request.form,
            )

        try:
            base_salary = float(base_salary_raw) if base_salary_raw else 0.0
            bonus = float(bonus_raw) if bonus_raw else 0.0
            deductions = float(deductions_raw) if deductions_raw else 0.0
        except ValueError:
            base_salary = 0.0
            bonus = 0.0
            deductions = 0.0

        net_salary = base_salary + bonus - deductions

        payload = {
            "guard_id": guard_id,
            "month": month,
            "base_salary": base_salary,
            "bonus": bonus,
            "deductions": deductions,
            "net_salary": net_salary,
            "status": status,
        }

        try:
            client.table("payroll").insert(payload).execute()
            flash(f"Payslip for {month} generated successfully! (Net: Rs. {net_salary:,.2f})", "success")
            return redirect(url_for("payroll.index"))
        except Exception as e:
            err_msg = str(e)
            if "PGRST204" in err_msg and "payroll" in err_msg.lower():
                flash(
                    "Payroll table/columns missing. Re-run schema_chunk6.sql in Supabase SQL Editor, then try again.",
                    "error",
                )
            else:
                flash(f"Failed to generate payslip: {err_msg}", "error")
            guards = _get_guards_list(client)
            return render_template(
                "payroll/generate.html",
                guards=guards,
                default_month=date.today().strftime("%B %Y"),
                form_data=request.form,
            )

    guards = _get_guards_list(client)
    default_month = date.today().strftime("%B %Y")
    return render_template("payroll/generate.html", guards=guards, default_month=default_month, form_data={})


@payroll_bp.route("/pay/<payroll_id>", methods=["GET", "POST"])
@login_required
def pay(payroll_id):
    client = get_session_client()

    try:
        client.table("payroll").update({"status": "Paid"}).eq("id", payroll_id).execute()
        flash("Salary payment marked as Paid!", "success")
    except Exception as e:
        flash(f"Failed to update payment status: {str(e)}", "error")

    return redirect(url_for("payroll.index"))
