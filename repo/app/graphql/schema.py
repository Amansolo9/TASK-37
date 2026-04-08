"""Minimal GraphQL schema using graphql-core."""

from graphql import (
    GraphQLSchema, GraphQLObjectType, GraphQLField, GraphQLString,
    GraphQLInt, GraphQLBoolean, GraphQLList, GraphQLArgument,
    GraphQLNonNull, GraphQLFloat,
)


ContentType = GraphQLObjectType("Content", lambda: {
    "id": GraphQLField(GraphQLInt),
    "slug": GraphQLField(GraphQLString),
    "title": GraphQLField(GraphQLString),
    "summary": GraphQLField(GraphQLString),
    "state": GraphQLField(GraphQLString),
    "media_type": GraphQLField(GraphQLString),
    "region_id": GraphQLField(GraphQLInt),
    "is_pinned": GraphQLField(GraphQLBoolean),
    "is_recommended": GraphQLField(GraphQLBoolean),
    "created_at": GraphQLField(GraphQLString),
    "published_at": GraphQLField(GraphQLString),
})

SearchResultType = GraphQLObjectType("SearchResult", lambda: {
    "id": GraphQLField(GraphQLInt),
    "record_type": GraphQLField(GraphQLString),
    "title": GraphQLField(GraphQLString),
    "body_text": GraphQLField(GraphQLString),
    "region_id": GraphQLField(GraphQLInt),
    "media_type": GraphQLField(GraphQLString),
})

ScheduleType = GraphQLObjectType("Schedule", lambda: {
    "id": GraphQLField(GraphQLInt),
    "title": GraphQLField(GraphQLString),
    "status": GraphQLField(GraphQLString),
    "date": GraphQLField(GraphQLString),
    "start_time": GraphQLField(GraphQLString),
    "end_time": GraphQLField(GraphQLString),
    "classroom_id": GraphQLField(GraphQLInt),
    "instructor_id": GraphQLField(GraphQLInt),
    "region_id": GraphQLField(GraphQLInt),
})

OrderType = GraphQLObjectType("Order", lambda: {
    "id": GraphQLField(GraphQLInt),
    "order_number": GraphQLField(GraphQLString),
    "customer_name": GraphQLField(GraphQLString),
    "state": GraphQLField(GraphQLString),
    "total": GraphQLField(GraphQLString),
    "region_id": GraphQLField(GraphQLInt),
    "has_device_identifier": GraphQLField(GraphQLBoolean),
    "has_credit_history": GraphQLField(GraphQLBoolean),
    "created_at": GraphQLField(GraphQLString),
})

ReportJobType = GraphQLObjectType("ReportJob", lambda: {
    "id": GraphQLField(GraphQLInt),
    "report_type": GraphQLField(GraphQLString),
    "status": GraphQLField(GraphQLString),
    "row_count": GraphQLField(GraphQLInt),
    "error": GraphQLField(GraphQLString),
})


def _resolve_content(root, info, id=None, slug=None):
    from app.models.cms import ContentItem
    from app.extensions import db
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "content.read" not in scopes:
        raise Exception("Scope 'content.read' required")
    if id:
        item = db.session.get(ContentItem, id)
    elif slug:
        item = ContentItem.query.filter_by(slug=slug).first()
    else:
        return None
    if not item:
        return None
    # Enforce region isolation on detail lookup
    actor_id = ctx.get("actor_id")
    if actor_id:
        from app.services.access_policy import check_region_access
        from app.models.user import User
        actor = db.session.get(User, actor_id)
        if actor and not check_region_access(item, actor):
            raise Exception("Access denied: content is outside your region scope")
    v = item.current_version
    return {
        "id": item.id, "slug": item.slug,
        "title": v.title if v else "", "summary": v.summary if v else "",
        "state": item.workflow_state, "media_type": item.media_type,
        "region_id": item.region_id, "is_pinned": item.is_pinned,
        "is_recommended": item.is_recommended,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }


