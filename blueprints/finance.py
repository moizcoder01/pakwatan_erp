"""
blueprints/finance.py
---------------------
Invoicing Module, Executive Financial Dashboard & CSV Export Engine.

Routes:
  - GET        /finance/dashboard              : Revenue, payroll expense & net profit overview
  - GET/POST   /finance/expenses               : Centralized expense tracker + manual expense logging
  - GET/POST   /finance/invoices               : Client invoice listing + creation form
  - GET/POST   /finance/invoices/pay/<id>      : Mark invoice as Paid
  - GET        /finance/export/payroll/csv     : Download full payroll ledger as CSV
"""

import csv
from datetime import date, datetime, timedelta
from pdf_utils import build_ledger_pdf, build_payslip_pdf
from io import StringIO

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from decorators import login_required
from supabase_client import get_session_client

finance_bp = Blueprint("finance", __name__)

EXPENSE_CATEGORIES = (
    "Rent",
    "Utility Bills",
    "Weapon Purchase",
    "Uniforms & Tactical Gear",
    "Legal/Licensing Fees",
    "Office Maintenance",
    "Fuel & Transport",
    "Miscellaneous",
)

PAYMENT_METHODS = ("Cash", "Bank Transfer")

@finance_bp.route("/export/payslip/<payroll_id>")
@login_required
def export_payslip(payroll_id):
    client = get_session_client()
    export_format = request.args.get("format", "pdf").strip().lower()

    try:
        res = (
            client.table("payroll")
            .select("id, guard_id, month, base_salary, bonus, deductions, net_salary, status, "
                    "guards(guard_id, full_name, cnic, phone)")
            .eq("id", payroll_id).limit(1).execute()
        )
        rows = res.data or []
    except Exception as e:
        flash(f"Failed to load payslip: {e}", "error")
        return redirect(url_for("payroll.index"))

    if not rows:
        flash("Payslip record not found.", "error")
        return redirect(url_for("payroll.index"))

    p = rows[0]
    guard = p.get("guards") or {}

    pending_advances = []
    if p.get("guard_id"):
        try:
            adv_res = (
                client.table("salary_advances")
                .select("amount, reason, advance_date")
                .eq("guard_id", p["guard_id"]).eq("is_deducted", False).execute()
            )
            pending_advances = adv_res.data or []
        except Exception:
            pass

    safe_month = (p.get("month") or "").replace(" ", "_") or "unknown"
    base_filename = f"payslip_{guard.get('guard_id') or payroll_id}_{safe_month}"

    if export_format == "csv":
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Field", "Value"])
        writer.writerow(["Guard ID", guard.get("guard_id") or "—"])
        writer.writerow(["Guard Name", guard.get("full_name") or "—"])
        writer.writerow(["CNIC", guard.get("cnic") or "—"])
        writer.writerow(["Phone", guard.get("phone") or "—"])
        writer.writerow(["Month", p.get("month") or "—"])
        writer.writerow(["Base Salary", f"{_safe_float(p.get('base_salary')):.2f}"])
        writer.writerow(["Bonus", f"{_safe_float(p.get('bonus')):.2f}"])
        writer.writerow(["Deductions", f"{_safe_float(p.get('deductions')):.2f}"])
        writer.writerow(["Net Salary", f"{_safe_float(p.get('net_salary')):.2f}"])
        writer.writerow(["Status", p.get("status") or "—"])
        return Response(buffer.getvalue(), mimetype="text/csv",
                         headers={"Content-Disposition": f"attachment; filename={base_filename}.csv"})

    buffer = build_payslip_pdf(
        guard_name=guard.get("full_name") or "—", guard_code=guard.get("guard_id") or "—",
        cnic=guard.get("cnic") or "—", phone=guard.get("phone") or "—",
        month_label=p.get("month") or "—", base_salary=_safe_float(p.get("base_salary")),
        bonus=_safe_float(p.get("bonus")), deductions=_safe_float(p.get("deductions")),
        net_salary=_safe_float(p.get("net_salary")), status=p.get("status") or "Pending",
        pending_advances=pending_advances,
    )
    return Response(buffer.getvalue(), mimetype="application/pdf",
                     headers={"Content-Disposition": f"attachment; filename={base_filename}.pdf"})


def _safe_float(value, default=0.0):
    try:
        return float(value) if value is not None and value != "" else default
    except (TypeError, ValueError):
        return default


