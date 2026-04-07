"""Analytics and KPI service with caching and report generation."""

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from flask import current_app
from app.extensions import db, cache
from app.models.catalog import Order, OrderItem
from app.models.dispatch import ScheduleItem, ScheduleConflict
from app.models.analytics import KpiSnapshot, ReportJob
from app.utils.date_helpers import parse_date_us


def _parse_filter_date(val):
    """Parse a date filter value, accepting ISO 8601 strings or date objects."""
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val  # already a date/datetime
    if isinstance(val, str):
        # Try ISO format first
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        # Try MM/DD/YYYY
        parsed = parse_date_us(val)
        if parsed:
            return datetime.combine(parsed, datetime.min.time())
    return None


def _filters_hash(report_scope, filters):
    raw = json.dumps({"scope": report_scope, **filters}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _mask_financial_fields(metrics, user_permissions):
    """Mask sensitive financial fields if user lacks analytics.view_financials."""
    if user_permissions and "analytics.view_financials" not in user_permissions:
        metrics = dict(metrics)
        for key in list(metrics.keys()):
            if "revenue" in key or "cost" in key or "amount" in key or "margin" in key:
                metrics[key] = "[restricted]"
    return metrics


def get_kpis(report_scope, filters, user_permissions=None):
    fhash = _filters_hash(report_scope, filters)
    cache_key = f"kpi:{fhash}"
    cached = cache.get(cache_key)
    if cached:
        return _mask_financial_fields(cached, user_permissions)

    metrics = {}
    if report_scope in ("orders", "overview"):
        metrics.update(_order_kpis(filters))
    if report_scope in ("schedule", "overview"):
        metrics.update(_schedule_kpis(filters))

    # Cache unmasked metrics
    cache.set(cache_key, metrics, timeout=current_app.config.get("AGGREGATE_CACHE_TTL_SECONDS", 600))

    # Apply per-request masking
    metrics = _mask_financial_fields(metrics, user_permissions)

    snap = KpiSnapshot(
        report_scope=report_scope, filters_hash=fhash,
        filters_json=json.dumps(filters), metrics_json=json.dumps(metrics, default=str),
        generated_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(seconds=600),
    )
    db.session.add(snap)
    db.session.commit()
    return metrics


def _order_kpis(filters):
    q = Order.query
    if filters.get("region_id"):
        q = q.filter(Order.region_id == filters["region_id"])
    date_from = _parse_filter_date(filters.get("date_from"))
    if date_from:
        q = q.filter(Order.created_at >= date_from)
    date_to = _parse_filter_date(filters.get("date_to"))
    if date_to:
        q = q.filter(Order.created_at <= date_to)
    if filters.get("state"):
        q = q.filter(Order.state == filters["state"])

    orders = q.all()
    total_count = len(orders)
    completed = [o for o in orders if o.completed_at]
    canceled = [o for o in orders if o.state == "canceled"]
    refunded = [o for o in orders if o.state == "refunded"]

    turnaround_days = []
    for o in completed:
        if o.completed_at and o.created_at:
            td = (o.completed_at - o.created_at).total_seconds() / 86400
            turnaround_days.append(td)

    on_time = sum(1 for o in completed
                  if o.scheduled_date and o.completed_at
                  and o.completed_at.date() <= o.scheduled_date)

    exception_count = len(canceled) + len(refunded)
    total_revenue = sum(float(o.total_amount) for o in orders if o.state in ("paid", "completed"))

    # Cost calculation from service item cost_amount
    total_cost = Decimal("0")
    for o in orders:
        if o.state in ("paid", "completed"):
            for oi in o.items:
                if oi.service_item and oi.service_item.cost_amount:
                    total_cost += oi.quantity * oi.service_item.cost_amount

    return {
        "order_count": total_count,
        "completed_count": len(completed),
        "avg_turnaround_days": round(sum(turnaround_days) / len(turnaround_days), 1) if turnaround_days else 0,
        "on_time_rate": round(on_time / len(completed) * 100, 1) if completed else 0,
        "exception_rate": round(exception_count / total_count * 100, 1) if total_count else 0,
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(float(total_cost), 2),
        "net_margin": round(total_revenue - float(total_cost), 2),
    }


def _schedule_kpis(filters):
    q = ScheduleItem.query
    if filters.get("region_id"):
        q = q.filter(ScheduleItem.region_id == filters["region_id"])
    date_from = _parse_filter_date(filters.get("date_from"))
    if date_from:
        q = q.filter(ScheduleItem.scheduled_date >= date_from.date() if hasattr(date_from, 'date') else date_from)
    date_to = _parse_filter_date(filters.get("date_to"))
    if date_to:
        q = q.filter(ScheduleItem.scheduled_date <= date_to.date() if hasattr(date_to, 'date') else date_to)

    items = q.all()
    total = len(items)
    completed = sum(1 for i in items if i.status == "completed")
    conflict = sum(1 for i in items if i.status == "conflict")

    return {
        "schedule_total": total,
        "schedule_completed": completed,
        "schedule_conflict_count": conflict,
        "schedule_completion_rate": round(completed / total * 100, 1) if total else 0,
    }


# Estimated rows-per-second processing rate for report generation.
# Used to decide sync vs async: if expected_seconds > 5, run async.
_ROWS_PER_SECOND = 100


def _build_order_query(filters):
    """Build a filtered Order query. Shared by estimation and report generation."""
    q = Order.query
    if filters.get("region_id"):
        q = q.filter(Order.region_id == filters["region_id"])
    if filters.get("state"):
        q = q.filter(Order.state == filters["state"])
    date_from = _parse_filter_date(filters.get("date_from"))
    if date_from:
        q = q.filter(Order.created_at >= date_from)
    date_to = _parse_filter_date(filters.get("date_to"))
    if date_to:
        q = q.filter(Order.created_at <= date_to)
    return q


def _build_schedule_query(filters):
    """Build a filtered ScheduleItem query. Shared by estimation and report generation.

    Accepts 'status' or 'state' filter key — the browser form submits 'state'
    (shared field for both order and schedule reports) while the ScheduleItem
    column is named 'status'.  Normalize here so all callers work correctly.
    """
    q = ScheduleItem.query
    if filters.get("region_id"):
        q = q.filter(ScheduleItem.region_id == filters["region_id"])
    status_val = filters.get("status") or filters.get("state")
    if status_val:
        q = q.filter(ScheduleItem.status == status_val)
    date_from = _parse_filter_date(filters.get("date_from"))
    if date_from:
        q = q.filter(ScheduleItem.scheduled_date >= (date_from.date() if hasattr(date_from, 'date') else date_from))
    date_to = _parse_filter_date(filters.get("date_to"))
    if date_to:
        q = q.filter(ScheduleItem.scheduled_date <= (date_to.date() if hasattr(date_to, 'date') else date_to))
    return q


def estimate_expected_seconds(report_type, filters):
    """Estimate expected report generation time in seconds.

    Returns estimated seconds based on filtered row count and processing rate.
    Reports expected to take > 5 seconds are generated asynchronously.
    Uses the same filter logic as report generation for accurate estimation.
    """
    if report_type == "orders":
        row_count = _build_order_query(filters).count()
    elif report_type == "schedule":
        row_count = _build_schedule_query(filters).count()
    else:
        row_count = 100
    return row_count / _ROWS_PER_SECOND


def create_report_job(report_type, filters, user_id):
    expected_seconds = estimate_expected_seconds(report_type, filters)
    job = ReportJob(
        report_type=report_type,
        filters_json=json.dumps(filters, default=str),
        requested_by=user_id,
        status="queued",
    )
    db.session.add(job)
    db.session.commit()

    # Sync if expected runtime <= 5 seconds, async otherwise
    if expected_seconds <= 5.0:
        process_report_job(job.id)
    return job


def process_report_job(job_id):
    job = db.session.get(ReportJob, job_id)
    if not job or job.status not in ("queued",):
        return
    job.status = "running"
    job.started_at = datetime.utcnow()
    db.session.commit()

    try:
        filters = json.loads(job.filters_json) if job.filters_json else {}
        rows, headers = _generate_report_data(job.report_type, filters)
        job.row_count = len(rows)

        report_dir = Path(current_app.config["REPORT_OUTPUT_ROOT"])
        report_dir.mkdir(parents=True, exist_ok=True)
        filename = f"report_{job.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
        filepath = report_dir / filename

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        job.result_file_path = str(filepath)
        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.expires_at = datetime.utcnow() + timedelta(days=7)
    except Exception as e:
        job.status = "failed"
        job.error_text = str(e)
        job.finished_at = datetime.utcnow()

    db.session.commit()


def _generate_report_data(report_type, filters):
    if report_type == "orders":
        orders = _build_order_query(filters).order_by(Order.created_at.desc()).all()
        headers = ["Order #", "Customer", "Region", "State", "Subtotal", "Tax", "Total", "Paid", "Created"]
        rows = []
        for o in orders:
            rows.append([
                o.order_number, o.customer_name,
                o.region.name if o.region else "", o.state,
                str(o.subtotal_amount), str(o.tax_amount), str(o.total_amount),
                str(o.paid_amount), o.created_at.isoformat() if o.created_at else "",
            ])
        return rows, headers
    elif report_type == "schedule":
        items = _build_schedule_query(filters).order_by(ScheduleItem.scheduled_date).all()
        headers = ["Title", "Date", "Start", "End", "Status", "Region"]
        rows = []
        for i in items:
            rows.append([
                i.title, str(i.scheduled_date), str(i.start_time),
                str(i.end_time), i.status,
                i.region.name if i.region else "",
            ])
        return rows, headers
    return [], []


def get_report_job(job_id):
    return db.session.get(ReportJob, job_id)
