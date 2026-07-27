"""
blueprints/dashboard.py
------------------------
Main ERP dashboard: top metric cards + recent activity tables.

Visibility is role-scoped:
  - Admin / Ops : org-wide metrics across all clients/guards.
  - Client      : metrics and activity limited to their own client_id
                   (guards assigned to them, complaints they raised).
                   Salary/financial figures are never shown to Client role.
"""

from datetime import date

from flask import Blueprint, render_template, session

from decorators import login_required
from supabase_client import get_session_client

dashboard_bp = Blueprint("dashboard", __name__)


def _safe_count(query):
    """Run a Supabase count query, returning 0 instead of raising on error."""
    try:
        return query.execute().count or 0
    except Exception:
        return 0


def _safe_data(query, default=None):
    """Run a Supabase data query, returning a safe default instead of raising."""
    try:
        result = query.execute()
        return result.data or (default if default is not None else [])
    except Exception:
        return default if default is not None else []


def _client_guard_ids(client, client_id):
    rows = _safe_data(client.table("guards").select("id").eq("assigned_client_id", client_id))
    return [row["id"] for row in rows]


def _admin_ops_metrics(client):
    today = date.today().isoformat()
    return {
        "active_guards": _safe_count(
            client.table("guards").select("id", count="exact").eq("is_active", True)
        ),
        "guards_on_duty": _safe_count(
            client.table("guards").select("id", count="exact").eq("duty_status", "On Duty")
        ),
        "open_complaints": _safe_count(
            client.table("complaints").select("id", count="exact").eq("resolution_status", "Unresolved")
        ),
        "weapons_assigned": _safe_count(
            client.table("weapons").select("id", count="exact").eq("status", "Assigned")
        ),
        "active_clients": _safe_count(
            client.table("clients").select("id", count="exact").eq("status", "Active")
        ),
        "pending_deductions": _sum_pending_deductions(client),
        "today": today,
    }


def _sum_pending_deductions(client):
    rows = _safe_data(
        client.table("salary_advances")
        .select("amount")
        .eq("auto_deduct_next_month", True)
        .eq("is_deducted", False)
    )
    return sum(float(r["amount"]) for r in rows) if rows else 0.0


def _client_metrics(client, client_id):
    guard_ids = _client_guard_ids(client, client_id)
    on_duty = 0
    if guard_ids:
        on_duty = _safe_count(
            client.table("guards")
            .select("id", count="exact")
            .eq("assigned_client_id", client_id)
            .eq("duty_status", "On Duty")
        )
    return {
        "assigned_guards": len(guard_ids),
        "guards_on_duty": on_duty,
        "open_complaints": _safe_count(
            client.table("complaints")
            .select("id", count="exact")
            .eq("client_id", client_id)
            .eq("resolution_status", "Unresolved")
        ),
        "guard_ids": guard_ids,
    }


def _recent_attendance(client, guard_ids=None, limit=8):
    query = (
        client.table("attendance")
        .select("attendance_date, status, reason_for_absence, guards(full_name)")
        .order("attendance_date", desc=True)
        .limit(limit)
    )
    if guard_ids is not None:
        if not guard_ids:
            return []
        query = query.in_("guard_id", guard_ids)
    return _safe_data(query)


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


@dashboard_bp.route("/dashboard")
@login_required
def index():
    user = session["user"]
    client = get_session_client()

    if user["role"] in ("Admin", "Ops"):
        metrics = _admin_ops_metrics(client)
        recent_attendance = _recent_attendance(client)
        recent_complaints = _recent_complaints(client)
        recent_advances = _recent_salary_advances(client)
        return render_template(
            "dashboard.html",
            metrics=metrics,
            recent_attendance=recent_attendance,
            recent_complaints=recent_complaints,
            recent_advances=recent_advances,
        )

    # Client role — scoped view, no financial data.
    client_id = user.get("client_id")
    metrics = _client_metrics(client, client_id) if client_id else {
        "assigned_guards": 0, "guards_on_duty": 0, "open_complaints": 0, "guard_ids": []
    }
    recent_attendance = _recent_attendance(client, guard_ids=metrics["guard_ids"])
    recent_complaints = _recent_complaints(client, client_id=client_id)
    return render_template(
        "dashboard.html",
        metrics=metrics,
        recent_attendance=recent_attendance,
        recent_complaints=recent_complaints,
        recent_advances=None,  # Client role never sees salary data
    )
