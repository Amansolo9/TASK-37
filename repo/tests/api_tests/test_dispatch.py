"""Dispatch and scheduling tests."""

import pytest
from datetime import date, time, timedelta
from app.services import dispatch_service
from app.models.dispatch import Resource, ScheduleItem, ScheduleConflict
from app.models.region import Region


class TestConflictDetection:
    @pytest.fixture
    def setup_resources(self, db, region):
        r1 = Resource(resource_type="classroom", name="Room 1", code="R1",
                     region_id=region.id, active=True)
        r2 = Resource(resource_type="instructor", name="Teacher 1", code="T1",
                     region_id=region.id, active=True)
        db.session.add_all([r1, r2])
        db.session.commit()
        return r1, r2

    def test_instructor_overlap_detected(self, app, db, admin_user, region, setup_resources):
        r1, ins = setup_resources
        with app.app_context():
            tomorrow = date.today() + timedelta(days=1)
            item1 = dispatch_service.create_schedule_item(
                "Class A", region.id, tomorrow, time(9, 0), time(11, 0),
                classroom_id=r1.id, instructor_id=ins.id, user_id=admin_user.id,
            )
            item2 = dispatch_service.create_schedule_item(
                "Class B", region.id, tomorrow, time(10, 0), time(12, 0),
                instructor_id=ins.id, user_id=admin_user.id,
            )
            assert item2.status == "conflict"
            conflicts = ScheduleConflict.query.filter_by(schedule_item_id=item2.id).all()
            assert any("instructor" in c.conflict_type for c in conflicts)

    def test_no_conflict_different_days(self, app, db, admin_user, region, setup_resources):
        r1, ins = setup_resources
        with app.app_context():
            day1 = date.today() + timedelta(days=2)
            day2 = date.today() + timedelta(days=3)
            dispatch_service.create_schedule_item(
                "Day1", region.id, day1, time(9, 0), time(11, 0),
                instructor_id=ins.id, user_id=admin_user.id,
            )
            item2 = dispatch_service.create_schedule_item(
                "Day2", region.id, day2, time(9, 0), time(11, 0),
                instructor_id=ins.id, user_id=admin_user.id,
            )
            assert item2.status == "scheduled"

    def test_reschedule_creates_change_record(self, app, db, admin_user, region, setup_resources):
        r1, ins = setup_resources
        with app.app_context():
            day1 = date.today() + timedelta(days=10)
            day2 = date.today() + timedelta(days=11)
            item = dispatch_service.create_schedule_item(
                "Move Me", region.id, day1, time(9, 0), time(11, 0),
                instructor_id=ins.id, user_id=admin_user.id,
            )
            dispatch_service.reschedule(
                item.id, day2, time(10, 0), time(12, 0), admin_user.id,
            )
            from app.models.dispatch import ScheduleChange
            changes = ScheduleChange.query.filter_by(schedule_item_id=item.id).all()
            assert len(changes) >= 1
            assert changes[0].change_type == "reschedule"
