"""CMS routes for content management."""

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.blueprints.cms import bp
from app.services import cms_service
from app.models.cms import ContentItem, ContentVersion
from app.models.region import Category, Tag, Region
from app.forms.cms_forms import ContentForm, TaxonomyForm, PlacementForm
from app.utils.pagination import paginate_query
from app.utils.date_helpers import parse_datetime_us
from app.services.access_policy import apply_region_filter, check_region_access
from app.extensions import db
from functools import wraps


def permission_required(*perms):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.has_any_permission(*perms):
                flash("Permission denied.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


@bp.route("/content")
@login_required
@permission_required("content.create", "content.edit", "content.review", "content.publish")
def content_list():
    state = request.args.get("state")
    region_id = request.args.get("region_id", type=int)
    query = cms_service.get_content_list(state=state, region_id=region_id)
    query = apply_region_filter(query, ContentItem, current_user)
    pagination = paginate_query(query)
    regions = Region.query.filter_by(active=True).all()
    is_htmx = request.headers.get("HX-Request")
    template = "cms/content_list_partial.html" if is_htmx else "cms/content_list.html"
    return render_template(template, pagination=pagination, regions=regions,
                          current_state=state, current_region_id=region_id)


@bp.route("/content/new", methods=["GET", "POST"])
@login_required
@permission_required("content.create")
def content_new():
    form = ContentForm()
    _populate_form_choices(form)
    if form.validate_on_submit():
        from app.services.access_policy import validate_region_for_create
        if form.region_id.data and not validate_region_for_create(current_user, form.region_id.data):
            flash("Region is outside your authorized scope.", "danger")
            return render_template("cms/content_form.html", form=form, editing=False)
        try:
            item = cms_service.create_content(
                title=form.title.data,
                slug=form.slug.data or cms_service.slugify(form.title.data),
                body_html=form.body_html.data,
                summary=form.summary.data,
                author_id=current_user.id,
                region_id=form.region_id.data or None,
                media_type=form.media_type.data or None,
                category_ids=form.categories.data,
                tag_ids=form.tags.data,
            )
            flash("Content created.", "success")
            return redirect(url_for("cms.content_detail", id=item.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("cms/content_form.html", form=form, editing=False)


@bp.route("/content/<int:id>", methods=["GET", "POST"])
@login_required
@permission_required("content.create", "content.edit", "content.review")
def content_detail(id):
    item = db.session.get(ContentItem, id)
    if not item:
        flash("Content not found.", "danger")
        return redirect(url_for("cms.content_list"))
    if not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.content_list"))
    form = ContentForm()
    _populate_form_choices(form)
    if request.method == "GET":
        v = item.current_version
        if v:
            form.title.data = v.title
            form.summary.data = v.summary
            form.body_html.data = v.body_html
        form.slug.data = item.slug
        form.region_id.data = item.region_id
        form.media_type.data = item.media_type
        form.categories.data = [c.id for c in item.categories]
        form.tags.data = [t.id for t in item.tags]
    if form.validate_on_submit():
        try:
            cms_service.update_content_draft(
                item_id=item.id,
                title=form.title.data,
                body_html=form.body_html.data,
                summary=form.summary.data,
                editor_id=current_user.id,
                slug=form.slug.data,
                region_id=form.region_id.data or None,
                media_type=form.media_type.data or None,
                category_ids=form.categories.data,
                tag_ids=form.tags.data,
            )
            flash("Content saved.", "success")
            return redirect(url_for("cms.content_detail", id=item.id))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("cms/content_form.html", form=form, editing=True, item=item)


@bp.route("/content/<int:id>/submit-review", methods=["POST"])
@login_required
@permission_required("content.submit_review")
def submit_review(id):
    item = db.session.get(ContentItem, id)
    if not item or not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.content_list"))
    try:
        cms_service.submit_for_review(id, current_user.id)
        flash("Submitted for review.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("cms.content_detail", id=id))


@bp.route("/content/<int:id>/approve", methods=["POST"])
@login_required
@permission_required("content.publish")
def approve(id):
    item = db.session.get(ContentItem, id)
    if not item or not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.content_list"))
    notes = request.form.get("review_notes", "")
    try:
        cms_service.approve_and_publish(id, current_user.id, notes)
        flash("Content published.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("cms.content_detail", id=id))


@bp.route("/content/<int:id>/schedule", methods=["POST"])
@login_required
@permission_required("content.schedule")
def schedule(id):
    item = db.session.get(ContentItem, id)
    if not item or not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.content_list"))
    scheduled_at = parse_datetime_us(request.form.get("scheduled_at"))
    if not scheduled_at:
        flash("Valid date/time required for scheduling.", "danger")
        return redirect(url_for("cms.content_detail", id=id))
    notes = request.form.get("review_notes", "")
    try:
        cms_service.schedule_publish(id, current_user.id, scheduled_at, notes)
        flash("Content scheduled for publish.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("cms.content_detail", id=id))


@bp.route("/content/<int:id>/withdraw", methods=["POST"])
@login_required
@permission_required("content.withdraw")
def withdraw(id):
    item = db.session.get(ContentItem, id)
    if not item or not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.content_list"))
    try:
        cms_service.withdraw_content(id, current_user.id)
        flash("Content withdrawn.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("cms.content_detail", id=id))


@bp.route("/content/<int:id>/versions")
@login_required
@permission_required("content.create", "content.edit", "content.review", "content.publish")
def content_versions(id):
    item = db.session.get(ContentItem, id)
    if not item:
        flash("Content not found.", "danger")
        return redirect(url_for("cms.content_list"))
    if not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.content_list"))
    versions = ContentVersion.query.filter_by(content_item_id=id).order_by(
        ContentVersion.version_number.desc()
    ).all()
    return render_template("cms/content_versions.html", item=item, versions=versions)


@bp.route("/review-queue")
@login_required
@permission_required("content.review")
def review_queue():
    from app.services.access_policy import get_actor_region_ids
    items = cms_service.get_review_queue()
    region_ids = get_actor_region_ids(current_user)
    if region_ids is not None:
        items = [i for i in items if i.region_id is None or i.region_id in region_ids]
    return render_template("cms/review_queue.html", items=items)


@bp.route("/taxonomy/categories")
@login_required
@permission_required("content.manage_taxonomy")
def categories():
    cats = Category.query.order_by(Category.name).all()
    form = TaxonomyForm()
    is_htmx = request.headers.get("HX-Request")
    template = "cms/categories_partial.html" if is_htmx else "cms/categories.html"
    return render_template(template, categories=cats, form=form)


@bp.route("/taxonomy/categories/add", methods=["POST"])
@login_required
@permission_required("content.manage_taxonomy")
def category_add():
    form = TaxonomyForm()
    if form.validate_on_submit():
        slug = cms_service.slugify(form.name.data)
        cat = Category(name=form.name.data, slug=slug, active=True)
        db.session.add(cat)
        try:
            db.session.commit()
            flash("Category added.", "success")
        except Exception:
            db.session.rollback()
            flash("Category with that name/slug already exists.", "danger")
    cats = Category.query.order_by(Category.name).all()
    return render_template("cms/categories_partial.html", categories=cats, form=TaxonomyForm())


@bp.route("/taxonomy/tags")
@login_required
@permission_required("content.manage_taxonomy")
def tags():
    tags_list = Tag.query.order_by(Tag.name).all()
    form = TaxonomyForm()
    return render_template("cms/tags.html", tags=tags_list, form=form)


@bp.route("/taxonomy/tags/add", methods=["POST"])
@login_required
@permission_required("content.manage_taxonomy")
def tag_add():
    form = TaxonomyForm()
    if form.validate_on_submit():
        slug = cms_service.slugify(form.name.data)
        tag = Tag(name=form.name.data, slug=slug, active=True)
        db.session.add(tag)
        try:
            db.session.commit()
            flash("Tag added.", "success")
        except Exception:
            db.session.rollback()
            flash("Tag with that name/slug already exists.", "danger")
    tags_list = Tag.query.order_by(Tag.name).all()
    return render_template("cms/tags_partial.html", tags=tags_list, form=TaxonomyForm())


@bp.route("/homepage-placement")
@login_required
@permission_required("content.manage_homepage_placement")
def homepage_placement():
    data = cms_service.get_homepage_content()
    pub_query = ContentItem.query.filter_by(workflow_state="published").order_by(ContentItem.published_at.desc())
    pub_query = apply_region_filter(pub_query, ContentItem, current_user)
    published = pub_query.all()
    return render_template("cms/homepage_placement.html", homepage=data, published=published)


@bp.route("/homepage-placement/<int:id>", methods=["POST"])
@login_required
@permission_required("content.manage_homepage_placement")
def update_placement(id):
    item = db.session.get(ContentItem, id)
    if not item or not check_region_access(item, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("cms.homepage_placement"))
    cms_service.update_placement(
        item_id=id,
        is_pinned="is_pinned" in request.form,
        is_recommended="is_recommended" in request.form,
        is_carousel="is_carousel" in request.form,
        carousel_rank=request.form.get("carousel_rank", type=int),
        user_id=current_user.id,
    )
    flash("Placement updated.", "success")
    return redirect(url_for("cms.homepage_placement"))


@bp.route("/check-slug")
@login_required
def check_slug():
    slug = request.args.get("slug", "")
    exclude_id = request.args.get("exclude_id", type=int)
    if cms_service.is_slug_unique(slug, exclude_id):
        return '<span class="text-success">Slug available</span>'
    return '<span class="text-danger">Slug already taken</span>'


def _populate_form_choices(form):
    form.region_id.choices = [(0, "-- None --")] + [
        (r.id, r.name) for r in Region.query.filter_by(active=True).all()
    ]
    form.categories.choices = [(c.id, c.name) for c in Category.query.filter_by(active=True).all()]
    form.tags.choices = [(t.id, t.name) for t in Tag.query.filter_by(active=True).all()]
