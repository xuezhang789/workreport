#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"

"${PYTHON_BIN}" -m pip check
"${PYTHON_BIN}" manage.py check
"${PYTHON_BIN}" manage.py makemigrations --check --dry-run
"${PYTHON_BIN}" manage.py validate_api_contract

DJANGO_SECRET_KEY='ci-production-security-check-key-9fc034582dad4c60aeb0b0ca' \
DJANGO_DEBUG=False \
DJANGO_TEST_MODE=0 \
DJANGO_ALLOWED_HOSTS=example.com \
DJANGO_ALLOW_SQLITE_IN_PRODUCTION=True \
FIELD_ENCRYPTION_KEYS='j3On4pp-WU-C4aaC5PUMQtNOgSSI20r_dgzYr4gDJIo=' \
METRICS_TOKEN='ci-metrics-token' \
CHANNEL_LAYER_BACKEND=memory \
CACHE_BACKEND=locmem \
"${PYTHON_BIN}" manage.py check --deploy

LOG_LEVEL=WARNING "${PYTHON_BIN}" manage.py test --verbosity 1
