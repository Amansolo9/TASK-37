"""User, Role, and permission models."""

from datetime import datetime
from flask_login import UserMixin
from app.extensions import db

user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)


# Capability constants
CAPABILITIES = [
    "admin.manage_users",
    "admin.manage_roles",
    "admin.manage_settings",
    "admin.manage_api_keys",
    "admin.view_audit_logs",
    "content.create",
    "content.edit",
    "content.submit_review",
    "content.review",
    "content.publish",
    "content.schedule",
    "content.withdraw",
    "content.manage_taxonomy",
    "content.manage_homepage_placement",
    "dispatch.manage_resources",
    "dispatch.manage_schedule",
    "dispatch.resolve_conflicts",
    "dispatch.view_change_notices",
    "orders.manage",
    "orders.record_payment",
    "orders.reconcile",
    "analytics.view",
    "analytics.export",
    "analytics.view_financials",
    "files.upload",
    "files.download",
    "files.manage_retention",
    "api.access",
]

role_permissions = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission", db.String(100), primary_key=True),
)


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(255))
    permissions = db.relationship(
        "RolePermission", backref="role", cascade="all, delete-orphan"
    )
    users = db.relationship("User", secondary=user_roles, back_populates="roles")

    def get_permissions(self):
        return {rp.permission for rp in self.permissions}


class RolePermission(db.Model):
    __tablename__ = "role_permissions_detail"
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    permission = db.Column(db.String(100), nullable=False)

    __table_args__ = (db.UniqueConstraint("role_id", "permission"),)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active_user = db.Column(db.Boolean, default=True, nullable=False)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    lockout_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_activity_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    roles = db.relationship("Role", secondary=user_roles, back_populates="users")

    @property
    def is_active(self):
        return self.is_active_user

    def get_permissions(self):
        perms = set()
        for role in self.roles:
            perms.update(role.get_permissions())
        return perms

    def has_permission(self, perm: str) -> bool:
        return perm in self.get_permissions()

    def has_any_permission(self, *perms: str) -> bool:
        user_perms = self.get_permissions()
        return bool(user_perms & set(perms))


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor = db.relationship("User", foreign_keys=[actor_user_id])


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(100), primary_key=True)
    value_json = db.Column(db.Text, nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
