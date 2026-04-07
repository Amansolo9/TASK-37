"""Auth routes: login, logout."""

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from app.blueprints.auth import bp
from app.services.auth_service import authenticate_user
from app.services.audit_service import log_action
from app.forms.auth_forms import LoginForm


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user, error = authenticate_user(form.username.data, form.password.data)
        if user:
            login_user(user)
            from app.utils.auth_context import is_safe_redirect_url
            next_page = request.args.get("next")
            if next_page and not is_safe_redirect_url(next_page):
                next_page = None
            return redirect(next_page or url_for("dashboard"))
        flash(error, "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout")
def logout():
    if current_user.is_authenticated:
        log_action(current_user.id, "logout", "user", current_user.id)
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
