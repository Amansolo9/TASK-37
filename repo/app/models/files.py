"""File attachment and download audit models."""

from datetime import datetime
from app.extensions import db


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    owner_type = db.Column(db.String(50), nullable=True, index=True)
    owner_id = db.Column(db.Integer, nullable=True)
    original_filename = db.Column(db.String(300), nullable=False)
    stored_filename = db.Column(db.String(300), nullable=False)
    storage_path = db.Column(db.String(500), nullable=False)
    file_ext = db.Column(db.String(20), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False, index=True)
    duplicate_of_id = db.Column(db.Integer, db.ForeignKey("attachments.id"), nullable=True)
    watermark_on_download = db.Column(db.Boolean, default=False, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)
    purge_after = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    uploader = db.relationship("User", foreign_keys=[uploaded_by])
    duplicate_of = db.relationship("Attachment", remote_side="Attachment.id")


class FileDownloadAudit(db.Model):
    __tablename__ = "file_download_audits"
    id = db.Column(db.Integer, primary_key=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("attachments.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    watermark_applied = db.Column(db.Boolean, default=False, nullable=False)
    downloaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    attachment = db.relationship("Attachment", foreign_keys=[attachment_id])
    user = db.relationship("User", foreign_keys=[user_id])