def _resolve_contents(root, info, state=None, region_id=None):
    from app.services import cms_service
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "content.read" not in scopes:
        raise Exception("Scope 'content.read' required")
    q = cms_service.get_content_list(state=state, region_id=region_id)
    actor_id = ctx.get("actor_id")
    if actor_id:
        from app.services.access_policy import apply_region_filter, get_actor_region_ids
        from app.models.user import User
        from app.extensions import db
        actor = db.session.get(User, actor_id)
        if actor:
            from app.models.cms import ContentItem
            q = apply_region_filter(q, ContentItem, actor)
    items = q.limit(50).all()
    result = []
    for item in items:
        v = item.current_version
        result.append({
            "id": item.id, "slug": item.slug,
            "title": v.title if v else "", "summary": v.summary if v else "",
            "state": item.workflow_state, "media_type": item.media_type,
            "region_id": item.region_id,
            "is_pinned": item.is_pinned, "is_recommended": item.is_recommended,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        })
    return result


def _resolve_search(root, info, query, record_type=None):
    from app.services import search_service
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "search.read" not in scopes:
        raise Exception("Scope 'search.read' required")
    results, count = search_service.search(query, record_type=record_type)
    actor_id = ctx.get("actor_id")
    if actor_id:
        from app.services.access_policy import get_actor_region_ids
        from app.models.user import User
        from app.extensions import db
        actor = db.session.get(User, actor_id)
        if actor:
            region_ids = get_actor_region_ids(actor)
            if region_ids is not None:
                results = [r for r in results if r.region_id is None or r.region_id in region_ids]
                count = len(results)
    return [{
        "id": r.id, "record_type": r.record_type, "title": r.title,
        "body_text": (r.body_text or "")[:200], "region_id": r.region_id,
        "media_type": r.media_type,
    } for r in results]


def _resolve_schedules(root, info, status=None, region_id=None):
    from app.services import dispatch_service
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "dispatch.read" not in scopes:
        raise Exception("Scope 'dispatch.read' required")
    q = dispatch_service.get_schedule_items(status=status, region_id=region_id)
    actor_id = ctx.get("actor_id")
    if actor_id:
        from app.services.access_policy import apply_region_filter
        from app.models.user import User
        from app.extensions import db
        from app.models.dispatch import ScheduleItem
        actor = db.session.get(User, actor_id)
        if actor:
            q = apply_region_filter(q, ScheduleItem, actor)
    items = q.limit(50).all()
    return [{
        "id": i.id, "title": i.title, "status": i.status,
        "date": str(i.scheduled_date), "start_time": str(i.start_time),
        "end_time": str(i.end_time), "classroom_id": i.classroom_id,
        "instructor_id": i.instructor_id, "region_id": i.region_id,
    } for i in items]


def _resolve_orders(root, info, state=None, region_id=None):
    from app.services import order_service
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "orders.read" not in scopes:
        raise Exception("Scope 'orders.read' required")
    q = order_service.get_order_list(state=state, region_id=region_id)
    actor_id = ctx.get("actor_id")
    if actor_id:
        from app.services.access_policy import apply_region_filter
        from app.models.user import User
        from app.extensions import db
        from app.models.catalog import Order
        actor = db.session.get(User, actor_id)
        if actor:
            q = apply_region_filter(q, Order, actor)
    items = q.limit(50).all()
    return [{
        "id": o.id, "order_number": o.order_number,
        "customer_name": o.customer_name, "state": o.state,
        "total": str(o.total_amount), "region_id": o.region_id,
        "has_device_identifier": o.encrypted_device_identifier is not None,
        "has_credit_history": o.encrypted_credit_history is not None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    } for o in items]


