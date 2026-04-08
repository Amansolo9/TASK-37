"""Centralized access policy helpers for object-level authorization and region isolation.

Region-based isolation:
  Users are associated with regions through their roles/permissions. Every user
  has an accessible set of region_ids derived from the objects they own/created.
  For the admin role, all regions are accessible. For non-admin users, access is
  scoped to regions of objects they created or are explicitly associated with.

  For this single-deployment product, region_id serves as the isolation boundary.
  Each entity with a region_id is filtered by the actor's accessible regions in
  list/search queries. Entities without a region_id (e.g. unscoped attachments)
  fall back to ownership/uploader checks.

Attachment access policy:
  - Uploader always has access
  - Admin (admin.manage_users) has access to all
  - For owned attachments (owner_type/owner_id set): access granted if actor can
    access the owning entity
  - For unowned attachments: access only for uploader or admin
"""

import logging
from flask_login import current_user
from app.extensions import db

logger = logging.getLogger(__name__)


def get_actor_region_ids(user):
    """Return the set of region_ids accessible to a user.

    Admins get all regions. Other users get regions from entities they created.
    Returns None for admins (meaning 'all regions').
    """
    if user.has_permission("admin.manage_users"):
        return None  # admin sees all

    from app.models.catalog import Order
    from app.models.cms import ContentItem
    from app.models.dispatch import ScheduleItem

    region_ids = set()

    # Regions from orders the user created
    order_regions = db.session.query(Order.region_id).filter(
        Order.created_by == user.id, Order.region_id.isnot(None)
    ).distinct().all()
    region_ids.update(r[0] for r in order_regions)

    # Regions from content the user created
    content_regions = db.session.query(ContentItem.region_id).filter(
        ContentItem.created_by == user.id, ContentItem.region_id.isnot(None)
    ).distinct().all()
    region_ids.update(r[0] for r in content_regions)

    # Regions from schedule items the user created
    sched_regions = db.session.query(ScheduleItem.region_id).filter(
        ScheduleItem.created_by == user.id, ScheduleItem.region_id.isnot(None)
    ).distinct().all()
    region_ids.update(r[0] for r in sched_regions)

    return region_ids if region_ids else {-1}  # empty set -> deny all


def validate_region_for_create(user, region_id):
    """Check if a user is allowed to create/operate on an entity in the given region.

    Returns True if the user has access to the region, False otherwise.
    Admins can operate on any region.
    """
    if not region_id:
        return True
    region_ids = get_actor_region_ids(user)
    if region_ids is None:
        return True  # admin
    return region_id in region_ids


def apply_region_filter(query, model, user):
    """Apply region-based isolation filter to a query.

    model must have a region_id column. Returns filtered query.
    """
    region_ids = get_actor_region_ids(user)
    if region_ids is None:
        return query  # admin
    return query.filter(model.region_id.in_(region_ids))


def check_region_access(obj, user):
    """Check if user can access a specific object based on its region_id.

    Returns True if allowed. Objects without a region_id are accessible to all.
    """
    region_id = getattr(obj, "region_id", None)
    if region_id is None:
        return True
    region_ids = get_actor_region_ids(user)
    if region_ids is None:
        return True  # admin
    return region_id in region_ids


def can_access_attachment(attachment, user):
    """Determine if a user can access a specific attachment.

    Returns True if access is allowed, False otherwise.
    """
    if not attachment or attachment.deleted_at:
        return False

    # Admin access
    if user.has_permission("admin.manage_users"):
        return True

    # Uploader always has access
    if attachment.uploaded_by == user.id:
        return True

    # Check owner relationship
    if attachment.owner_type and attachment.owner_id:
        return _check_owner_access(attachment, user)

    # Unowned attachment: only uploader or admin (already checked above)
    return False


def _check_owner_access(attachment, user):
    """Check if user can access the entity that owns this attachment."""
    if attachment.owner_type == "content_item":
        from app.models.cms import ContentItem
        item = db.session.get(ContentItem, attachment.owner_id)
        if not item:
            return False
        # Content creators/editors can access content attachments
        if item.created_by == user.id:
            return True
        if user.has_any_permission("content.create", "content.edit", "content.review", "content.publish"):
            # Check region isolation
            region_ids = get_actor_region_ids(user)
            if region_ids is None or (item.region_id and item.region_id in region_ids):
                return True
        return False

    elif attachment.owner_type == "order":
        from app.models.catalog import Order
        order = db.session.get(Order, attachment.owner_id)
        if not order:
            return False
        if order.created_by == user.id:
            return True
        if user.has_permission("orders.manage"):
            region_ids = get_actor_region_ids(user)
            if region_ids is None or order.region_id in region_ids:
                return True
        return False

    # Unknown owner_type: deny by default
    logger.warning("Unknown attachment owner_type=%s for attachment %s", attachment.owner_type, attachment.id)
    return False
