"""File management routes."""

from flask import render_template, redirect, url_for, flash, request, send_file, abort
from flask_login import login_required, current_user
from functools import wraps
from pathlib import Path
from app.blueprints.files import bp
from app.services import file_service
from app.services.access_policy import can_access_attachment
from app.models.files import Attachment
from app.extensions import db


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


@bp.route("/upload", methods=["GET", "POST"])
@login_required
@permission_required("files.upload")
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        if not f:
            flash("No file selected.", "danger")
            return render_template("files/upload.html")
        try:
            att = file_service.save_upload(f, current_user.id)
            if att.duplicate_of_id:
                flash(f"File uploaded (duplicate of #{att.duplicate_of_id}).", "warning")
            else:
                flash("File uploaded.", "success")
            return redirect(url_for("files.file_list"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template("files/upload.html")


@bp.route("")
@login_required
@permission_required("files.download")
def file_list():
    from app.utils.pagination import paginate_query
    query = Attachment.query.filter(Attachment.deleted_at.is_(None))
    # Scope file list: admin sees all, others see only own uploads
    if not current_user.has_permission("admin.manage_users"):
        query = query.filter(Attachment.uploaded_by == current_user.id)
    query = query.order_by(Attachment.uploaded_at.desc())
    pagination = paginate_query(query)
    return render_template("files/file_list.html", pagination=pagination)


@bp.route("/<int:id>/download-link")
@login_required
@permission_required("files.download")
def download_link(id):
    att = db.session.get(Attachment, id)
    if not att or att.deleted_at:
        flash("File not found.", "danger")
        return redirect(url_for("files.file_list"))
    if not can_access_attachment(att, current_user):
        flash("Access denied.", "danger")
        return redirect(url_for("files.file_list"))
    url = file_service.generate_signed_url(id, current_user.id)
    return render_template("files/download_link.html", attachment=att, download_url=url)


@bp.route("/<int:id>/download")
@login_required
@permission_required("files.download")
def download(id):
    sig = request.args.get("sig", "")
    expires = request.args.get("expires", "")
    uid = request.args.get("uid", "")

    if not file_service.verify_signed_url(id, sig, expires, uid):
        abort(403, "Invalid or expired download link.")

    if str(current_user.id) != str(uid):
        abort(403, "Permission denied.")

    att = db.session.get(Attachment, id)
    if not can_access_attachment(att, current_user):
        abort(403, "Access denied to this attachment.")

    apply_wm = request.args.get("watermark", "0") == "1"
    path, filename = file_service.get_download_path(id, current_user.id, apply_watermark=apply_wm)
    if not path:
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)
