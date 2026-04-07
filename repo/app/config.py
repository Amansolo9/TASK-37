import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


_INSECURE_DEFAULTS = {"dev-secret-key-change-me", "dev-jwt-secret-change-me", ""}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    SESSION_TIMEOUT_MINUTES = int(os.environ.get("SESSION_TIMEOUT_MINUTES", 30))
    LOGIN_LOCKOUT_THRESHOLD = int(os.environ.get("LOGIN_LOCKOUT_THRESHOLD", 5))
    LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", 15))

    SQLITE_PATH = os.environ.get("SQLITE_PATH", "instance/greencycle.db")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{BASE_DIR / SQLITE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", str(BASE_DIR / "storage")))
    REPORT_OUTPUT_ROOT = Path(
        os.environ.get("REPORT_OUTPUT_ROOT", str(BASE_DIR / "storage" / "generated_reports"))
    )
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", 20))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

    DOWNLOAD_URL_TTL_SECONDS = int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", 600))
    ATTACHMENT_ARCHIVE_DAYS = int(os.environ.get("ATTACHMENT_ARCHIVE_DAYS", 180))
    ATTACHMENT_PURGE_YEARS = int(os.environ.get("ATTACHMENT_PURGE_YEARS", 7))
    ENABLE_FILE_PURGE = os.environ.get("ENABLE_FILE_PURGE", "false").lower() == "true"

    API_DAILY_QUOTA = int(os.environ.get("API_DAILY_QUOTA", 1000))
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES_SECONDS = 3600

    FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")

    @classmethod
    def validate_production_secrets(cls):
        """Reject insecure defaults in production. Call during startup."""
        errors = []
        if cls.SECRET_KEY in _INSECURE_DEFAULTS:
            errors.append("SECRET_KEY must be set to a strong random value")
        if cls.JWT_SECRET_KEY in _INSECURE_DEFAULTS:
            errors.append("JWT_SECRET_KEY must be set to a strong random value")
        if not cls.FIELD_ENCRYPTION_KEY or cls.FIELD_ENCRYPTION_KEY in _INSECURE_DEFAULTS:
            errors.append("FIELD_ENCRYPTION_KEY must be set to a valid Fernet key")
        if errors:
            raise RuntimeError(
                "Production config validation failed:\n  - " + "\n  - ".join(errors)
            )

    EXTERNAL_INTEGRATIONS_ENABLED = (
        os.environ.get("EXTERNAL_INTEGRATIONS_ENABLED", "false").lower() == "true"
    )
    WATERMARK_DEFAULT_ENABLED = (
        os.environ.get("WATERMARK_DEFAULT_ENABLED", "false").lower() == "true"
    )

    DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", 50))
    AGGREGATE_CACHE_TTL_SECONDS = int(os.environ.get("AGGREGATE_CACHE_TTL_SECONDS", 600))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = SESSION_TIMEOUT_MINUTES * 60

    WTF_CSRF_ENABLED = True

    CACHE_TYPE = "FileSystemCache"
    CACHE_DIR = str(BASE_DIR / "instance" / "cache")
    CACHE_DEFAULT_TIMEOUT = AGGREGATE_CACHE_TTL_SECONDS


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret"
    JWT_SECRET_KEY = "test-jwt-secret"
    FIELD_ENCRYPTION_KEY = "sftLkMsijRqJsseVyPhBfqR28fi_Z0W_XA5QMvjVaCg="  # valid Fernet key for tests
    STORAGE_ROOT = Path("/tmp/greencycle_test_storage")
    REPORT_OUTPUT_ROOT = Path("/tmp/greencycle_test_reports")
