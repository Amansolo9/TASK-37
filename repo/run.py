"""Production/development entry point with scheduler.

Used by gunicorn: gunicorn --preload "run:app"
Used locally:     python run.py

Scheduler design:
  The APScheduler background scheduler is started at module-import time.
  With gunicorn --preload, the module is imported once in the master process
  before forking workers, so the scheduler runs exactly once.

  For deployments that need isolated scheduling, set SCHEDULER_ENABLED=false
  for web workers and run a dedicated scheduler process:
      python -m app.tasks.run_scheduler
"""

import os
from app import create_app
from app.tasks.scheduler import init_scheduler

app = create_app()

# Initialize FTS tables
with app.app_context():
    from app.services.search_service import init_fts
    init_fts(app)

# Start background scheduler only once.
# SCHEDULER_ENABLED=false disables it (for worker-only processes).
if os.environ.get("SCHEDULER_ENABLED", "true").lower() != "false":
    init_scheduler(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
