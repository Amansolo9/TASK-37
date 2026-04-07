#!/bin/bash
set -e

echo "==> Running database migrations..."
flask db upgrade

echo "==> Initializing FTS search index..."
python -c "
from app import create_app
from app.services.search_service import init_fts
app = create_app()
with app.app_context():
    init_fts(app)
    print('    FTS index ready')
"

echo "==> Seeding database (idempotent)..."
flask seed

echo "==> Starting GreenCycle Portal on port 5000..."
# --preload ensures the app (and scheduler) is loaded once in the master process,
# preventing duplicate scheduler jobs across forked workers.
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --threads 4 \
    --timeout 120 \
    --preload \
    --access-logfile - \
    --error-logfile - \
    "run:app"
