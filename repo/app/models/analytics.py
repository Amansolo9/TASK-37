"""Analytics and reporting models."""

from datetime import datetime
from app.extensions import db


class KpiSnapshot(db.Model):
    __tablename__ = "kpi_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    report_scope = db.Column(db.String(100), nullable=False)
    filters_hash = db.Column(db.String(64), nullable=False, index=True)
    filters_json = db.Column(db.Text, nullable=True)
    metrics_json = db.Column(db.Text, nullable=False)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)


class ReportJob(db.Model):
    __tablename__ = "report_jobs"
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(100), nullable=False)
    filters_json = db.Column(db.Text, nullable=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), default="queued", nullable=False, index=True)
    row_count = db.Column(db.Integer, nullable=True)
    result_file_path = db.Column(db.String(500), nullable=True)
    error_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", foreign_keys=[requested_by])
