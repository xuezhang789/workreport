#!/usr/bin/env sh
set -eu

if [ "${RUN_COLLECTSTATIC_ON_STARTUP:-1}" = "1" ]; then
  python manage.py collectstatic --noinput
fi

if [ "${RUN_MIGRATIONS_ON_STARTUP:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${RUN_SEARCH_REBUILD_ON_STARTUP:-0}" = "1" ]; then
  python manage.py rebuild_search_index --batch-size "${SEARCH_REBUILD_BATCH_SIZE:-500}"
fi

exec "$@"
