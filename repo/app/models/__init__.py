"""Import all models so they are registered with SQLAlchemy."""

from app.models.user import User, Role, RolePermission, AuditLog, Setting, user_roles
from app.models.region import Region, Category, Tag
from app.models.cms import ContentItem, ContentVersion, content_categories, content_tags, content_attachments
from app.models.search import SearchDocument, SearchQuery
from app.models.dispatch import (
    Resource, ResourceAvailability, TimeSlotTemplate,
    ScheduleItem, ScheduleConflict, ScheduleChange,
)
from app.models.catalog import (
    ServiceItem, Order, OrderItem, Payment,
    ReconciliationRun, ReconciliationItem,
)
from app.models.analytics import KpiSnapshot, ReportJob
from app.models.files import Attachment, FileDownloadAudit
from app.models.api import ApiClient, ApiUsageCounter, OutboxEvent, WebhookSubscription

__all__ = [
    "User", "Role", "RolePermission", "AuditLog", "Setting",
    "Region", "Category", "Tag",
    "ContentItem", "ContentVersion",
    "SearchDocument", "SearchQuery",
    "Resource", "ResourceAvailability", "TimeSlotTemplate",
    "ScheduleItem", "ScheduleConflict", "ScheduleChange",
    "ServiceItem", "Order", "OrderItem", "Payment",
    "ReconciliationRun", "ReconciliationItem",
    "KpiSnapshot", "ReportJob",
    "Attachment", "FileDownloadAudit",
    "ApiClient", "ApiUsageCounter", "OutboxEvent", "WebhookSubscription",
]
