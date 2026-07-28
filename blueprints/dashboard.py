"""
High-level ERP dashboard with executive KPIs, alerts, and chart analytics.

Visibility is role-scoped:
  - Admin / Ops: org-wide operational + financial metrics
  - Client: deployment-only snapshot, no financial figures
"""

from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, session

from decorators import login_required
from supabase_client import get_session_client

dashboard_bp = Blueprint("dashboard", __name__)

EXPENSE_BUCKETS = ("Payroll", "Armory/Gear", "Utilities", "Rent", "Transport")
LICENSE_EXPIRY_COLUMNS = ("license_expiry", "license_expiry_date", "expiry_date")


def _safe_count(query):
    try:
        return query.execute().count or 0
    except Exception:
        return 0


def _safe_data(query, default=None):
    try:
        result = query.execute()
        return result.data or (default if default is not None else [])
    except Exception:
        return default if default is not None else []


def _safe_float(value, default=0.0):
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _execute_rows(query):
    try:
        result = query.execute()
        return True, result.data or []
    except Exception:
        return False, []


def _client_guard_ids(client, client_id):
    rows = _safe_data(client.table("guards").select("id").eq("assigned_client_id", client_id))
    return [row["id"] for row in rows]


def _normalize_attendance_row(row):
    normalized = dict(row)
    normalized["display_date"] = normalized.get("attendance_date") or normalized.get("date")
    return normalized


