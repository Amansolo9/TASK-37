"""Search tests."""

import pytest
from app.services import search_service


class TestSearch:
    def test_search_logs_query(self, app, db, admin_user):
        with app.app_context():
            results, count = search_service.search("test query", user_id=admin_user.id)
            from app.models.search import SearchQuery
            logged = SearchQuery.query.filter_by(raw_query="test query").first()
            assert logged is not None

    def test_zero_result_flagged(self, app, db, admin_user):
        with app.app_context():
            results, count = search_service.search("xyznonexistent", user_id=admin_user.id)
            from app.models.search import SearchQuery
            logged = SearchQuery.query.filter_by(raw_query="xyznonexistent").first()
            assert logged.zero_results is True

    def test_trending_terms(self, app, db, admin_user):
        with app.app_context():
            for _ in range(3):
                search_service.search("popular term", user_id=admin_user.id)
            trending = search_service.get_trending_terms(days=7)
            assert any("popular term" in t[0] for t in trending)