def _get_clients_list(client):
    """Active (and all) clients for invoice dropdowns."""
    try:
        res = (
            client.table("clients")
            .select("id, client_name, company_name, monthly_billing_rate, rate_per_guard, status")
            .order("client_name")
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def _safe_query_rows(query):
    """Run a Supabase query and return [] on failure."""
    try:
        result = query.execute()
        return result.data or []
    except Exception:
        return []


def _parse_iso_date(raw_value, fallback):
    """Parse YYYY-MM-DD input safely."""
    if not raw_value:
        return fallback
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        return fallback


def _month_labels_between(start_date, end_date):
    """Return month labels matching payroll.month values between dates."""
    labels = []
    cursor = start_date.replace(day=1)
    end_month = end_date.replace(day=1)
    while cursor <= end_month:
        labels.append(cursor.strftime("%B %Y"))
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return labels


def _month_sort_anchor(month_label):
    """Convert `July 2026` style labels to a sortable YYYY-MM-01 key."""
    try:
        return datetime.strptime(month_label, "%B %Y").date().isoformat()
    except ValueError:
        return month_label


def _resolve_expense_filters():
    """Build normalized filters for the expense tracker."""
    today = date.today()
    period = request.args.get("period", "this_month").strip() or "this_month"
    category = request.args.get("category", "").strip()
    payment_method = request.args.get("payment_method", "").strip()
    search = request.args.get("q", "").strip()

    if period == "last_month":
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - timedelta(days=1)
        start_date = end_date.replace(day=1)
    elif period == "custom":
        fallback_start = today.replace(day=1)
        start_date = _parse_iso_date(request.args.get("start_date", "").strip(), fallback_start)
        end_date = _parse_iso_date(request.args.get("end_date", "").strip(), today)
    else:
        period = "this_month"
        start_date = today.replace(day=1)
        end_date = today

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    return {
        "period": period,
        "category": category,
        "payment_method": payment_method,
        "search": search,
        "start_date": start_date,
        "end_date": end_date,
        "start_date_value": start_date.isoformat(),
        "end_date_value": end_date.isoformat(),
        "month_labels": _month_labels_between(start_date, end_date),
    }


def _row_matches_filters(row, filters):
    """Apply category/payment/search filters to a normalized ledger row."""
    category = filters["category"]
    payment_method = filters["payment_method"]
    search = filters["search"].lower()

    if category and row.get("category") != category:
        return False
    if payment_method and row.get("payment_method") != payment_method:
        return False
    if search:
        haystack = " ".join(
            str(row.get(key) or "")
            for key in ("description", "notes", "reference_number", "source_label")
        ).lower()
        if search not in haystack:
            return False
    return True


def _fetch_manual_expense_rows(client, filters):
    rows = _safe_query_rows(
        client.table("manual_expenses")
        .select(
            "id, category, description, amount, expense_date, payment_method, "
            "reference_number, notes, created_at"
        )
        .gte("expense_date", filters["start_date_value"])
        .lte("expense_date", filters["end_date_value"])
        .order("expense_date", desc=True)
    )
    ledger = []
    for row in rows:
        ledger.append(
            {
                "id": row.get("id"),
                "source_type": "manual",
                "source_label": "Manual Expense",
                "category": row.get("category") or "Miscellaneous",
                "description": row.get("description") or "Manual expense entry",
                "notes": row.get("notes") or "",
                "amount": _safe_float(row.get("amount")),
                "expense_date": row.get("expense_date"),
                "sort_key": row.get("expense_date") or "",
                "payment_method": row.get("payment_method") or "",
                "reference_number": row.get("reference_number") or "",
            }
        )
    return ledger


def _fetch_payroll_expense_rows(client, filters):
    month_labels = filters["month_labels"]
    if not month_labels:
        return []

    query = client.table("payroll").select(
        "id, month, net_salary, status, guards(full_name, guard_id)"
    )
    if len(month_labels) == 1:
        query = query.eq("month", month_labels[0])
    else:
        query = query.in_("month", month_labels)

    rows = _safe_query_rows(query.order("created_at", desc=True))
    ledger = []
    for row in rows:
        guard = row.get("guards") or {}
        guard_name = guard.get("full_name") or "Unknown Guard"
        month = row.get("month") or ""
        status = row.get("status") or "Pending"
        ledger.append(
            {
                "id": row.get("id"),
                "source_type": "payroll",
                "source_label": "Payroll",
                "category": "Guard Salaries",
                "description": f"{guard_name} salary for {month}".strip(),
                "notes": f"Payroll status: {status}",
                "amount": _safe_float(row.get("net_salary")),
                "expense_date": month,
                "sort_key": _month_sort_anchor(month),
                "payment_method": "Bank Transfer" if status == "Paid" else "System",
                "reference_number": guard.get("guard_id") or "",
            }
        )
    return ledger


def _fetch_weapon_purchase_rows(client, filters):
    rows = _safe_query_rows(
        client.table("weapon_purchases")
        .select("id, vendor_name, purchase_cost, purchase_date, invoice_reference, notes")
        .gte("purchase_date", filters["start_date_value"])
        .lte("purchase_date", filters["end_date_value"])
        .order("purchase_date", desc=True)
    )
    ledger = []
    for row in rows:
        ledger.append(
            {
                "id": row.get("id"),
                "source_type": "weapon_purchase",
                "source_label": "Weapon Procurement",
                "category": "Weapon Purchase",
                "description": row.get("vendor_name") or "Weapon purchase",
                "notes": row.get("notes") or "",
                "amount": _safe_float(row.get("purchase_cost")),
                "expense_date": row.get("purchase_date"),
                "sort_key": row.get("purchase_date") or "",
                "payment_method": "System",
                "reference_number": row.get("invoice_reference") or "",
            }
        )
    return ledger


def _fetch_uniform_rows(client, filters):
    rows = _safe_query_rows(
        client.table("expenses")
        .select("id, item_type, description, quantity, amount, expense_date")
        .gte("expense_date", filters["start_date_value"])
        .lte("expense_date", filters["end_date_value"])
        .order("expense_date", desc=True)
    )
    ledger = []
    for row in rows:
        qty = row.get("quantity") or 1
        item_type = row.get("item_type") or "Gear"
        description = row.get("description") or f"{item_type} purchase"
        ledger.append(
            {
                "id": row.get("id"),
                "source_type": "uniform_expense",
                "source_label": "Uniform / Gear",
                "category": "Uniforms & Tactical Gear",
                "description": description,
                "notes": f"Quantity: {qty}",
                "amount": _safe_float(row.get("amount")),
                "expense_date": row.get("expense_date"),
                "sort_key": row.get("expense_date") or "",
                "payment_method": "System",
                "reference_number": item_type,
            }
        )
    return ledger


def _build_expense_tracker_payload(client, filters):
    """Merge manual + automated cost records into one filtered ledger."""
    manual_rows = _fetch_manual_expense_rows(client, filters)
    payroll_rows = _fetch_payroll_expense_rows(client, filters)
    weapon_rows = _fetch_weapon_purchase_rows(client, filters)
    uniform_rows = _fetch_uniform_rows(client, filters)

    combined = manual_rows + payroll_rows + weapon_rows + uniform_rows
    filtered = [row for row in combined if _row_matches_filters(row, filters)]
    filtered.sort(key=lambda row: str(row.get("sort_key") or ""), reverse=True)

    summary = {
        "manual_total": sum(row["amount"] for row in manual_rows),
        "payroll_total": sum(row["amount"] for row in payroll_rows),
        "weapon_total": sum(row["amount"] for row in weapon_rows),
        "uniform_total": sum(row["amount"] for row in uniform_rows),
    }
    summary["operational_total"] = (
        summary["payroll_total"] + summary["weapon_total"] + summary["uniform_total"]
    )
    summary["filtered_total"] = sum(row["amount"] for row in filtered)

    return {
        "ledger_rows": filtered,
        "summary": summary,
    }


def _next_invoice_number(client):
    """Generate sequential invoice numbers like INV-2026-001."""
    year = date.today().year
    prefix = f"INV-{year}-"
    try:
        res = (
            client.table("invoices")
            .select("invoice_number")
            .like("invoice_number", f"{prefix}%")
            .order("invoice_number", desc=True)
            .limit(50)
            .execute()
        )
        max_seq = 0
        for row in res.data or []:
            num = (row.get("invoice_number") or "").replace(prefix, "")
            try:
                max_seq = max(max_seq, int(num))
            except ValueError:
                continue
        return f"{prefix}{max_seq + 1:03d}"
    except Exception:
        return f"{prefix}001"


def _refresh_overdue_statuses(client, invoices):
    """Flip Unpaid invoices past due_date to Overdue (best-effort)."""
    today = date.today()
    for inv in invoices:
        if inv.get("status") != "Unpaid":
            continue
        due_raw = inv.get("due_date")
        if not due_raw:
            continue
        try:
            due = date.fromisoformat(str(due_raw)[:10])
        except ValueError:
            continue
        if due < today:
            try:
                client.table("invoices").update({"status": "Overdue"}).eq("id", inv["id"]).execute()
                inv["status"] = "Overdue"
            except Exception:
                pass
    return invoices


@finance_bp.route("/dashboard")
@login_required
def dashboard():
    client = get_session_client()

    total_revenue = 0.0
    active_clients = 0
    try:
        clients_res = (
            client.table("clients")
            .select("status, monthly_billing_rate, rate_per_guard")
            .execute()
        )
        for c in clients_res.data or []:
            if (c.get("status") or "").strip() != "Active":
                continue
            active_clients += 1
            rate = c.get("monthly_billing_rate")
            if rate is None or rate == "":
                rate = c.get("rate_per_guard")
            total_revenue += _safe_float(rate)
    except Exception as e:
        flash(f"Could not load client billing rates: {e}", "error")

    total_expenses = 0.0
    paid_slips = 0
    try:
        payroll_res = (
            client.table("payroll")
            .select("net_salary, status")
            .eq("status", "Paid")
            .execute()
        )
        for p in payroll_res.data or []:
            paid_slips += 1
            total_expenses += _safe_float(p.get("net_salary"))
    except Exception as e:
        flash(f"Could not load payroll expenses: {e}", "error")

    net_profit = total_revenue - total_expenses
    margin_pct = (net_profit / total_revenue * 100.0) if total_revenue > 0 else 0.0

    # Invoice snapshot
    invoice_stats = {"Paid": 0, "Unpaid": 0, "Overdue": 0, "outstanding": 0.0}
    recent_invoices = []
    try:
        inv_res = (
            client.table("invoices")
            .select(
                "id, invoice_number, amount, issue_date, due_date, status, created_at, "
                "clients(client_name, company_name)"
            )
            .order("created_at", desc=True)
            .limit(8)
            .execute()
        )
        recent_invoices = _refresh_overdue_statuses(client, inv_res.data or [])

        all_inv = client.table("invoices").select("status, amount").execute()
        for inv in all_inv.data or []:
            st = inv.get("status")
            amt = _safe_float(inv.get("amount"))
            if st in invoice_stats:
                invoice_stats[st] += 1
            if st in ("Unpaid", "Overdue"):
                invoice_stats["outstanding"] += amt
    except Exception:
        pass

    metrics = {
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "margin_pct": margin_pct,
        "active_clients": active_clients,
        "paid_slips": paid_slips,
        "invoice_stats": invoice_stats,
    }

    return render_template(
        "finance/dashboard.html",
        metrics=metrics,
        recent_invoices=recent_invoices,
    )


@finance_bp.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses_tracker():
    client = get_session_client()

    if request.method == "POST":
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        amount = _safe_float(request.form.get("amount", "").strip())
        expense_date = request.form.get("expense_date", "").strip() or date.today().isoformat()
        payment_method = request.form.get("payment_method", "").strip()
        reference_number = request.form.get("reference_number", "").strip()
        notes = request.form.get("notes", "").strip()

        if category not in EXPENSE_CATEGORIES:
            flash("Please choose a valid expense category.", "error")
            return redirect(url_for("finance.expenses_tracker"))
        if amount <= 0:
            flash("Expense amount must be greater than zero.", "error")
            return redirect(url_for("finance.expenses_tracker"))
        if payment_method not in PAYMENT_METHODS:
            flash("Please choose a valid payment method.", "error")
            return redirect(url_for("finance.expenses_tracker"))

        payload = {
            "category": category,
            "description": description or "Manual expense entry",
            "amount": amount,
            "expense_date": expense_date,
            "payment_method": payment_method,
            "reference_number": reference_number or None,
            "notes": notes or None,
        }

        try:
            client.table("manual_expenses").insert(payload).execute()
            flash("Expense entry logged successfully.", "success")
        except Exception as exc:
            message = str(exc)
            if "manual_expenses" in message or "PGRST204" in message or "schema cache" in message:
                flash(
                    "Expense tracker table missing. Run the new expense migration in Supabase SQL Editor, then try again.",
                    "error",
                )
            else:
                flash(f"Failed to save expense entry: {message}", "error")
        return redirect(url_for("finance.expenses_tracker"))

    filters = _resolve_expense_filters()
    tracker = _build_expense_tracker_payload(client, filters)

    return render_template(
        "finance/expenses.html",
        categories=EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        filters=filters,
        ledger_rows=tracker["ledger_rows"],
        summary=tracker["summary"],
    )


@finance_bp.route("/invoices", methods=["GET", "POST"])
@login_required
def invoices():
    client = get_session_client()

    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()
        amount_raw = request.form.get("amount", "").strip()
        issue_date = request.form.get("issue_date", "").strip() or date.today().isoformat()
        due_date = request.form.get("due_date", "").strip()
        status = request.form.get("status", "Unpaid").strip() or "Unpaid"
        invoice_number = request.form.get("invoice_number", "").strip()

        if not client_id:
            flash("Please select a client for this invoice.", "error")
            return redirect(url_for("finance.invoices"))

        amount = _safe_float(amount_raw)
        if amount <= 0:
            flash("Invoice amount must be greater than zero.", "error")
            return redirect(url_for("finance.invoices"))

        if not due_date:
            try:
                due_date = (date.fromisoformat(issue_date) + timedelta(days=30)).isoformat()
            except ValueError:
                due_date = (date.today() + timedelta(days=30)).isoformat()

        if not invoice_number:
            invoice_number = _next_invoice_number(client)

        if status not in ("Paid", "Unpaid", "Overdue"):
            status = "Unpaid"

        payload = {
            "client_id": client_id,
            "invoice_number": invoice_number,
            "amount": amount,
            "issue_date": issue_date,
            "due_date": due_date,
            "status": status,
        }

        try:
            client.table("invoices").insert(payload).execute()
            flash(f"Invoice {invoice_number} created successfully!", "success")
            return redirect(url_for("finance.invoices"))
        except Exception as e:
            err_msg = str(e)
            if "PGRST204" in err_msg or "schema cache" in err_msg or "Could not find the table" in err_msg:
                flash(
                    "Invoices table missing. Run schema_chunk7.sql in your Supabase SQL Editor, then try again.",
                    "error",
                )
            else:
                flash(f"Failed to create invoice: {err_msg}", "error")
            return redirect(url_for("finance.invoices"))

    status_filter = request.args.get("status", "").strip()
    client_filter = request.args.get("client_id", "").strip()
    month_filter = request.args.get("month", "").strip()  # "YYYY-MM"

    query = (
        client.table("invoices")
        .select(
            "id, client_id, invoice_number, amount, issue_date, due_date, status, created_at, "
            "clients(id, client_name, company_name, phone)"
        )
        .order("created_at", desc=True)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    if client_filter:
        query = query.eq("client_id", client_filter)
    if month_filter:
        try:
            month_start = datetime.strptime(month_filter, "%Y-%m").date()
            month_end = (
                month_start.replace(year=month_start.year + 1, month=1)
                if month_start.month == 12
                else month_start.replace(month=month_start.month + 1)
            ) - timedelta(days=1)
            query = query.gte("issue_date", month_start.isoformat()).lte("issue_date", month_end.isoformat())
        except ValueError:
            month_filter = ""

    query = (
        client.table("invoices")
        .select(
            "id, client_id, invoice_number, amount, issue_date, due_date, status, created_at, "
            "clients(id, client_name, company_name, phone)"
        )
        .order("created_at", desc=True)
    )
    if status_filter:
        query = query.eq("status", status_filter)

    try:
        res = query.execute()
        invoices_list = _refresh_overdue_statuses(client, res.data or [])
    except Exception as e:
        flash(f"Error loading invoices: {e}", "error")
        invoices_list = []

    counts = {"All": 0, "Paid": 0, "Unpaid": 0, "Overdue": 0}
    totals = {"billed": 0.0, "collected": 0.0, "outstanding": 0.0}
    try:
        all_res = client.table("invoices").select("status, amount").execute()
        rows = all_res.data or []
        counts["All"] = len(rows)
        for inv in rows:
            st = inv.get("status")
            amt = _safe_float(inv.get("amount"))
            totals["billed"] += amt
            if st in counts:
                counts[st] += 1
            if st == "Paid":
                totals["collected"] += amt
            elif st in ("Unpaid", "Overdue"):
                totals["outstanding"] += amt
    except Exception:
        pass

    clients = _get_clients_list(client)
    default_invoice_number = _next_invoice_number(client)
    default_issue = date.today().isoformat()
    default_due = (date.today() + timedelta(days=30)).isoformat()
    default_target_month = date.today().strftime("%Y-%m")

    return render_template(
        "finance/invoices.html",
        invoices=invoices_list,
        clients=clients,
        status_filter=status_filter,
        counts=counts,
        totals=totals,
        default_invoice_number=default_invoice_number,
        default_issue=default_issue,
        default_due=default_due,
        default_target_month=default_target_month,
        client_filter=client_filter,
        month_filter=month_filter,
    )


@finance_bp.route("/invoices/pay/<invoice_id>", methods=["GET", "POST"])
@login_required
def mark_invoice_paid(invoice_id):
    client = get_session_client()
    try:
        client.table("invoices").update({"status": "Paid"}).eq("id", invoice_id).execute()
        flash("Invoice marked as Paid.", "success")
    except Exception as e:
        flash(f"Failed to update invoice: {e}", "error")
    return redirect(url_for("finance.invoices"))

@finance_bp.route("/invoices/bulk-generate", methods=["POST"])
@login_required
def bulk_generate_invoices():
    """Auto-create Unpaid invoices for every active client for a target month,
    skipping clients that already have an invoice issued in that month."""
    client = get_session_client()

    target_month = request.form.get("target_month", "").strip()  # "YYYY-MM"
    due_offset_raw = request.form.get("due_offset_days", "30").strip()

    if not target_month:
        flash("Please select a target month.", "error")
        return redirect(url_for("finance.invoices"))

    try:
        month_start = datetime.strptime(target_month, "%Y-%m").date()
    except ValueError:
        flash("Invalid target month format.", "error")
        return redirect(url_for("finance.invoices"))

    try:
        due_offset_days = int(due_offset_raw)
    except ValueError:
        due_offset_days = 30

    month_end = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    ) - timedelta(days=1)
    month_label = month_start.strftime("%B %Y")

    # Active clients
    try:
        clients_res = (
            client.table("clients")
            .select("id, client_name, company_name, monthly_billing_rate, rate_per_guard, status")
            .eq("status", "Active")
            .execute()
        )
        active_clients = clients_res.data or []
    except Exception as e:
        flash(f"Failed to load clients: {e}", "error")
        return redirect(url_for("finance.invoices"))

    if not active_clients:
        flash("No active clients found to generate invoices for.", "error")
        return redirect(url_for("finance.invoices"))

    # Clients that already have an invoice issued within the target month
    try:
        existing_res = (
            client.table("invoices")
            .select("client_id")
            .gte("issue_date", month_start.isoformat())
            .lte("issue_date", month_end.isoformat())
            .execute()
        )
        existing_client_ids = {row.get("client_id") for row in (existing_res.data or [])}
    except Exception as e:
        flash(f"Failed to check existing invoices for {month_label}: {e}", "error")
        return redirect(url_for("finance.invoices"))

    issue_date = date.today().isoformat()
    due_date = (date.today() + timedelta(days=due_offset_days)).isoformat()

    # Reserve a block of sequential invoice numbers up front to avoid re-querying per client
    starting_number = _next_invoice_number(client)
    try:
        prefix, seq_str = starting_number.rsplit("-", 1)
        seq_counter = int(seq_str)
        prefix = prefix + "-"
    except ValueError:
        prefix = f"INV-{date.today().year}-"
        seq_counter = 1

    created_count = 0
    skipped_existing = 0
    skipped_no_rate = 0
    failed_count = 0

    for c in active_clients:
        client_id = c.get("id")
        if not client_id or client_id in existing_client_ids:
            skipped_existing += 1
            continue

        rate = c.get("monthly_billing_rate")
        if rate is None or rate == "":
            rate = c.get("rate_per_guard")
        amount = _safe_float(rate)

        if amount <= 0:
            skipped_no_rate += 1
            continue

        invoice_number = f"{prefix}{seq_counter:03d}"
        seq_counter += 1

        payload = {
            "client_id": client_id,
            "invoice_number": invoice_number,
            "amount": amount,
            "issue_date": issue_date,
            "due_date": due_date,
            "status": "Unpaid",
        }

        try:
            client.table("invoices").insert(payload).execute()
            created_count += 1
        except Exception:
            failed_count += 1

    total_skipped = skipped_existing + skipped_no_rate + failed_count
    message = (
        f"Successfully generated {created_count} new invoice"
        f"{'s' if created_count != 1 else ''} for {month_label} "
        f"({total_skipped} skipped as already created)"
    )
    if skipped_no_rate or failed_count:
        message += f" — {skipped_no_rate} had no billing rate, {failed_count} failed to save"

    flash(message, "success" if created_count > 0 else "error")
    return redirect(url_for("finance.invoices", month=target_month))

def _build_payroll_export_rows(client, status_filter="", month_filter=""):
    query = (
        client.table("payroll")
        .select(
            "id, month, base_salary, bonus, deductions, net_salary, status, created_at, "
            "guards(guard_id, full_name, cnic, phone)"
        )
        .order("created_at", desc=True)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    if month_filter:
        query = query.eq("month", month_filter)
    return _safe_query_rows(query)


@finance_bp.route("/export/payroll")
@login_required
def export_payroll():
    """Unified payroll export — ?format=csv (default) or ?format=pdf."""
    client = get_session_client()
    export_format = request.args.get("format", "csv").strip().lower()
    status_filter = request.args.get("status", "").strip()
    month_filter = request.args.get("month", "").strip()

    rows = _build_payroll_export_rows(client, status_filter, month_filter)

    if export_format == "pdf":
        columns = ["Guard ID", "Guard Name", "Month", "Base", "Bonus", "Deductions", "Net Salary", "Status"]
        table_rows = []
        for p in rows:
            guard = p.get("guards") or {}
            table_rows.append([
                guard.get("guard_id") or "—", guard.get("full_name") or "—", p.get("month") or "—",
                f"Rs. {_safe_float(p.get('base_salary')):,.2f}",
                f"Rs. {_safe_float(p.get('bonus')):,.2f}",
                f"Rs. {_safe_float(p.get('deductions')):,.2f}",
                f"Rs. {_safe_float(p.get('net_salary')):,.2f}",
                p.get("status") or "—",
            ])
        subtitle_bits = []
        if month_filter:
            subtitle_bits.append(f"Month: {month_filter}")
        if status_filter:
            subtitle_bits.append(f"Status: {status_filter}")
        subtitle = " · ".join(subtitle_bits) or "All recorded payslips"

        buffer = build_ledger_pdf(title="Payroll Ledger", subtitle=subtitle, columns=columns, rows=table_rows)
        filename = f"pakwatan_payroll_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return Response(buffer.getvalue(), mimetype="application/pdf",
                         headers={"Content-Disposition": f"attachment; filename={filename}"})

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Payslip ID", "Guard ID", "Guard Name", "CNIC", "Phone", "Month",
                      "Base Salary", "Bonus", "Deductions", "Net Salary", "Status", "Created At"])
    for p in rows:
        guard = p.get("guards") or {}
        writer.writerow([
            p.get("id") or "", guard.get("guard_id") or "", guard.get("full_name") or "",
            guard.get("cnic") or "", guard.get("phone") or "", p.get("month") or "",
            f"{_safe_float(p.get('base_salary')):.2f}", f"{_safe_float(p.get('bonus')):.2f}",
            f"{_safe_float(p.get('deductions')):.2f}", f"{_safe_float(p.get('net_salary')):.2f}",
            p.get("status") or "", p.get("created_at") or "",
        ])
    filename = f"pakwatan_payroll_ledger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(buffer.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


