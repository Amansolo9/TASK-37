"""Standalone scheduler process.

Run this when web workers have SCHEDULER_ENABLED=false:
    python -m app.tasks.run_scheduler
"""

import time
from app import create_app
from app.tasks.scheduler import init_scheduler

app = create_app()

with app.app_context():
    from app.services.search_service import init_fts
    init_fts(app)

init_scheduler(app)
print("Scheduler running. Press Ctrl+C to stop.")

try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    from app.tasks.scheduler import scheduler
    scheduler.shutdown()
    print("Scheduler stopped.")
