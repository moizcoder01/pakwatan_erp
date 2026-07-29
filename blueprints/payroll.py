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

from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from decorators import login_required
from supabase_client import get_session_client

payroll_bp = Blueprint("payroll", __name__)


def _get_guards_list(client):
    """Fetch security guards list for dropdown selection."""
    try:
        res = client.table("guards").select(
            "id, guard_id, full_name, base_salary, status"
        ).order("full_name").execute()
        return res.data or []
    except Exception:
        # Fallback for schema variants without guard_id/status columns
        try:
            res = client.table("guards").select("id, full_name, base_salary").order("full_name").execute()
            return res.data or []
        except Exception:
            return []

def _get_guards_with_pending_advances(client):
    """Guards list for dropdowns, each annotated with pending_advances
    (sum of un-deducted salary_advances) so the UI can auto-fill deductions."""
    guards = _get_guards_list(client)
    if not guards:
        return guards

    try:
        adv_res = (
            client.table("salary_advances")
            .select("guard_id, amount")
            .eq("is_deducted", False)
            .execute()
        )
        pending_rows = adv_res.data or []
    except Exception:
        pending_rows = []

    pending_by_guard = {}
    for row in pending_rows:
        gid = row.get("guard_id")
        if not gid:
            continue
        pending_by_guard[gid] = pending_by_guard.get(gid, 0.0) + float(row.get("amount") or 0)

    for g in guards:
        g["pending_advances"] = pending_by_guard.get(g["id"], 0.0)

    return guards

def _normalize_attendance_row(row):
    """Unify date fields across Phase-1 (attendance_date) and later (date) schemas."""
    normalized = dict(row)
    normalized["display_date"] = normalized.get("attendance_date") or normalized.get("date")

    guard_obj = normalized.get("guard") or normalized.get("guards")
    normalized["guard_info"] = guard_obj if isinstance(guard_obj, dict) else None

    replacement_obj = normalized.get("replacement")
    normalized["replacement_info"] = replacement_obj if isinstance(replacement_obj, dict) else None

    return normalized


def _fetch_attendance_for_date(client, report_date, limit=200):
    """
    Fetch attendance logs, joined to guards, for a specific date.

    `attendance` has TWO foreign keys to `guards` (guard_id and
    replacement_guard_id), so any embed MUST disambiguate which FK to
    join through via the `!<constraint_name>` hint, or PostgREST raises
    an ambiguous-relationship error and returns nothing. Default Postgres
    FK constraint names follow the `<table>_<column>_fkey` convention.
    """
    select_variants = [
        # Preferred: overtime_hours + both guard relationships disambiguated
        "id, attendance_date, status, overtime_hours, reason_for_absence, "
        "guard:guards!attendance_guard_id_fkey(id, full_name, guard_id), "
        "replacement:guards!attendance_replacement_guard_id_fkey(id, full_name, guard_id)",
        # Fallback: no overtime_hours column (pre-Chunk-6 schema)
        "id, attendance_date, status, reason_for_absence, "
        "guard:guards!attendance_guard_id_fkey(id, full_name, guard_id), "
        "replacement:guards!attendance_replacement_guard_id_fkey(id, full_name, guard_id)",
        # Last resort: guard_id column doesn't exist on guards either
        "id, attendance_date, status, reason_for_absence, "
        "guard:guards!attendance_guard_id_fkey(id, full_name)",
    ]

    for select_cols in select_variants:
        try:
            rows = (
                client.table("attendance")
                .select(select_cols)
                .eq("attendance_date", report_date)
                .order("attendance_date", desc=True)
                .limit(limit)
                .execute()
                .data
                or []
            )
            return [_normalize_attendance_row(r) for r in rows]
        except Exception:
            continue

    return []


