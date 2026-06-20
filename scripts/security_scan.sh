#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"

if [[ "${SKIP_BANDIT:-0}" != "1" ]]; then
  "${PYTHON_BIN}" -m bandit -q -r \
    audit core projects reports tasks work_logs settings.py urls.py asgi.py wsgi.py celery_app.py \
    -x "*/tests/*,*/management/commands/generate_*.py,*/management/commands/import_mock_data.py,*/management/commands/generate_large_scale_data.py" \
    --severity-level medium \
    --confidence-level medium
fi

if [[ "${SKIP_PIP_AUDIT:-0}" != "1" ]]; then
  PIP_AUDIT_CACHE_DIR="${PIP_AUDIT_CACHE_DIR:-.cache/pip-audit}"
  mkdir -p "${PIP_AUDIT_CACHE_DIR}"
  "${PYTHON_BIN}" -m pip_audit --cache-dir "${PIP_AUDIT_CACHE_DIR}" --local
fi
