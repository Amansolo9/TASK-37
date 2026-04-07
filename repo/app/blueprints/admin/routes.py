"""Admin routes for user, role, region, settings, audit, api-client management."""

from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app.blueprints.admin import bp
from app.services import admin_service
from app.services.audit_service import log_action
from app.services.auth_service import create_user
from app.forms.admin_forms import UserForm, RegionForm
from app.models.user import AuditLog, Setting, Role, CAPABILITIES
from app.models.api import ApiClient
from app.extensions import db
from app.utils.pagination import paginate_query


def permission_required(*perms):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not current_user.has_any_permission(*perms):
                flash("Permission denied.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


@bp.route("/users")
@login_required
@permission_required("admin.manage_users")
def users():
    from app.models.user import User
    query = User.query.order_by(User.username)
    pagination = paginate_query(query)
    return render_template("admin/users.html", pagination=pagination)


@bp.route("/users/new", methods=["GET", "POST"])
@login_required
@permission_required("admin.manage_users")
def user_new():
    from app.forms.admin_forms import UserCreateForm
    form = UserCreateForm()
    form.roles.choices = [(r.id, r.name) for r in admin_service.get_all_roles()]
    if form.validate_on_submit():
        role_names = [Role.query.get(rid).name for rid in form.roles.data] if form.roles.data else []
        user = create_user(form.username.data, form.display_name.data, form.password.data, role_names)
        log_action(current_user.id, "user_created", "user", user.id)
        flash("User created.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, editing=False)


@bp.route("/users/<int:user_id>", methods=["GET", "POST"])
@login_required
@permission_required("admin.manage_users")
def user_edit(user_id):
    user = admin_service.get_user(user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))
    form = UserForm(obj=user)
    form.roles.choices = [(r.id, r.name) for r in admin_service.get_all_roles()]
    if request.method == "GET":
        form.roles.data = [r.id for r in user.roles]
        form.is_active.data = user.is_active_user
    if form.validate_on_submit():
        admin_service.update_user(
            user, form.display_name.data, form.is_active.data,
            form.roles.data, form.password.data or None, current_user.id,
        )
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, editing=True, user=user)


@bp.route("/users/check-username")
@login_required
@permission_required("admin.manage_users")
def check_username():
    from app.models.user import User
    username = request.args.get("username", "")
    user_id = request.args.get("user_id", type=int)
    q = User.query.filter_by(username=username)
    if user_id:
        q = q.filter(User.id != user_id)
    exists = q.first() is not None
    if exists:
        return '<span class="text-danger">Username already taken</span>'
    return '<span class="text-success">Username available</span>'


@bp.route("/roles")
@login_required
@permission_required("admin.manage_roles")
def roles():
    roles = admin_service.get_all_roles()
    return render_template("admin/roles.html", roles=roles, capabilities=CAPABILITIES)


@bp.route("/settings")
@login_required
@permission_required("admin.manage_settings")
def settings():
    settings_list = Setting.query.order_by(Setting.key).all()
    return render_template("admin/settings.html", settings=settings_list)


@bp.route("/regions")
@login_required
@permission_required("admin.manage_settings")
def regions():
    regions = admin_service.get_all_regions()
    return render_template("admin/regions.html", regions=regions)


@bp.route("/regions/new", methods=["GET", "POST"])
@login_required
@permission_required("admin.manage_settings")
def region_new():
    form = RegionForm()
    if form.validate_on_submit():
        admin_service.create_region(form.code.data, form.name.data, form.sales_tax_rate.data, form.active.data)
        flash("Region created.", "success")
        return redirect(url_for("admin.regions"))
    return render_template("admin/region_form.html", form=form, editing=False)


@bp.route("/regions/<int:region_id>", methods=["GET", "POST"])
@login_required
@permission_required("admin.manage_settings")
def region_edit(region_id):
    region = admin_service.get_region(region_id)
    if not region:
        flash("Region not found.", "danger")
        return redirect(url_for("admin.regions"))
    form = RegionForm(obj=region)
    if form.validate_on_submit():
        admin_service.update_region(region, form.code.data, form.name.data, form.sales_tax_rate.data, form.active.data, current_user.id)
        flash("Region updated.", "success")
        return redirect(url_for("admin.regions"))
    return render_template("admin/region_form.html", form=form, editing=True, region=region)


@bp.route("/api-clients")
@login_required
@permission_required("admin.manage_api_keys")
def api_clients():
    query = ApiClient.query.order_by(ApiClient.name)
    pagination = paginate_query(query)
    return render_template("admin/api_clients.html", pagination=pagination)


@bp.route("/api-clients/new", methods=["GET", "POST"])
@login_required
@permission_required("admin.manage_api_keys")
def api_client_new():
    from app.forms.admin_forms import ApiClientForm
    form = ApiClientForm()
    if form.validate_on_submit():
        scopes = [s.strip() for s in form.scopes.data.split("\n") if s.strip()] if form.scopes.data else []
        from app.services.api_auth_service import create_api_client
        client_obj, raw_secret = create_api_client(form.name.data, scopes, current_user.id)
        flash(f"API client created. Key ID: {client_obj.key_id}", "success")
        return render_template("admin/api_client_created.html", client=client_obj, secret=raw_secret)
    return render_template("admin/api_client_form.html", form=form)


@bp.route("/api-clients/<int:client_id>/revoke", methods=["POST"])
@login_required
@permission_required("admin.manage_api_keys")
def api_client_revoke(client_id):
    client_obj = ApiClient.query.get(client_id)
    if not client_obj:
        flash("API client not found.", "danger")
        return redirect(url_for("admin.api_clients"))
    client_obj.active = False
    db.session.commit()
    log_action(current_user.id, "api_client_revoked", "api_client", client_obj.id)
    flash(f"API client '{client_obj.name}' has been revoked.", "success")
    return redirect(url_for("admin.api_clients"))


@bp.route("/audit-logs")
@login_required
@permission_required("admin.view_audit_logs")
def audit_logs():
    query = AuditLog.query.order_by(AuditLog.created_at.desc())
    action_filter = request.args.get("action")
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)
    pagination = paginate_query(query)
    return render_template("admin/audit_logs.html", pagination=pagination, action_filter=action_filter)
