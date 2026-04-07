"""Search service using SQLite FTS5."""

import json
from datetime import datetime, timedelta
from app.extensions import db
from app.models.search import SearchDocument, SearchQuery


def init_fts(app):
    """Create FTS5 virtual table if not exists. Call during app init or migration."""
    with app.app_context():
        db.session.execute(db.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "title, body_text, tags_text, metadata_text, "
            "content='search_documents', content_rowid='id')"
        ))
        db.session.commit()


def rebuild_fts_index():
    db.session.execute(db.text("INSERT INTO search_fts(search_fts) VALUES('rebuild')"))
    db.session.commit()


def index_content_item(item):
    """Index or update a content item in search_documents + FTS."""
    version = item.current_version
    if not version:
        return
    tags_text = " ".join(t.name for t in item.tags) if item.tags else ""
    cat_text = " ".join(c.name for c in item.categories) if item.categories else ""
    metadata_text = f"{cat_text} {item.media_type or ''}"

    doc = SearchDocument.query.filter_by(record_type="content", record_id=item.id).first()
    if doc:
        doc.title = version.title
        doc.body_text = version.body_text or ""
        doc.tags_text = tags_text
        doc.metadata_text = metadata_text
        doc.region_id = item.region_id
        doc.media_type = item.media_type
        doc.primary_date = (item.published_at or item.created_at).date() if item.published_at or item.created_at else None
        doc.updated_at = datetime.utcnow()
    else:
        doc = SearchDocument(
            record_type="content",
            record_id=item.id,
            title=version.title,
            body_text=version.body_text or "",
            tags_text=tags_text,
            metadata_text=metadata_text,
            region_id=item.region_id,
            media_type=item.media_type,
            primary_date=(item.published_at or item.created_at).date() if item.published_at or item.created_at else None,
        )
        db.session.add(doc)
    db.session.flush()

    # Update FTS
    try:
        db.session.execute(db.text(
            "INSERT OR REPLACE INTO search_fts(rowid, title, body_text, tags_text, metadata_text) "
            "VALUES(:rowid, :title, :body_text, :tags_text, :metadata_text)"
        ), {"rowid": doc.id, "title": doc.title, "body_text": doc.body_text,
            "tags_text": doc.tags_text, "metadata_text": doc.metadata_text})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("FTS index update failed: %s", e)
    db.session.commit()


def index_schedule_item(schedule_item):
    """Index a schedule item in search_documents."""
    doc = SearchDocument.query.filter_by(record_type="schedule", record_id=schedule_item.id).first()
    title = schedule_item.title
    body_text = schedule_item.notes or ""
    metadata_text = f"{schedule_item.status}"
    if doc:
        doc.title = title
        doc.body_text = body_text
        doc.metadata_text = metadata_text
        doc.region_id = schedule_item.region_id
        doc.primary_date = schedule_item.scheduled_date
        doc.updated_at = datetime.utcnow()
    else:
        doc = SearchDocument(
            record_type="schedule",
            record_id=schedule_item.id,
            title=title,
            body_text=body_text,
            metadata_text=metadata_text,
            region_id=schedule_item.region_id,
            primary_date=schedule_item.scheduled_date,
        )
        db.session.add(doc)
    db.session.flush()
    try:
        db.session.execute(db.text(
            "INSERT OR REPLACE INTO search_fts(rowid, title, body_text, tags_text, metadata_text) "
            "VALUES(:rowid, :title, :body_text, :tags_text, :metadata_text)"
        ), {"rowid": doc.id, "title": doc.title, "body_text": doc.body_text,
            "tags_text": "", "metadata_text": doc.metadata_text})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("FTS index update failed: %s", e)
    db.session.commit()


def search(query_text, user_id=None, record_type=None, region_id=None,
           media_type=None, date_from=None, date_to=None, category_id=None,
           page=1, per_page=50):
    """Full-text search with facets and logging."""
    normalized = query_text.strip().lower()

    # Build FTS query
    try:
        fts_results = db.session.execute(db.text(
            "SELECT rowid, rank FROM search_fts WHERE search_fts MATCH :q ORDER BY rank LIMIT :limit OFFSET :offset"
        ), {"q": normalized, "limit": per_page, "offset": (page - 1) * per_page}).fetchall()
        doc_ids = [r[0] for r in fts_results]
    except Exception:
        doc_ids = []

    if doc_ids:
        q = SearchDocument.query.filter(SearchDocument.id.in_(doc_ids))
    else:
        # Fallback to LIKE search
        q = SearchDocument.query.filter(
            db.or_(
                SearchDocument.title.ilike(f"%{normalized}%"),
                SearchDocument.body_text.ilike(f"%{normalized}%"),
                SearchDocument.tags_text.ilike(f"%{normalized}%"),
            )
        )

    if record_type:
        q = q.filter(SearchDocument.record_type == record_type)
    if region_id:
        q = q.filter(SearchDocument.region_id == region_id)
    if media_type:
        q = q.filter(SearchDocument.media_type == media_type)
    if date_from:
        q = q.filter(SearchDocument.primary_date >= date_from)
    if date_to:
        q = q.filter(SearchDocument.primary_date <= date_to)

    if category_id:
        # Join back to content items to filter by category
        from app.models.cms import ContentItem, content_categories
        matching_content_ids = db.session.query(content_categories.c.content_item_id).filter(
            content_categories.c.category_id == category_id
        ).subquery()
        q = q.filter(
            db.and_(
                SearchDocument.record_type == "content",
                SearchDocument.record_id.in_(db.session.query(matching_content_ids))
            )
        )

    # Apply deterministic ordering and pagination to all paths (including LIKE fallback)
    q = q.order_by(SearchDocument.updated_at.desc(), SearchDocument.id.desc())
    total_count = q.count()
    results = q.offset((page - 1) * per_page).limit(per_page).all()
    result_count = total_count

    # Log search
    sq = SearchQuery(
        user_id=user_id,
        raw_query=query_text,
        normalized_query=normalized,
        filters_json=json.dumps({
            "record_type": record_type, "region_id": region_id,
            "media_type": media_type, "category_id": category_id,
        }),
        result_count=result_count,
        zero_results=result_count == 0,
    )
    db.session.add(sq)
    db.session.commit()

    return results, result_count


def get_trending_terms(days=7, limit=10):
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.session.execute(db.text(
        "SELECT normalized_query, COUNT(*) as cnt FROM search_queries "
        "WHERE created_at >= :since GROUP BY normalized_query ORDER BY cnt DESC LIMIT :limit"
    ), {"since": since, "limit": limit}).fetchall()
    return [(r[0], r[1]) for r in rows]


def get_zero_result_queries(days=30, limit=20):
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.session.execute(db.text(
        "SELECT normalized_query, COUNT(*) as cnt FROM search_queries "
        "WHERE zero_results = 1 AND created_at >= :since "
        "GROUP BY normalized_query ORDER BY cnt DESC LIMIT :limit"
    ), {"since": since, "limit": limit}).fetchall()
    return [(r[0], r[1]) for r in rows]