@payroll_bp.route("/")
@login_required
def index():
    client = get_session_client()
    status_filter = request.args.get("status", "").strip()
    month_filter = request.args.get("month", "").strip()

    # --- CLAUDE ADDITION: Handle native <input type="month"> parameter ---
    month_value_param = request.args.get("month_value", "").strip()
    if month_value_param and not month_filter:
        month_filter = _month_value_to_label(month_value_param)
    # ----------------------------------------------------------------------

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
        # --- CLAUDE ADDITION: Pass month_value_display kwarg for template ---
        month_value_display=_label_to_month_value(month_filter) if month_filter else "",
        # --------------------------------------------------------------------
        counts=counts,
        financials=financials,
    )


def _compute_attendance_metrics(rows):
    total = len(rows)
    present_statuses = ("Present", "On Duty")
    present_count = sum(1 for r in rows if r.get("status") in present_statuses)
    absent_count = sum(1 for r in rows if r.get("status") == "Absent")
    leave_count = total - present_count - absent_count
    rate = round((present_count / total) * 100, 1) if total else 0.0

    return {
        "total_logged": total,
        "present_count": present_count,
        "absent_count": absent_count,
        "leave_count": leave_count,
        "attendance_rate": rate,
    }



@payroll_bp.route("/mark-attendance", methods=["GET", "POST"])
@login_required
def mark_attendance():
    client = get_session_client()

    if request.method == "POST":
        guard_id = request.form.get("guard_id", "").strip()
        att_date = request.form.get("date", "").strip() or date.today().isoformat()
        status = request.form.get("status", "Present").strip()
        overtime_raw = request.form.get("overtime_hours", "").strip()

        guards = _get_guards_list(client)

        if not guard_id:
            flash("Please select a Guard to log attendance.", "error")
            return render_template(
                "payroll/attendance.html",
                guards=guards,
                recent_attendance=_fetch_attendance_for_date(client, att_date),
                metrics=_compute_attendance_metrics(_fetch_attendance_for_date(client, att_date)),
                report_date=att_date,
                form_data=request.form,
            )

        # --- Duplicate prevention: same guard, same date -------------------
        try:
            dup_check = (
                client.table("attendance")
                .select("id")
                .eq("guard_id", guard_id)
                .eq("attendance_date", att_date)
                .limit(1)
                .execute()
            )
            if dup_check.data:
                flash(
                    f"Attendance for this guard on {att_date} has already been recorded. "
                    "Edit the existing entry instead of logging a duplicate.",
                    "error",
                )
                return render_template(
                    "payroll/attendance.html",
                    guards=guards,
                    recent_attendance=_fetch_attendance_for_date(client, att_date),
                    metrics=_compute_attendance_metrics(_fetch_attendance_for_date(client, att_date)),
                    report_date=att_date,
                    form_data=request.form,
                )
        except Exception:
            pass  # if the pre-check itself fails, fall through to the DB unique constraint as a safety net

        try:
            overtime_hours = float(overtime_raw) if overtime_raw else 0.0
        except ValueError:
            overtime_hours = 0.0

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
            return redirect(url_for("payroll.mark_attendance", date=att_date))
        except Exception as e:
            err_msg = str(e)
            if "duplicate key value violates unique constraint" in err_msg.lower():
                flash(
                    f"Attendance for this guard on {att_date} has already been recorded.",
                    "error",
                )
            elif "overtime_hours" in err_msg or "PGRST204" in err_msg:
                flash(
                    "Attendance table is missing expected columns. Re-run the latest "
                    "attendance schema migration in Supabase SQL Editor, then try again.",
                    "error",
                )
            else:
                flash(f"Failed to log attendance: {err_msg}", "error")

            return render_template(
                "payroll/attendance.html",
                guards=guards,
                recent_attendance=_fetch_attendance_for_date(client, att_date),
                metrics=_compute_attendance_metrics(_fetch_attendance_for_date(client, att_date)),
                report_date=att_date,
                form_data=request.form,
            )

    # --- GET: render the terminal for a chosen (or today's) date -----------
    report_date = request.args.get("date", "").strip() or date.today().isoformat()
    recent_attendance = _fetch_attendance_for_date(client, report_date)
    metrics = _compute_attendance_metrics(recent_attendance)
    guards = _get_guards_list(client)

    return render_template(
        "payroll/attendance.html",
        guards=guards,
        recent_attendance=recent_attendance,
        metrics=metrics,
        report_date=report_date,
        form_data={"date": report_date},
    )