def _resolve_report_job(root, info, id=None):
    from app.services import analytics_service
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "analytics.read" not in scopes:
        raise Exception("Scope 'analytics.read' required")
    if not id:
        return None
    job = analytics_service.get_report_job(id)
    if not job:
        return None
    if job.requested_by != ctx.get("actor_id") and "analytics.view" not in scopes:
        raise Exception("Access denied")
    return {
        "id": job.id, "report_type": job.report_type, "status": job.status,
        "row_count": job.row_count, "error": job.error_text,
    }


def _resolve_create_report(root, info, report_type, filters=None):
    import json
    from app.services import analytics_service
    ctx = info.context or {}
    actor_id = ctx.get("actor_id")
    scopes = ctx.get("scopes", set())
    if "analytics.export" not in scopes:
        raise Exception("Scope 'analytics.export' required")
    if not actor_id:
        raise Exception("Authentication required")
    f = json.loads(filters) if filters else {}
    job = analytics_service.create_report_job(report_type, f, user_id=actor_id)
    return {
        "id": job.id, "report_type": job.report_type, "status": job.status,
        "row_count": job.row_count, "error": job.error_text,
    }


def _resolve_ack_event(root, info, id=None, consumer_name=None):
    from app.services import outbox_service
    ctx = info.context or {}
    scopes = ctx.get("scopes", set())
    if "outbox.write" not in scopes:
        raise Exception("Scope 'outbox.write' required")
    if not consumer_name:
        raise Exception("consumer_name is required for acknowledgment")
    try:
        outbox_service.acknowledge_event(id, consumer_name=consumer_name)
        return True
    except ValueError as e:
        raise Exception(str(e))


QueryType = GraphQLObjectType("Query", {
    "content": GraphQLField(ContentType, args={
        "id": GraphQLArgument(GraphQLInt),
        "slug": GraphQLArgument(GraphQLString),
    }, resolve=_resolve_content),
    "contents": GraphQLField(GraphQLList(ContentType), args={
        "state": GraphQLArgument(GraphQLString),
        "region_id": GraphQLArgument(GraphQLInt),
    }, resolve=_resolve_contents),
    "search": GraphQLField(GraphQLList(SearchResultType), args={
        "query": GraphQLArgument(GraphQLNonNull(GraphQLString)),
        "record_type": GraphQLArgument(GraphQLString),
    }, resolve=_resolve_search),
    "schedules": GraphQLField(GraphQLList(ScheduleType), args={
        "status": GraphQLArgument(GraphQLString),
        "region_id": GraphQLArgument(GraphQLInt),
    }, resolve=_resolve_schedules),
    "orders": GraphQLField(GraphQLList(OrderType), args={
        "state": GraphQLArgument(GraphQLString),
        "region_id": GraphQLArgument(GraphQLInt),
    }, resolve=_resolve_orders),
    "reportJob": GraphQLField(ReportJobType, args={
        "id": GraphQLArgument(GraphQLInt),
    }, resolve=_resolve_report_job),
})

MutationType = GraphQLObjectType("Mutation", {
    "createReportJob": GraphQLField(ReportJobType, args={
        "report_type": GraphQLArgument(GraphQLNonNull(GraphQLString)),
        "filters": GraphQLArgument(GraphQLString),
    }, resolve=_resolve_create_report),
    "acknowledgeOutboxEvent": GraphQLField(GraphQLBoolean, args={
        "id": GraphQLArgument(GraphQLNonNull(GraphQLInt)),
        "consumer_name": GraphQLArgument(GraphQLNonNull(GraphQLString)),
    }, resolve=_resolve_ack_event),
})

schema = GraphQLSchema(query=QueryType, mutation=MutationType)


def execute_query(query_string, variables=None, context=None):
    from graphql import graphql_sync
    result = graphql_sync(schema, query_string, variable_values=variables, context_value=context)
    response = {}
    if result.data:
        response["data"] = result.data
    if result.errors:
        response["errors"] = [{"message": str(e)} for e in result.errors]
    return response
