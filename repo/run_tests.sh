#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "==> Running GreenCycle Portal test suite..."
echo ""

python -m pytest tests/ \
    -v \
    --tb=short \
    "$@"
