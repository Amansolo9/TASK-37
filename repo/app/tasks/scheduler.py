"""APScheduler background jobs for the application."""

from apscheduler.schedulers.background import BackgroundScheduler


scheduler = BackgroundScheduler()


def init_scheduler(app):
    """Configure and start background jobs."""

    def scheduled_publish_job():
        with app.app_context():
            from app.services.cms_service import process_scheduled_publishes
            count = process_scheduled_publishes()
            if count:
                app.logger.info(f"Scheduled publish: {count} items published")

    def report_job_processor():
        with app.app_context():
            from app.models.analytics import ReportJob
            from app.services.analytics_service import process_report_job
            from app.extensions import db
            jobs = ReportJob.query.filter_by(status="queued").limit(5).all()
            for job in jobs:
                process_report_job(job.id)

    def attachment_archive_job():
        with app.app_context():
            from app.services.file_service import archive_old_attachments
            count = archive_old_attachments()
            if count:
                app.logger.info(f"Archived {count} attachments")

    def attachment_purge_job():
        with app.app_context():
            from app.services.file_service import purge_expired_attachments
            count = purge_expired_attachments()
            if count:
                app.logger.info(f"Purged {count} attachments")

    scheduler.add_job(scheduled_publish_job, "interval", minutes=1, id="scheduled_publish")
    scheduler.add_job(report_job_processor, "interval", seconds=30, id="report_processor")
    scheduler.add_job(attachment_archive_job, "cron", hour=2, minute=0, id="attachment_archive")
    scheduler.add_job(attachment_purge_job, "cron", hour=3, minute=0, id="attachment_purge")

    if not scheduler.running:
        scheduler.start()
    app.logger.info("Background scheduler started")
