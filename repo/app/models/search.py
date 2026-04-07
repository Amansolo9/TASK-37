"""Search models: document projection and query analytics."""

from datetime import datetime
from app.extensions import db


class SearchDocument(db.Model):
    __tablename__ = "search_documents"
    id = db.Column(db.Integer, primary_key=True)
    record_type = db.Column(db.String(50), nullable=False, index=True)
    record_id = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    body_text = db.Column(db.Text, nullable=True)
    tags_text = db.Column(db.Text, nullable=True)
    metadata_text = db.Column(db.Text, nullable=True)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=True)
    media_type = db.Column(db.String(50), nullable=True)
    primary_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("record_type", "record_id"),)


class SearchQuery(db.Model):
    __tablename__ = "search_queries"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    raw_query = db.Column(db.String(500), nullable=False)
    normalized_query = db.Column(db.String(500), nullable=False, index=True)
    filters_json = db.Column(db.Text, nullable=True)
    result_count = db.Column(db.Integer, default=0, nullable=False)
    zero_results = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
