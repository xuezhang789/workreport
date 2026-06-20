#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"

"${PYTHON_BIN}" manage.py check --deploy
"${PYTHON_BIN}" manage.py migrate --check
"${PYTHON_BIN}" manage.py validate_api_contract
"${PYTHON_BIN}" manage.py collectstatic --noinput --dry-run
"${PYTHON_BIN}" manage.py runtime_maintenance