def _active_guards_for_payroll(client):
    """Guards eligible for bulk payroll generation."""
    try:
        res = client.table("guards").select(
            "id, guard_id, full_name, base_salary"
        ).eq("is_active", True).order("full_name").execute()
        return res.data or []
    except Exception:
        try:
            res = client.table("guards").select(
                "id, guard_id, full_name, base_salary, status"
            ).eq("status", "Active").order("full_name").execute()
            return res.data or []
        except Exception:
            return []


def _guard_ids_with_payroll_for_month(client, month_label):
    try:
        res = client.table("payroll").select("guard_id").eq("month", month_label).execute()
        return {row["guard_id"] for row in (res.data or [])}
    except Exception:
        return set()


def _pending_advances_for_guard(client, guard_id):
    try:
        res = (
            client.table("salary_advances")
            .select("id, amount")
            .eq("guard_id", guard_id)
            .eq("is_deducted", False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def _mark_advances_deducted(client, advance_ids, deducted_on, payroll_id=None):
    if not advance_ids:
        return
    update_payload = {"is_deducted": True, "deducted_on": deducted_on}
    if payroll_id:
        update_payload["deducted_in_payroll_id"] = payroll_id
    try:
        client.table("salary_advances").update(update_payload).in_("id", advance_ids).execute()
    except Exception:
        pass


def _month_value_to_label(month_value):
    """Convert an <input type=month> value like '2026-07' to 'July 2026'."""
    try:
        return datetime.strptime(month_value + "-01", "%Y-%m-%d").strftime("%B %Y")
    except ValueError:
        return month_value
def _label_to_month_value(label):
    """Reverse of _month_value_to_label — 'July 2026' -> '2026-07'."""
    try:
        return datetime.strptime(label, "%B %Y").strftime("%Y-%m")
    except (ValueError, TypeError):
        return ""


@payroll_bp.route("/generate", methods=["GET", "POST"])
@login_required
def generate():
    client = get_session_client()
    default_month_value = date.today().strftime("%Y-%m")

    if request.method == "POST":
        mode = request.form.get("mode", "bulk").strip()
        month_value = request.form.get("month_value", "").strip() or default_month_value
        month_label = _month_value_to_label(month_value)

        if mode == "custom":
            guard_id = request.form.get("guard_id", "").strip()
            base_salary_raw = request.form.get("base_salary", "").strip()
            bonus_raw = request.form.get("bonus", "").strip()
            deductions_raw = request.form.get("deductions", "").strip()
            status = request.form.get("status", "Pending").strip()
            auto_apply_advances = request.form.get("auto_apply_advances_custom") == "on"

            if not guard_id:
                flash("Please select a Guard for individual/custom payroll generation.", "error")
                guards = _get_guards_with_pending_advances(client)
                return render_template(
                    "payroll/generate.html", 
                    guards=guards,
                    default_month_value=default_month_value, 
                    form_data=request.form
                )

            try:
                existing = client.table("payroll").select("id").eq("guard_id", guard_id).eq("month", month_label).limit(1).execute()
                if existing.data:
                    flash(f"A payroll record for this guard in {month_label} already exists.", "error")
                    guards = _get_guards_with_pending_advances(client)
                    return render_template(
                        "payroll/generate.html", 
                        guards=guards,
                        default_month_value=default_month_value, 
                        form_data=request.form
                    )
            except Exception:
                pass

            try:
                base_salary = float(base_salary_raw) if base_salary_raw else 0.0
                bonus = float(bonus_raw) if bonus_raw else 0.0
                manual_deductions = float(deductions_raw) if deductions_raw else 0.0
            except ValueError:
                base_salary, bonus, manual_deductions = 0.0, 0.0, 0.0

            # The submitted deductions value already includes the advance
            # amount if auto-apply was checked (JS pre-fills it client-side).
            advance_total = 0.0
            advance_ids_to_clear = []
            if auto_apply_advances:
                for adv in _pending_advances_for_guard(client, guard_id):
                    advance_total += float(adv.get("amount") or 0)
                    advance_ids_to_clear.append(adv["id"])

            total_deductions = max(manual_deductions, advance_total) if auto_apply_advances else manual_deductions

            net_salary = base_salary + bonus - total_deductions
            payload = {
                "guard_id": guard_id,
                "month": month_label,
                "base_salary": base_salary,
                "bonus": bonus,
                "deductions": total_deductions,
                "advance_deduction": advance_total,
                "net_salary": net_salary,
                "status": status,
            }
            try:
                res = client.table("payroll").insert(payload).execute()
                new_payroll_id = res.data[0]["id"] if res.data else None
                if advance_ids_to_clear:
                    _mark_advances_deducted(client, advance_ids_to_clear, date.today().isoformat(), new_payroll_id)
                flash(f"Individual payslip for {month_label} generated! (Net: Rs. {net_salary:,.2f}"
                      + (f", incl. Rs. {advance_total:,.2f} advance recovery)" if advance_total else ")"), "success")
                return redirect(url_for("payroll.index"))
            except Exception as e:
                err_msg = str(e)
                if "PGRST204" in err_msg:
                    flash("Payroll table/columns missing. Re-run schema_chunk6.sql (and schema_chunk10.sql), then try again.", "error")
                else:
                    flash(f"Failed to generate payslip: {err_msg}", "error")
                guards = _get_guards_with_pending_advances(client)
                return render_template(
                    "payroll/generate.html", 
                    guards=guards,
                    default_month_value=default_month_value, 
                    form_data=request.form
                )
        # --- Bulk mode: every active guard for the selected month -----------
        auto_apply_advances = request.form.get("auto_apply_advances_bulk") == "on"
        guards = _active_guards_for_payroll(client)
        already_processed = _guard_ids_with_payroll_for_month(client, month_label)

        generated_count, skipped_count, errors = 0, 0, []

        for g in guards:
            if g["id"] in already_processed:
                skipped_count += 1
                continue

            base_salary = float(g.get("base_salary") or 0)
            deductions = 0.0
            advance_ids_to_clear = []

            if auto_apply_advances:
                for adv in _pending_advances_for_guard(client, g["id"]):
                    deductions += float(adv.get("amount") or 0)
                    advance_ids_to_clear.append(adv["id"])

            net_salary = base_salary - deductions
            payload = {
                "guard_id": g["id"], "month": month_label, "base_salary": base_salary,
                "bonus": 0.0, "deductions": deductions, "advance_deduction": deductions,
                "net_salary": net_salary, "status": "Pending",
            }
            try:
                res = client.table("payroll").insert(payload).execute()
                new_payroll_id = res.data[0]["id"] if res.data else None
                generated_count += 1
                if advance_ids_to_clear:
                    _mark_advances_deducted(client, advance_ids_to_clear, date.today().isoformat(), new_payroll_id)
            except Exception as e:
                errors.append(f"{g.get('full_name', 'Guard')}: {e}")

        summary = f"Bulk payroll for {month_label}: {generated_count} payslip(s) generated"
        if skipped_count:
            summary += f", {skipped_count} skipped (already processed this month)"
        if errors:
            summary += f", {len(errors)} failed"
        flash(summary, "success" if generated_count else "warning")
        if errors:
            flash("Some guards failed: " + "; ".join(errors[:5]), "error")

        return redirect(url_for("payroll.index", month=month_label))

    guards = _get_guards_with_pending_advances(client)
    return render_template("payroll/generate.html", guards=guards,
                           default_month_value=default_month_value, form_data={})

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
