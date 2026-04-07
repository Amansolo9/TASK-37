"""Region and taxonomy models."""

from datetime import datetime
from app.extensions import db


class Region(db.Model):
    __tablename__ = "regions"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    sales_tax_rate = db.Column(db.Numeric(6, 4), default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    children = db.relationship("Category", backref=db.backref("parent", remote_side="Category.id"))


class Tag(db.Model):
    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