@finance_bp.route("/export/payroll/csv")
@login_required
def export_payroll_csv():
    """Kept for backward compatibility with existing template links."""
    return redirect(url_for("finance.export_payroll", format="csv",
                             status=request.args.get("status", ""), month=request.args.get("month", "")))



@finance_bp.route("/export/invoices")
@login_required
def export_invoices():
    """Invoice ledger export — bulk, or scoped to one client/month, ?format=csv|pdf."""
    client = get_session_client()
    export_format = request.args.get("format", "csv").strip().lower()
    status_filter = request.args.get("status", "").strip()
    client_filter = request.args.get("client_id", "").strip()
    month_filter = request.args.get("month", "").strip()

    query = (
        client.table("invoices")
        .select("id, invoice_number, amount, issue_date, due_date, status, created_at, "
                "clients(client_name, company_name, phone)")
        .order("created_at", desc=True)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    if client_filter:
        query = query.eq("client_id", client_filter)
    if month_filter:
        try:
            month_start = datetime.strptime(month_filter, "%Y-%m").date()
            month_end = (
                month_start.replace(year=month_start.year + 1, month=1)
                if month_start.month == 12
                else month_start.replace(month=month_start.month + 1)
            ) - timedelta(days=1)
            query = query.gte("issue_date", month_start.isoformat()).lte("issue_date", month_end.isoformat())
        except ValueError:
            month_filter = ""

    rows = _safe_query_rows(query)

    client_label = None
    if client_filter:
        if rows:
            client_label = (rows[0].get("clients") or {}).get("client_name")
        else:
            try:
                c_res = client.table("clients").select("client_name").eq("id", client_filter).limit(1).execute()
                if c_res.data:
                    client_label = c_res.data[0].get("client_name")
            except Exception:
                pass

    subtitle_bits = []
    if client_label:
        subtitle_bits.append(f"Client: {client_label}")
    if month_filter:
        subtitle_bits.append(f"Month: {month_filter}")
    if status_filter:
        subtitle_bits.append(f"Status: {status_filter}")
    subtitle = " · ".join(subtitle_bits) or "All client invoices"
    title = f"{client_label} — Invoice Ledger" if client_label else "Client Invoice Ledger"
    filename_stub = "pakwatan_invoices" + (f"_{client_label.replace(' ', '_')}" if client_label else "")

    if export_format == "pdf":
        columns = ["Invoice #", "Client", "Amount", "Issue Date", "Due Date", "Status"]
        table_rows = []
        for inv in rows:
            c = inv.get("clients") or {}
            table_rows.append([
                inv.get("invoice_number") or "—", c.get("client_name") or "—",
                f"Rs. {_safe_float(inv.get('amount')):,.2f}",
                inv.get("issue_date") or "—", inv.get("due_date") or "—", inv.get("status") or "—",
            ])
        buffer = build_ledger_pdf(title=title, subtitle=subtitle, columns=columns, rows=table_rows)
        filename = f"{filename_stub}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return Response(buffer.getvalue(), mimetype="application/pdf",
                         headers={"Content-Disposition": f"attachment; filename={filename}"})

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Invoice ID", "Invoice #", "Client", "Company", "Phone", "Amount",
                      "Issue Date", "Due Date", "Status", "Created At"])
    for inv in rows:
        c = inv.get("clients") or {}
        writer.writerow([
            inv.get("id") or "", inv.get("invoice_number") or "", c.get("client_name") or "",
            c.get("company_name") or "", c.get("phone") or "", f"{_safe_float(inv.get('amount')):.2f}",
            inv.get("issue_date") or "", inv.get("due_date") or "", inv.get("status") or "", inv.get("created_at") or "",
        ])
    filename = f"{filename_stub}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(buffer.getvalue(), mimetype="text/csv",
                     headers={"Content-Disposition": f"attachment; filename={filename}"})


