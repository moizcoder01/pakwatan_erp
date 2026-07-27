"""
blueprints/finance.py
---------------------
Invoicing Module, Executive Financial Dashboard & CSV Export Engine.

Routes:
  - GET        /finance/dashboard              : Revenue, payroll expense & net profit overview
  - GET/POST   /finance/invoices               : Client invoice listing + creation form
  - GET/POST   /finance/invoices/pay/<id>      : Mark invoice as Paid
  - GET        /finance/export/payroll/csv     : Download full payroll ledger as CSV
"""

import csv
from datetime import date, datetime, timedelta
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


@finance_bp.route("/export/payroll/csv")
@login_required
def export_payroll_csv():
    """Stream the full payroll ledger as a downloadable CSV file."""
    client = get_session_client()

    try:
        res = (
            client.table("payroll")
            .select(
                "id, month, base_salary, bonus, deductions, net_salary, status, created_at, "
                "guards(guard_id, full_name, cnic, phone)"
            )
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
    except Exception as e:
        flash(f"Failed to export payroll CSV: {e}", "error")
        return redirect(url_for("finance.dashboard"))

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Payslip ID",
            "Guard ID",
            "Guard Name",
            "CNIC",
            "Phone",
            "Month",
            "Base Salary",
            "Bonus",
            "Deductions",
            "Net Salary",
            "Status",
            "Created At",
        ]
    )

    for p in rows:
        guard = p.get("guards") or {}
        writer.writerow(
            [
                p.get("id") or "",
                guard.get("guard_id") or "",
                guard.get("full_name") or "",
                guard.get("cnic") or "",
                guard.get("phone") or "",
                p.get("month") or "",
                f"{_safe_float(p.get('base_salary')):.2f}",
                f"{_safe_float(p.get('bonus')):.2f}",
                f"{_safe_float(p.get('deductions')):.2f}",
                f"{_safe_float(p.get('net_salary')):.2f}",
                p.get("status") or "",
                p.get("created_at") or "",
            ]
        )

    filename = f"pakwatan_payroll_ledger_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
