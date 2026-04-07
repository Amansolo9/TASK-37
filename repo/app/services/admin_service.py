"""Admin service layer for user/role/region management."""

from datetime import datetime
from app.extensions import db
from app.models.user import User, Role, RolePermission
from app.models.region import Region
from app.utils.auth_helpers import hash_password
from app.services.audit_service import log_action


def get_all_users():
    return User.query.order_by(User.username).all()


def get_user(user_id):
    return db.session.get(User, user_id)


def update_user(user, display_name, is_active, role_ids, password=None, actor_id=None):
    user.display_name = display_name
    user.is_active_user = is_active
    user.roles = Role.query.filter(Role.id.in_(role_ids)).all() if role_ids else []
    if password:
        user.password_hash = hash_password(password)
    db.session.commit()
    if actor_id:
        log_action(actor_id, "user_updated", "user", user.id)
    return user


def get_all_roles():
    return Role.query.order_by(Role.name).all()


def get_role(role_id):
    return db.session.get(Role, role_id)


def create_role(name, description, permissions):
    role = Role(name=name, description=description)
    for perm in permissions:
        role.permissions.append(RolePermission(permission=perm))
    db.session.add(role)
    db.session.commit()
    return role


def update_role(role, name, description, permissions, actor_id=None):
    role.name = name
    role.description = description
    RolePermission.query.filter_by(role_id=role.id).delete()
    for perm in permissions:
        role.permissions.append(RolePermission(permission=perm))
    db.session.commit()
    if actor_id:
        log_action(actor_id, "role_updated", "role", role.id)
    return role


def get_all_regions():
    return Region.query.order_by(Region.name).all()


def get_region(region_id):
    return db.session.get(Region, region_id)


def create_region(code, name, sales_tax_rate, active=True):
    region = Region(code=code, name=name, sales_tax_rate=sales_tax_rate, active=active)
    db.session.add(region)
    db.session.commit()
    return region


def update_region(region, code, name, sales_tax_rate, active, actor_id=None):
    region.code = code
    region.name = name
    region.sales_tax_rate = sales_tax_rate
    region.active = active
    db.session.commit()
    if actor_id:
        log_action(actor_id, "region_updated", "region", region.id)
    return region
