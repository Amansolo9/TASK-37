"""CMS content models with versioning and workflow."""

from datetime import datetime
from app.extensions import db

content_categories = db.Table(
    "content_categories",
    db.Column("content_item_id", db.Integer, db.ForeignKey("content_items.id"), primary_key=True),
    db.Column("category_id", db.Integer, db.ForeignKey("categories.id"), primary_key=True),
)

content_tags = db.Table(
    "content_tags",
    db.Column("content_item_id", db.Integer, db.ForeignKey("content_items.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
)

content_attachments = db.Table(
    "content_attachments",
    db.Column("content_item_id", db.Integer, db.ForeignKey("content_items.id"), primary_key=True),
    db.Column("attachment_id", db.Integer, db.ForeignKey("attachments.id"), primary_key=True),
)


class ContentItem(db.Model):
    __tablename__ = "content_items"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    current_version_id = db.Column(db.Integer, db.ForeignKey("content_versions.id", use_alter=True), nullable=True)
    published_version_id = db.Column(db.Integer, db.ForeignKey("content_versions.id", use_alter=True), nullable=True)
    workflow_state = db.Column(db.String(20), default="draft", nullable=False, index=True)
    region_id = db.Column(db.Integer, db.ForeignKey("regions.id"), nullable=True)
    media_type = db.Column(db.String(50), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    is_recommended = db.Column(db.Boolean, default=False, nullable=False)
    is_carousel = db.Column(db.Boolean, default=False, nullable=False)
    carousel_rank = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)
    scheduled_publish_at = db.Column(db.DateTime, nullable=True)
    withdrawn_at = db.Column(db.DateTime, nullable=True)

    region = db.relationship("Region", foreign_keys=[region_id])
    categories = db.relationship("Category", secondary=content_categories, backref="content_items")
    tags = db.relationship("Tag", secondary=content_tags, backref="content_items")
    attachments = db.relationship("Attachment", secondary=content_attachments, backref="content_items")
    versions = db.relationship(
        "ContentVersion",
        foreign_keys="ContentVersion.content_item_id",
        backref="content_item",
        order_by="ContentVersion.version_number.desc()",
    )
    current_version = db.relationship(
        "ContentVersion", foreign_keys=[current_version_id], post_update=True
    )
    published_version = db.relationship(
        "ContentVersion", foreign_keys=[published_version_id], post_update=True
    )
    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])


class ContentVersion(db.Model):
    __tablename__ = "content_versions"
    id = db.Column(db.Integer, primary_key=True)
    content_item_id = db.Column(db.Integer, db.ForeignKey("content_items.id"), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    body_html = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    review_notes = db.Column(db.Text, nullable=True)
    workflow_state = db.Column(db.String(20), default="draft", nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    scheduled_publish_at = db.Column(db.DateTime, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    withdrawn_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    author = db.relationship("User", foreign_keys=[author_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        db.UniqueConstraint("content_item_id", "version_number"),
    )
