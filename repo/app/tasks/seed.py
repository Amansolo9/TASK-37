"""Seed command to populate demo data."""

import click
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from flask.cli import with_appcontext
from app.extensions import db
from app.models.user import User, Role, RolePermission
from app.models.region import Region, Category, Tag
from app.models.cms import ContentItem, ContentVersion
from app.models.dispatch import Resource, TimeSlotTemplate, ScheduleItem
from app.models.catalog import ServiceItem, Order, OrderItem, Payment
from app.models.analytics import ReportJob
from app.models.search import SearchQuery
from app.utils.auth_helpers import hash_password
from app.services.search_service import init_fts


ROLE_DEFINITIONS = {
    "admin": [
        "admin.manage_users", "admin.manage_roles", "admin.manage_settings",
        "admin.manage_api_keys", "admin.view_audit_logs",
        "content.create", "content.edit", "content.submit_review", "content.review",
        "content.publish", "content.schedule", "content.withdraw",
        "content.manage_taxonomy", "content.manage_homepage_placement",
        "dispatch.manage_resources", "dispatch.manage_schedule",
        "dispatch.resolve_conflicts", "dispatch.view_change_notices",
        "orders.manage", "orders.record_payment", "orders.reconcile",
        "analytics.view", "analytics.export", "analytics.view_financials",
        "files.upload", "files.download", "files.manage_retention",
        "api.access",
    ],
    "editor": [
        "content.create", "content.edit", "content.submit_review",
        "content.manage_taxonomy", "files.upload", "files.download",
    ],
    "reviewer": [
        "content.review", "content.publish", "content.schedule", "content.withdraw",
        "content.manage_homepage_placement", "content.manage_taxonomy",
        "files.upload", "files.download",
    ],
    "dispatcher": [
        "dispatch.manage_resources", "dispatch.manage_schedule",
        "dispatch.resolve_conflicts", "dispatch.view_change_notices",
        "files.upload", "files.download",
    ],
    "analyst": [
        "analytics.view", "analytics.export", "analytics.view_financials",
        "files.download",
    ],
}


