"""File service tests."""

import io
import pytest
from app.services import file_service


class TestFileValidation:
    def test_allowed_extension(self, app):
        with app.app_context():
            f = _make_file("test.pdf", b"%PDF-1.4 content", "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is True

    def test_blocked_extension(self, app):
        with app.app_context():
            f = _make_file("test.exe", b"MZ binary", "application/octet-stream")
            ok, err = file_service.validate_upload(f)
            assert ok is False
            assert "blocked" in err.lower()

    def test_disallowed_extension(self, app):
        with app.app_context():
            f = _make_file("test.txt", b"hello", "text/plain")
            ok, err = file_service.validate_upload(f)
            assert ok is False

    def test_size_limit(self, app):
        with app.app_context():
            big = b"x" * (21 * 1024 * 1024)
            f = _make_file("big.pdf", big, "application/pdf")
            ok, err = file_service.validate_upload(f)
            assert ok is False
            assert "limit" in err.lower()

    def test_sha256_computation(self, app):
        with app.app_context():
            f = _make_file("test.pdf", b"test content", "application/pdf")
            sha = file_service.compute_sha256(f)
            assert len(sha) == 64

    def test_duplicate_detection(self, app, db, admin_user):
        with app.app_context():
            content = b"%PDF-1.4 duplicate test content"
            f1 = _make_file("original.pdf", content, "application/pdf")
            att1 = file_service.save_upload(f1, admin_user.id)
            assert att1.duplicate_of_id is None

            f2 = _make_file("copy.pdf", content, "application/pdf")
            att2 = file_service.save_upload(f2, admin_user.id)
            assert att2.duplicate_of_id == att1.id

    def test_signed_url(self, app, db, admin_user):
        with app.app_context():
            content = b"%PDF-1.4 signed url test"
            f = _make_file("signed.pdf", content, "application/pdf")
            att = file_service.save_upload(f, admin_user.id)
            url = file_service.generate_signed_url(att.id, admin_user.id)
            assert f"/files/{att.id}/download" in url

            import re
            params = dict(re.findall(r'(\w+)=([^&]+)', url))
            assert file_service.verify_signed_url(
                att.id, params["sig"], params["expires"], params["uid"]
            )


def _make_file(filename, content, content_type):
    from werkzeug.datastructures import FileStorage
    return FileStorage(
        stream=io.BytesIO(content),
        filename=filename,
        content_type=content_type,
    )