@finance_bp.route("/export/invoice/<invoice_id>")
@login_required
def export_single_invoice(invoice_id):
    """Export exactly one invoice as a formatted PDF or CSV."""
    client = get_session_client()
    export_format = request.args.get("format", "pdf").strip().lower()

    try:
        res = (
            client.table("invoices")
            .select("id, invoice_number, amount, issue_date, due_date, status, "
                    "clients(client_name, company_name, phone)")
            .eq("id", invoice_id).limit(1).execute()
        )
        rows = res.data or []
    except Exception as e:
        flash(f"Failed to load invoice: {e}", "error")
        return redirect(url_for("finance.invoices"))

    if not rows:
        flash("Invoice not found.", "error")
        return redirect(url_for("finance.invoices"))

    inv = rows[0]
    c = inv.get("clients") or {}
    base_filename = f"invoice_{inv.get('invoice_number') or invoice_id}"

    if export_format == "csv":
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Field", "Value"])
        writer.writerow(["Invoice #", inv.get("invoice_number") or "—"])
        writer.writerow(["Client", c.get("client_name") or "—"])
        writer.writerow(["Company", c.get("company_name") or "—"])
        writer.writerow(["Phone", c.get("phone") or "—"])
        writer.writerow(["Amount", f"{_safe_float(inv.get('amount')):.2f}"])
        writer.writerow(["Issue Date", inv.get("issue_date") or "—"])
        writer.writerow(["Due Date", inv.get("due_date") or "—"])
        writer.writerow(["Status", inv.get("status") or "—"])
        return Response(buffer.getvalue(), mimetype="text/csv",
                         headers={"Content-Disposition": f"attachment; filename={base_filename}.csv"})

    columns = ["Field", "Value"]
    table_rows = [
        ["Invoice #", inv.get("invoice_number") or "—"],
        ["Client", c.get("client_name") or "—"],
        ["Company", c.get("company_name") or "—"],
        ["Amount", f"Rs. {_safe_float(inv.get('amount')):,.2f}"],
        ["Issue Date", inv.get("issue_date") or "—"],
        ["Due Date", inv.get("due_date") or "—"],
        ["Status", inv.get("status") or "—"],
    ]
    buffer = build_ledger_pdf(title=f"Invoice {inv.get('invoice_number') or ''}",
                               subtitle=c.get("client_name") or "Client invoice",
                               columns=columns, rows=table_rows)
    return Response(buffer.getvalue(), mimetype="application/pdf",
                     headers={"Content-Disposition": f"attachment; filename={base_filename}.pdf"})
