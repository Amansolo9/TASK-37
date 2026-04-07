"""CMS content service with workflow state machine."""

import re
import json
from datetime import datetime
from app.extensions import db
from app.models.cms import ContentItem, ContentVersion
from app.models.region import Category, Tag
from app.services.audit_service import log_action
from app.services.search_service import index_content_item
import bleach

ALLOWED_TAGS = [
    "p", "br", "strong", "em", "u", "s", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "blockquote", "pre", "code", "a", "img", "table", "thead",
    "tbody", "tr", "th", "td", "hr", "div", "span", "sub", "sup",
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "target"],
    "img": ["src", "alt", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    "*": ["class", "style"],
}

VALID_STATES = {"draft", "in_review", "published", "scheduled", "withdrawn"}
TRANSITIONS = {
    "draft": ["in_review"],
    "in_review": ["draft", "published", "scheduled"],
    "published": ["withdrawn"],
    "scheduled": ["published", "withdrawn"],
    "withdrawn": ["draft"],
}


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


def is_slug_unique(slug, exclude_id=None):
    q = ContentItem.query.filter_by(slug=slug)
    if exclude_id:
        q = q.filter(ContentItem.id != exclude_id)
    return q.first() is None


def sanitize_html(html_content):
    if not html_content:
        return ""
    return bleach.clean(html_content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


def html_to_text(html_content):
    if not html_content:
        return ""
    return bleach.clean(html_content, tags=[], strip=True)


def create_content(title, slug, body_html, summary, author_id, region_id=None,
                   media_type=None, category_ids=None, tag_ids=None, metadata_json=None):
    # Auto-derive slug from title when absent or blank
    if not slug or not slug.strip():
        slug = slugify(title)
    if not slug:
        raise ValueError("Slug cannot be blank and could not be derived from title.")
    if not is_slug_unique(slug):
        raise ValueError(f"Slug '{slug}' already exists.")

    clean_html = sanitize_html(body_html)
    body_text = html_to_text(clean_html)

    item = ContentItem(
        slug=slug,
        workflow_state="draft",
        region_id=region_id,
        media_type=media_type,
        created_by=author_id,
        updated_by=author_id,
    )
    db.session.add(item)
    db.session.flush()

    version = ContentVersion(
        content_item_id=item.id,
        version_number=1,
        title=title,
        summary=summary,
        body_html=clean_html,
        body_text=body_text,
        metadata_json=metadata_json,
        author_id=author_id,
        workflow_state="draft",
    )
    db.session.add(version)
    db.session.flush()

    item.current_version_id = version.id

    if category_ids:
        cats = Category.query.filter(Category.id.in_(category_ids)).all()
        item.categories = cats
    if tag_ids:
        tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()
        item.tags = tags

    db.session.commit()
    try:
        index_content_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to index content item %s: %s", item.id, e)
    log_action(author_id, "content_created", "content_item", item.id)
    return item


def update_content_draft(item_id, title, body_html, summary, editor_id,
                         slug=None, region_id=None, media_type=None,
                         category_ids=None, tag_ids=None, metadata_json=None):
    item = db.session.get(ContentItem, item_id)
    if not item:
        raise ValueError("Content not found.")
    if item.workflow_state not in ("draft", "withdrawn"):
        # Create new version for already-published content
        pass

    if slug and slug != item.slug:
        if not is_slug_unique(slug, exclude_id=item.id):
            raise ValueError(f"Slug '{slug}' already exists.")
        item.slug = slug

    clean_html = sanitize_html(body_html)
    body_text = html_to_text(clean_html)

    current_ver = item.current_version
    new_ver_num = (current_ver.version_number + 1) if current_ver else 1

    version = ContentVersion(
        content_item_id=item.id,
        version_number=new_ver_num,
        title=title,
        summary=summary,
        body_html=clean_html,
        body_text=body_text,
        metadata_json=metadata_json,
        author_id=editor_id,
        workflow_state="draft",
    )
    db.session.add(version)
    db.session.flush()

    item.current_version_id = version.id
    item.region_id = region_id
    item.media_type = media_type
    item.updated_by = editor_id
    item.workflow_state = "draft"

    if category_ids is not None:
        item.categories = Category.query.filter(Category.id.in_(category_ids)).all()
    if tag_ids is not None:
        item.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all()

    db.session.commit()
    try:
        index_content_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to index content item %s: %s", item.id, e)
    log_action(editor_id, "content_updated", "content_item", item.id)
    return item


def submit_for_review(item_id, user_id):
    item = db.session.get(ContentItem, item_id)
    if not item or item.workflow_state != "draft":
        raise ValueError("Only drafts can be submitted for review.")
    item.workflow_state = "in_review"
    version = item.current_version
    if version:
        version.workflow_state = "in_review"
        version.submitted_at = datetime.utcnow()
    db.session.commit()
    log_action(user_id, "content_submitted_review", "content_item", item.id)
    return item


def approve_and_publish(item_id, reviewer_id, review_notes=None):
    item = db.session.get(ContentItem, item_id)
    if not item or item.workflow_state != "in_review":
        raise ValueError("Only items in review can be published.")
    now = datetime.utcnow()
    item.workflow_state = "published"
    item.published_at = now
    item.published_version_id = item.current_version_id
    version = item.current_version
    if version:
        version.workflow_state = "published"
        version.reviewed_by = reviewer_id
        version.reviewed_at = now
        version.approved_at = now
        version.published_at = now
        version.review_notes = review_notes
    db.session.commit()
    try:
        index_content_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to index content item %s: %s", item.id, e)
    log_action(reviewer_id, "content_published", "content_item", item.id)
    _emit_outbox("content.published", "content_item", item.id)
    return item


def reject_to_draft(item_id, reviewer_id, review_notes=None):
    item = db.session.get(ContentItem, item_id)
    if not item or item.workflow_state != "in_review":
        raise ValueError("Only items in review can be rejected.")
    item.workflow_state = "draft"
    version = item.current_version
    if version:
        version.workflow_state = "draft"
        version.reviewed_by = reviewer_id
        version.reviewed_at = datetime.utcnow()
        version.review_notes = review_notes
    db.session.commit()
    log_action(reviewer_id, "content_rejected", "content_item", item.id)
    return item


def schedule_publish(item_id, reviewer_id, scheduled_at, review_notes=None):
    item = db.session.get(ContentItem, item_id)
    if not item or item.workflow_state != "in_review":
        raise ValueError("Only items in review can be scheduled.")
    item.workflow_state = "scheduled"
    item.scheduled_publish_at = scheduled_at
    version = item.current_version
    if version:
        version.workflow_state = "scheduled"
        version.reviewed_by = reviewer_id
        version.reviewed_at = datetime.utcnow()
        version.approved_at = datetime.utcnow()
        version.scheduled_publish_at = scheduled_at
        version.review_notes = review_notes
    db.session.commit()
    log_action(reviewer_id, "content_scheduled", "content_item", item.id,
              {"scheduled_at": scheduled_at.isoformat()})
    return item


def withdraw_content(item_id, user_id):
    item = db.session.get(ContentItem, item_id)
    if not item or item.workflow_state not in ("published", "scheduled"):
        raise ValueError("Only published/scheduled items can be withdrawn.")
    item.workflow_state = "withdrawn"
    item.withdrawn_at = datetime.utcnow()
    version = item.current_version
    if version:
        version.workflow_state = "withdrawn"
        version.withdrawn_at = datetime.utcnow()
    db.session.commit()
    try:
        index_content_item(item)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to index content item %s: %s", item.id, e)
    log_action(user_id, "content_withdrawn", "content_item", item.id)
    return item


def process_scheduled_publishes():
    now = datetime.utcnow()
    items = ContentItem.query.filter(
        ContentItem.workflow_state == "scheduled",
        ContentItem.scheduled_publish_at <= now,
    ).all()
    for item in items:
        item.workflow_state = "published"
        item.published_at = now
        item.published_version_id = item.current_version_id
        version = item.current_version
        if version:
            version.workflow_state = "published"
            version.published_at = now
        try:
            index_content_item(item)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to index content item %s: %s", item.id, e)
        _emit_outbox("content.published", "content_item", item.id)
    if items:
        db.session.commit()
    return len(items)


def update_placement(item_id, is_pinned, is_recommended, is_carousel, carousel_rank=None, user_id=None):
    item = db.session.get(ContentItem, item_id)
    if not item:
        raise ValueError("Content not found.")
    item.is_pinned = is_pinned
    item.is_recommended = is_recommended
    item.is_carousel = is_carousel
    item.carousel_rank = carousel_rank
    db.session.commit()
    if user_id:
        log_action(user_id, "content_placement_updated", "content_item", item.id)
    return item


def get_homepage_content():
    pinned = ContentItem.query.filter_by(workflow_state="published", is_pinned=True).all()
    recommended = ContentItem.query.filter_by(workflow_state="published", is_recommended=True).limit(10).all()
    carousel = ContentItem.query.filter_by(
        workflow_state="published", is_carousel=True
    ).order_by(ContentItem.carousel_rank.asc().nullslast()).limit(5).all()
    return {"pinned": pinned, "recommended": recommended, "carousel": carousel}


def get_review_queue():
    return ContentItem.query.filter_by(workflow_state="in_review").order_by(
        ContentItem.updated_at.desc()
    ).all()


def get_content_list(state=None, region_id=None, category_id=None):
    q = ContentItem.query
    if state:
        q = q.filter(ContentItem.workflow_state == state)
    if region_id:
        q = q.filter(ContentItem.region_id == region_id)
    if category_id:
        q = q.filter(ContentItem.categories.any(Category.id == category_id))
    return q.order_by(ContentItem.updated_at.desc())


def _emit_outbox(topic, aggregate_type, aggregate_id):
    try:
        from app.services.outbox_service import create_event
        create_event(topic, aggregate_type, aggregate_id, {})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to emit outbox event topic=%s aggregate=%s:%s: %s",
            topic, aggregate_type, aggregate_id, e
        )
