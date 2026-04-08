#!/bin/bash
set -e

cd "$(dirname "$0")"

usage() {
    echo "Usage: ./run_tests.sh [all|unit|api] [extra pytest args...]"
    echo ""
    echo "  all   - Run all tests (default)"
    echo "  unit  - Run unit tests only"
    echo "  api   - Run API/integration tests only"
    echo ""
    echo "Examples:"
    echo "  ./run_tests.sh              # run everything"
    echo "  ./run_tests.sh unit         # unit tests only"
    echo "  ./run_tests.sh api          # API tests only"
    echo "  ./run_tests.sh api -k auth  # API tests matching 'auth'"
}

TARGET="${1:-all}"
shift 2>/dev/null || true

case "$TARGET" in
    unit)
        echo "==> Running unit tests..."
        TEST_PATH="tests/unit_tests/"
        ;;
    api)
        echo "==> Running API / integration tests..."
        TEST_PATH="tests/api_tests/"
        ;;
    all)
        echo "==> Running full test suite..."
        TEST_PATH="tests/"
        ;;
    -h|--help|help)
        usage
        exit 0
        ;;
    *)
        # Treat unknown first arg as a pytest passthrough
        echo "==> Running full test suite..."
        TEST_PATH="tests/"
        set -- "$TARGET" "$@"
        ;;
esac

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
    web python -m pytest "$TEST_PATH" \
        -v \
        --tb=short \
        "$@"