@click.command("seed")
@with_appcontext
def seed_command():
    """Seed the database with demo data."""
    click.echo("Seeding database...")

    # Init FTS
    from flask import current_app
    init_fts(current_app)

    # Roles
    roles = {}
    for role_name, perms in ROLE_DEFINITIONS.items():
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            role = Role(name=role_name, description=f"{role_name.title()} role")
            db.session.add(role)
            db.session.flush()
        RolePermission.query.filter_by(role_id=role.id).delete()
        for perm in perms:
            db.session.add(RolePermission(role_id=role.id, permission=perm))
        roles[role_name] = role
    db.session.commit()
    click.echo("  Roles created")

    # Users
    users = {}
    user_defs = [
        ("admin", "Admin User", "admin123", ["admin"]),
        ("editor", "Editor User", "editor123", ["editor"]),
        ("reviewer", "Reviewer User", "reviewer123", ["reviewer"]),
        ("dispatcher", "Dispatcher User", "dispatch123", ["dispatcher"]),
        ("analyst", "Analyst User", "analyst123", ["analyst"]),
    ]
    for uname, dname, pwd, rnames in user_defs:
        u = User.query.filter_by(username=uname).first()
        if not u:
            u = User(
                username=uname, display_name=dname,
                password_hash=hash_password(pwd),
                is_active_user=True, last_activity_at=datetime.utcnow(),
            )
            db.session.add(u)
            db.session.flush()
        u.roles = [roles[r] for r in rnames]
        users[uname] = u
    db.session.commit()
    click.echo("  Users created")

    # Regions (defined early so user-region assignments can reference them)
    region_defs = [
        ("NE", "Northeast", Decimal("0.0825")),
        ("SE", "Southeast", Decimal("0.0700")),
        ("MW", "Midwest", Decimal("0.0600")),
        ("SW", "Southwest", Decimal("0.0500")),
        ("NW", "Northwest", Decimal("0.0000")),
    ]
    regions = {}
    for code, name, tax in region_defs:
        r = Region.query.filter_by(code=code).first()
        if not r:
            r = Region(code=code, name=name, sales_tax_rate=tax, active=True)
            db.session.add(r)
        regions[code] = r
    db.session.commit()
    click.echo("  Regions created")

    # Assign regions to users
    for user in users.values():
        if user.username == "admin":
            user.assigned_regions = list(regions.values())
        else:
            # Non-admin users get NE and SE regions by default
            user.assigned_regions = [regions["NE"], regions["SE"]]
    db.session.commit()
    click.echo("  User region assignments created")

    # Categories
    cat_defs = ["Recycling", "Composting", "Education", "Community Events", "Policy"]
    categories = {}
    for cname in cat_defs:
        slug = cname.lower().replace(" ", "-")
        c = Category.query.filter_by(slug=slug).first()
        if not c:
            c = Category(name=cname, slug=slug, active=True)
            db.session.add(c)
        categories[cname] = c
    db.session.commit()

    # Tags
    tag_defs = ["sustainability", "green", "waste-reduction", "workshops", "municipal"]
    tags = {}
    for tname in tag_defs:
        slug = tname.lower().replace(" ", "-")
        t = Tag.query.filter_by(slug=slug).first()
        if not t:
            t = Tag(name=tname, slug=slug, active=True)
            db.session.add(t)
        tags[tname] = t
    db.session.commit()
    click.echo("  Taxonomy created")

    # Content items
    content_defs = [
        ("recycling-guide-2024", "Complete Recycling Guide 2024", "draft",
         "<p>A comprehensive guide to recycling in your community.</p>", "article"),
        ("composting-101", "Composting 101: Getting Started", "in_review",
         "<p>Learn the basics of composting at home.</p>", "guide"),
        ("earth-day-event", "Earth Day Community Cleanup 2024", "published",
         "<p>Join us for our annual Earth Day cleanup event.</p>", "event"),
        ("waste-reduction-tips", "Top 10 Waste Reduction Tips", "published",
         "<p>Simple tips to reduce waste in your daily life.</p>", "article"),
        ("green-workshops-schedule", "Green Workshops Spring Schedule", "scheduled",
         "<p>Upcoming workshops on sustainability topics.</p>", "news"),
    ]
    for slug, title, state, body, mtype in content_defs:
        if ContentItem.query.filter_by(slug=slug).first():
            continue
        item = ContentItem(
            slug=slug, workflow_state=state, region_id=regions["NE"].id,
            media_type=mtype, created_by=users["editor"].id, updated_by=users["editor"].id,
            is_pinned=(state == "published" and slug == "earth-day-event"),
            is_recommended=(state == "published"),
        )
        if state == "published":
            item.published_at = datetime.utcnow() - timedelta(days=5)
        if state == "scheduled":
            item.scheduled_publish_at = datetime.utcnow() + timedelta(hours=24)
        db.session.add(item)
        db.session.flush()
        v = ContentVersion(
            content_item_id=item.id, version_number=1, title=title,
            summary=f"Summary: {title}", body_html=body,
            body_text=body.replace("<p>", "").replace("</p>", ""),
            author_id=users["editor"].id, workflow_state=state,
        )
        if state in ("published", "scheduled"):
            v.reviewed_by = users["reviewer"].id
            v.approved_at = datetime.utcnow() - timedelta(days=3)
        if state == "in_review":
            v.submitted_at = datetime.utcnow() - timedelta(days=1)
        db.session.add(v)
        db.session.flush()
        item.current_version_id = v.id
        if state == "published":
            item.published_version_id = v.id
        item.categories.append(categories["Recycling"])
        item.tags.append(tags["sustainability"])
    db.session.commit()
    click.echo("  Content created")

    # Resources
    resource_defs = [
        ("classroom", "Room A", "ROOM-A", "NE"),
        ("classroom", "Room B", "ROOM-B", "NE"),
        ("classroom", "Room C", "ROOM-C", "SE"),
        ("instructor", "Jane Smith", "INS-001", "NE"),
        ("instructor", "Bob Jones", "INS-002", "NE"),
        ("instructor", "Alice Chen", "INS-003", "SE"),
    ]
    resources = {}
    for rtype, name, code, reg in resource_defs:
        r = Resource.query.filter_by(code=code).first()
        if not r:
            r = Resource(resource_type=rtype, name=name, code=code,
                        region_id=regions[reg].id, active=True)
            db.session.add(r)
        resources[code] = r
    db.session.commit()

    # Time slots
    slot_defs = [
        ("Morning", time(9, 0), time(12, 0)),
        ("Afternoon", time(13, 0), time(17, 0)),
        ("Evening", time(18, 0), time(21, 0)),
    ]
    for sname, st, et in slot_defs:
        if not TimeSlotTemplate.query.filter_by(name=sname).first():
            db.session.add(TimeSlotTemplate(name=sname, start_time=st, end_time=et, active=True))
    db.session.commit()
    click.echo("  Resources and time slots created")

    # Schedule items (including conflict)
    today = date.today()
    sched_defs = [
        ("Recycling Workshop", today + timedelta(days=3), time(9, 0), time(11, 0), "ROOM-A", "INS-001", "scheduled"),
        ("Composting Class", today + timedelta(days=3), time(10, 0), time(12, 0), "ROOM-A", "INS-002", "conflict"),
        ("Green Living Seminar", today + timedelta(days=5), time(13, 0), time(15, 0), "ROOM-B", "INS-001", "scheduled"),
        ("Waste Audit Training", today + timedelta(days=7), time(9, 0), time(12, 0), "ROOM-C", "INS-003", "draft"),
    ]
    for title, sdate, st, et, cr, ins, status in sched_defs:
        if ScheduleItem.query.filter_by(title=title, scheduled_date=sdate).first():
            continue
        si = ScheduleItem(
            title=title, region_id=regions["NE"].id, scheduled_date=sdate,
            start_time=st, end_time=et,
            classroom_id=resources[cr].id, instructor_id=resources[ins].id,
            status=status, created_by=users["dispatcher"].id, updated_by=users["dispatcher"].id,
        )
        db.session.add(si)
    db.session.commit()
    click.echo("  Schedule items created")

    # Service items
    svc_defs = [
        ("WKS-001", "Recycling Workshop", "hourly", Decimal("75.00"), None, True, Decimal("30.00")),
        ("CMP-001", "Composting Starter Kit", "per_use", Decimal("45.00"), None, True, Decimal("20.00")),
        ("PKG-001", "Green Certification Package", "package", None, Decimal("299.99"), True, Decimal("120.00")),
        ("AUD-001", "Waste Audit Service", "hourly", Decimal("125.00"), None, True, Decimal("50.00")),
        ("CON-001", "Sustainability Consultation", "hourly", Decimal("150.00"), None, False, Decimal("60.00")),
    ]
    svc_items = {}
    for code, name, model, rate, pkg, taxable, cost in svc_defs:
        si = ServiceItem.query.filter_by(code=code).first()
        if not si:
            si = ServiceItem(code=code, name=name, pricing_model=model,
                           unit_rate=rate, package_price=pkg, taxable=taxable,
                           cost_amount=cost, active=True)
            db.session.add(si)
        svc_items[code] = si
    db.session.commit()
    click.echo("  Service items created")

    # Orders in various states
    order_defs = [
        ("Acme Corp", "NE", "created", [("WKS-001", 2), ("CMP-001", 5)]),
        ("GreenCity LLC", "SE", "paid", [("PKG-001", 1)]),
        ("EcoFirst Inc", "MW", "completed", [("AUD-001", 4), ("CON-001", 2)]),
        ("Nature's Way", "SW", "refunded", [("WKS-001", 1)]),
    ]
    for cust, reg_code, state, lines in order_defs:
        from app.services.order_service import generate_order_number
        if Order.query.filter_by(customer_name=cust).first():
            continue
        region = regions[reg_code]
        order = Order(
            order_number=generate_order_number(),
            customer_name=cust, region_id=region.id, state=state,
            tax_rate=region.sales_tax_rate,
            created_by=users["analyst"].id, updated_by=users["analyst"].id,
        )
        if state == "paid":
            order.paid_at = datetime.utcnow() - timedelta(days=2)
        elif state == "completed":
            order.completed_at = datetime.utcnow() - timedelta(days=1)
            order.paid_at = datetime.utcnow() - timedelta(days=3)
        elif state == "refunded":
            order.refunded_at = datetime.utcnow()
            order.paid_at = datetime.utcnow() - timedelta(days=5)
        db.session.add(order)
        db.session.flush()

        subtotal = Decimal("0")
        for svc_code, qty in lines:
            svc = svc_items[svc_code]
            unit = svc.unit_rate or svc.package_price or Decimal("0")
            line_sub = unit * Decimal(str(qty))
            oi = OrderItem(
                order_id=order.id, service_item_id=svc.id,
                description_snapshot=svc.name, quantity=qty,
                unit_rate=unit, line_subtotal=line_sub, taxable=svc.taxable,
            )
            db.session.add(oi)
            subtotal += line_sub

        taxable_sub = subtotal  # simplified
        tax = (taxable_sub * order.tax_rate).quantize(Decimal("0.01")) if order.tax_rate else Decimal("0")
        order.subtotal_amount = subtotal
        order.tax_amount = tax
        order.total_amount = subtotal + tax
        order.paid_amount = order.total_amount if state in ("paid", "completed", "refunded") else Decimal("0")

        if state in ("paid", "completed", "refunded"):
            pmt = Payment(
                order_id=order.id, tender_type="check",
                receipt_number=f"RCP-{order.order_number[-6:]}",
                amount=order.total_amount,
                recorded_by=users["analyst"].id,
            )
            db.session.add(pmt)

    db.session.commit()
    click.echo("  Orders created")

    # Sample report jobs
    rj = ReportJob(report_type="orders", requested_by=users["analyst"].id, status="completed",
                   row_count=4, created_at=datetime.utcnow() - timedelta(hours=2),
                   finished_at=datetime.utcnow() - timedelta(hours=1))
    db.session.add(rj)

    # Sample search queries
    for q, cnt in [("recycling", 3), ("composting", 2), ("nonexistent-term", 0)]:
        sq = SearchQuery(user_id=users["editor"].id, raw_query=q, normalized_query=q,
                        result_count=cnt, zero_results=(cnt == 0))
        db.session.add(sq)

    db.session.commit()
    click.echo("  Sample reports and search queries created")
    click.echo("Seeding complete!")
