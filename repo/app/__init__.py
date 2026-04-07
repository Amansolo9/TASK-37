"""GreenCycle Operations & Content Portal - App Factory."""

import os
from flask import Flask
from app.config import Config, TestConfig


def create_app(config_class=None):
    app = Flask(__name__, instance_relative_config=True)

    if config_class is None:
        config_class = TestConfig if os.environ.get("TESTING") else Config
    app.config.from_object(config_class)

    # Validate secrets in production mode (unconditional for non-test)
    if not app.config.get("TESTING"):
        config_class.validate_production_secrets()

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(str(app.config["STORAGE_ROOT"] / "uploads"), exist_ok=True)
    os.makedirs(str(app.config["STORAGE_ROOT"] / "archive"), exist_ok=True)
    os.makedirs(str(app.config["REPORT_OUTPUT_ROOT"]), exist_ok=True)

    # Initialize extensions
    from app.extensions import db, migrate, csrf, cache, login_manager
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    cache.init_app(app)
    login_manager.init_app(app)

    # Configure SQLite
    with app.app_context():
        if "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]:
            from sqlalchemy import event

            @event.listens_for(db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return db.session.get(User, int(user_id))

    # Session timeout middleware
    @app.before_request
    def check_session_timeout():
        from flask import session, redirect, url_for, request as req
        from flask_login import current_user, logout_user
        from datetime import datetime, timedelta

        if current_user.is_authenticated:
            now = datetime.utcnow()
            last = current_user.last_activity_at
            timeout = app.config["SESSION_TIMEOUT_MINUTES"]
            if last and (now - last) > timedelta(minutes=timeout):
                logout_user()
                session.clear()
                if not req.path.startswith("/api/"):
                    from flask import flash
                    flash("Session timed out due to inactivity.", "warning")
                    return redirect(url_for("auth.login"))
            current_user.last_activity_at = now
            db.session.commit()

    # Register template context
    @app.context_processor
    def inject_helpers():
        from app.utils.date_helpers import format_date_us, format_datetime_us
        return dict(
            format_date=format_date_us,
            format_datetime=format_datetime_us,
        )

    # Register blueprints
    from app.blueprints.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.blueprints.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from app.blueprints.cms import bp as cms_bp
    app.register_blueprint(cms_bp, url_prefix="/cms")

    from app.blueprints.search import bp as search_bp
    app.register_blueprint(search_bp, url_prefix="/search")

    from app.blueprints.dispatch import bp as dispatch_bp
    app.register_blueprint(dispatch_bp, url_prefix="/dispatch")

    from app.blueprints.catalog import bp as catalog_bp
    app.register_blueprint(catalog_bp, url_prefix="/catalog")

    from app.blueprints.orders import bp as orders_bp
    app.register_blueprint(orders_bp, url_prefix="/orders")

    from app.blueprints.analytics import bp as analytics_bp
    app.register_blueprint(analytics_bp, url_prefix="/analytics")

    from app.blueprints.files import bp as files_bp
    app.register_blueprint(files_bp, url_prefix="/files")

    from app.blueprints.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    csrf.exempt(api_bp)  # JWT API is CSRF-exempt

    # HTMX partial API: session-authenticated, CSRF-protected (NOT exempt)
    from app.blueprints.htmx import bp as htmx_bp
    app.register_blueprint(htmx_bp, url_prefix="/api/v1/htmx")

    # Dashboard route
    @app.route("/")
    @app.route("/dashboard")
    def dashboard():
        from flask_login import current_user
        from flask import render_template, redirect, url_for
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        return render_template("dashboard.html")

    # Import models for migration detection
    from app import models as _models  # noqa: F401

    # Register CLI commands
    from app.tasks.seed import seed_command
    app.cli.add_command(seed_command)

    return app