def _recent_attendance(client, guard_ids=None, limit=8):
    select_with_active = (
        "id, attendance_date, status, reason_for_absence, overtime_hours, "
        "guards!inner(full_name, guard_id, is_active)"
    )
    select_basic = (
        "id, attendance_date, status, reason_for_absence, overtime_hours, "
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
            if guard_ids is not None:
                if not guard_ids:
                    return []
                query = query.in_("guard_id", guard_ids)
            rows = query.execute().data or []
            return [_normalize_attendance_row(row) for row in rows]
        except Exception:
            continue

    return []


def _recent_complaints(client, client_id=None, limit=6):
    query = (
        client.table("complaints")
        .select("logged_at, complaint_details, resolution_status, clients(client_name), guards(full_name)")
        .order("logged_at", desc=True)
        .limit(limit)
    )
    if client_id:
        query = query.eq("client_id", client_id)
    return _safe_data(query)


def _recent_salary_advances(client, limit=6):
    query = (
        client.table("salary_advances")
        .select("advance_date, amount, reason, is_deducted, guards(full_name)")
        .order("advance_date", desc=True)
        .limit(limit)
    )
    return _safe_data(query)


def _month_start(months_back):
    today = date.today().replace(day=1)
    year = today.year
    month = today.month - months_back
    while month <= 0:
        year -= 1
        month += 12
    return date(year, month, 1)


def _month_sequence(count=6):
    labels = []
    for months_back in range(count - 1, -1, -1):
        month_date = _month_start(months_back)
        labels.append(
            {
                "label": month_date.strftime("%b %Y"),
                "payroll_label": month_date.strftime("%B %Y"),
                "start": month_date.isoformat(),
                "key": month_date.strftime("%Y-%m"),
            }
        )
    return labels


def _parse_date_key(raw_value):
    if not raw_value:
        return None
    raw_value = str(raw_value)[:10]
    try:
        return date.fromisoformat(raw_value).strftime("%Y-%m")
    except ValueError:
        return None


def _parse_payroll_month_key(raw_value):
    if not raw_value:
        return None
    try:
        return datetime.strptime(str(raw_value), "%B %Y").strftime("%Y-%m")
    except ValueError:
        return None


def _bucket_manual_category(category):
    category = (category or "").strip()
    if category == "Rent":
        return "Rent"
    if category == "Fuel & Transport":
        return "Transport"
    if category in ("Weapon Purchase", "Uniforms & Tactical Gear"):
        return "Armory/Gear"
    return "Utilities"


def _sum_invoice_revenue(client, month_start_value, month_end_value):
    rows = _safe_data(
        client.table("invoices")
        .select("amount")
        .gte("issue_date", month_start_value)
        .lte("issue_date", month_end_value)
    )
    return sum(_safe_float(row.get("amount")) for row in rows)


def _sum_current_month_payroll(client, payroll_label):
    rows = _safe_data(
        client.table("payroll")
        .select("net_salary")
        .eq("month", payroll_label)
    )
    return sum(_safe_float(row.get("net_salary")) for row in rows)


def _sum_active_guard_base_salary(client):
    rows = _safe_data(
        client.table("guards")
        .select("base_salary")
        .eq("is_active", True)
    )
    return sum(_safe_float(row.get("base_salary")) for row in rows)


def _current_month_manual_expenses(client, month_start_value, month_end_value):
    rows = _safe_data(
        client.table("manual_expenses")
        .select("category, amount")
        .gte("expense_date", month_start_value)
        .lte("expense_date", month_end_value)
    )
    total = 0.0
    buckets = {bucket: 0.0 for bucket in EXPENSE_BUCKETS}
    for row in rows:
        amount = _safe_float(row.get("amount"))
        total += amount
        buckets[_bucket_manual_category(row.get("category"))] += amount
    return total, buckets


def _current_month_armory_expenses(client, month_start_value, month_end_value):
    armory_total = 0.0

    purchase_rows = _safe_data(
        client.table("weapon_purchases")
        .select("purchase_cost")
        .gte("purchase_date", month_start_value)
        .lte("purchase_date", month_end_value)
    )
    for row in purchase_rows:
        armory_total += _safe_float(row.get("purchase_cost"))

    gear_rows = _safe_data(
        client.table("expenses")
        .select("amount")
        .gte("expense_date", month_start_value)
        .lte("expense_date", month_end_value)
    )
    for row in gear_rows:
        armory_total += _safe_float(row.get("amount"))

    return armory_total


def _build_financial_trend(client, months):
    revenue_map = {month["key"]: 0.0 for month in months}
    expense_map = {month["key"]: 0.0 for month in months}

    invoice_rows = _safe_data(client.table("invoices").select("issue_date, amount"))
    for row in invoice_rows:
        month_key = _parse_date_key(row.get("issue_date"))
        if month_key in revenue_map:
            revenue_map[month_key] += _safe_float(row.get("amount"))

    payroll_rows = _safe_data(client.table("payroll").select("month, net_salary"))
    for row in payroll_rows:
        month_key = _parse_payroll_month_key(row.get("month"))
        if month_key in expense_map:
            expense_map[month_key] += _safe_float(row.get("net_salary"))

    manual_rows = _safe_data(client.table("manual_expenses").select("expense_date, amount"))
    for row in manual_rows:
        month_key = _parse_date_key(row.get("expense_date"))
        if month_key in expense_map:
            expense_map[month_key] += _safe_float(row.get("amount"))

    purchase_rows = _safe_data(client.table("weapon_purchases").select("purchase_date, purchase_cost"))
    for row in purchase_rows:
        month_key = _parse_date_key(row.get("purchase_date"))
        if month_key in expense_map:
            expense_map[month_key] += _safe_float(row.get("purchase_cost"))

    gear_rows = _safe_data(client.table("expenses").select("expense_date, amount"))
    for row in gear_rows:
        month_key = _parse_date_key(row.get("expense_date"))
        if month_key in expense_map:
            expense_map[month_key] += _safe_float(row.get("amount"))

    return {
        "labels": [month["label"] for month in months],
        "revenue": [round(revenue_map[month["key"]], 2) for month in months],
        "expense": [round(expense_map[month["key"]], 2) for month in months],
    }


def _license_expiry_alert(client):
    today = date.today()
    in_30_days = today + timedelta(days=30)

    for column_name in LICENSE_EXPIRY_COLUMNS:
        supported, rows = _execute_rows(
            client.table("weapons")
            .select(f"id, serial_number, {column_name}")
            .not_.is_(column_name, "null")
            .lte(column_name, in_30_days.isoformat())
        )
        if not supported:
            continue
        if rows:
            return {
                "count": len(rows),
                "state": "warning",
                "label": "Weapon licenses expiring soon",
                "detail": (
                    f"{len(rows)} weapon license(s) are expired or due within 30 days."
                ),
            }
        return {
            "count": 0,
            "state": "healthy",
            "label": "Weapon licenses expiring soon",
            "detail": "No weapon licenses are expired or due within the next 30 days.",
        }
    return {
        "count": 0,
        "state": "neutral",
        "label": "Weapon license expiry tracking",
        "detail": "Run schema_chunk9.sql to enable license expiry compliance alerts.",
    }


def _admin_dashboard_payload(client):
    months = _month_sequence(6)
    current_month = months[-1]
    today = date.today()
    month_start_value = today.replace(day=1).isoformat()
    month_end_value = today.isoformat()

    active_workforce = _safe_count(
        client.table("guards").select("id", count="exact").eq("is_active", True)
    )
    guards_on_duty = _safe_count(
        client.table("guards").select("id", count="exact").eq("is_active", True).eq("duty_status", "On Duty")
    )
    guards_off_duty = max(active_workforce - guards_on_duty, 0)
    active_clients = _safe_count(
        client.table("clients").select("id", count="exact").eq("status", "Active")
    )

    monthly_revenue = _sum_invoice_revenue(client, month_start_value, month_end_value)
    payroll_total = _sum_current_month_payroll(client, current_month["payroll_label"])
    if payroll_total <= 0:
        payroll_total = _sum_active_guard_base_salary(client)

    manual_expense_total, expense_distribution = _current_month_manual_expenses(
        client,
        month_start_value,
        month_end_value,
    )
    expense_distribution["Payroll"] += payroll_total
    expense_distribution["Armory/Gear"] += _current_month_armory_expenses(
        client,
        month_start_value,
        month_end_value,
    )

    operational_expenses = payroll_total + manual_expense_total
    net_profit = monthly_revenue - operational_expenses
    net_margin_pct = (net_profit / monthly_revenue * 100.0) if monthly_revenue > 0 else 0.0

    weapons_assigned = _safe_count(
        client.table("weapons").select("id", count="exact").eq("status", "Assigned")
    )
    weapons_in_storage = _safe_count(
        client.table("weapons").select("id", count="exact").eq("status", "In Storage")
    )

    overdue_invoices = _safe_count(
        client.table("invoices").select("id", count="exact").eq("status", "Overdue")
    )
    unassigned_guards_rows = _safe_data(
        client.table("guards").select("assigned_client_id").eq("is_active", True)
    )
    unassigned_guards = sum(1 for row in unassigned_guards_rows if not row.get("assigned_client_id"))

    license_alert = _license_expiry_alert(client)

    return {
        "hero": {
            "title": "Executive ERP Dashboard",
            "subtitle": "Real-time workforce, financial, and armory telemetry across the Pakwatan operating network.",
            "period_label": current_month["label"],
        },
        "kpis": [
            {
                "title": "Active Workforce",
                "value": active_workforce,
                "context": f"On Duty {guards_on_duty} · Off Duty {guards_off_duty}",
                "pill": "Live headcount",
                "tone": "teal",
            },
            {
                "title": "Client Deployments",
                "value": active_clients,
                "context": "Active client sites under contract",
                "pill": "Portfolio",
                "tone": "amber",
            },
            {
                "title": "Monthly Invoiced Revenue",
                "value_currency": monthly_revenue,
                "context": f"Invoices issued during {current_month['label']}",
                "pill": "PKR",
                "tone": "slate",
            },
            {
                "title": "Operational Expenses",
                "value_currency": operational_expenses,
                "context": "Guard salaries + logged manual expenses",
                "pill": "PKR",
                "tone": "amber",
            },
            {
                "title": "Net Profit Margin",
                "value_currency": net_profit,
                "context": f"{net_margin_pct:.1f}% margin this month",
                "pill": "Profitability",
                "tone": "teal" if net_profit >= 0 else "red",
            },
        ],
        "charts": {
            "expense_distribution": {
                "labels": list(EXPENSE_BUCKETS),
                "values": [round(expense_distribution[bucket], 2) for bucket in EXPENSE_BUCKETS],
            },
            "financial_trend": _build_financial_trend(client, months),
        },
        "armory": {
            "assigned": weapons_assigned,
            "storage": weapons_in_storage,
            "total": weapons_assigned + weapons_in_storage,
        },
        "alerts": [
            {
                "state": "danger" if overdue_invoices else "healthy",
                "title": "Overdue Client Invoices",
                "detail": (
                    f"{overdue_invoices} invoice(s) require immediate collection follow-up."
                    if overdue_invoices
                    else "No overdue invoices detected."
                ),
                "count": overdue_invoices,
            },
            {
                "state": license_alert["state"],
                "title": license_alert["label"],
                "detail": license_alert["detail"],
                "count": license_alert["count"],
            },
            {
                "state": "danger" if unassigned_guards else "healthy",
                "title": "Unassigned Guards",
                "detail": (
                    f"{unassigned_guards} active guard(s) are available without deployment."
                    if unassigned_guards
                    else "All active guards are mapped to deployment coverage."
                ),
                "count": unassigned_guards,
            },
        ],
        "recent_attendance": _recent_attendance(client),
        "recent_complaints": _recent_complaints(client),
        "recent_advances": _recent_salary_advances(client),
    }


def _client_dashboard_payload(client, client_id):
    metrics = {
        "assigned_guards": 0,
        "guards_on_duty": 0,
        "open_complaints": 0,
        "guard_ids": [],
    }
    if client_id:
        guard_ids = _client_guard_ids(client, client_id)
        metrics["guard_ids"] = guard_ids
        metrics["assigned_guards"] = len(guard_ids)
        metrics["guards_on_duty"] = _safe_count(
            client.table("guards")
            .select("id", count="exact")
            .eq("assigned_client_id", client_id)
            .eq("duty_status", "On Duty")
        )
        metrics["open_complaints"] = _safe_count(
            client.table("complaints")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .eq("resolution_status", "Unresolved")
        )

    return {
        "hero": {
            "title": "Deployment Overview",
            "subtitle": "A live operational snapshot for your deployed guards, service coverage, and complaint status.",
            "period_label": date.today().strftime("%b %Y"),
        },
        "kpis": [
            {
                "title": "Assigned Guards",
                "value": metrics["assigned_guards"],
                "context": f"On Duty {metrics['guards_on_duty']}",
                "pill": "Coverage",
                "tone": "teal",
            },
            {
                "title": "Open Complaints",
                "value": metrics["open_complaints"],
                "context": "Tickets awaiting resolution",
                "pill": "Service Desk",
                "tone": "red" if metrics["open_complaints"] else "slate",
            },
        ],
        "charts": None,
        "armory": None,
        "alerts": [],
        "recent_attendance": _recent_attendance(client, guard_ids=metrics["guard_ids"]),
        "recent_complaints": _recent_complaints(client, client_id=client_id),
        "recent_advances": None,
    }


@dashboard_bp.route("/dashboard")
@login_required
def index():
    user = session["user"]
    client = get_session_client()

    if user["role"] in ("Admin", "Ops"):
        dashboard = _admin_dashboard_payload(client)
    else:
        dashboard = _client_dashboard_payload(client, user.get("client_id"))

    return render_template("dashboard/index.html", dashboard=dashboard)
