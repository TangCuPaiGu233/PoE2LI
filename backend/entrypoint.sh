#!/bin/bash
set -e

echo "=== Running database migrations ==="
alembic upgrade head 2>/dev/null || \
  python -c "from alembic.config import main; main()" upgrade head 2>/dev/null || \
  echo "WARNING: Alembic migration failed (tables will be created via create_all)"

echo "=== Starting application ==="
exec "$@"
