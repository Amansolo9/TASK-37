#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "==> Running GreenCycle Portal test suite..."
echo ""

# Build the test image (reuses cached layers from the app image)
docker compose build web

# Run tests inside the container, overriding the entrypoint
docker compose run --rm \
    --entrypoint "" \
    -e FLASK_APP=wsgi.py \
    -e SECRET_KEY=test-secret-not-for-production \
    -e JWT_SECRET_KEY=test-jwt-secret-not-for-production \
    -e FIELD_ENCRYPTION_KEY=sftLkMsijRqJsseVyPhBfqR28fi_Z0W_XA5QMvjVaCg= \
    -e TESTING=1 \
    --no-deps \
    web python -m pytest tests/ \
        -v \
        --tb=short \
        "$@"
