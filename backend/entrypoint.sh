#!/bin/bash
set -e

echo "=== Running database migrations ==="
python -m alembic upgrade head || echo "WARNING: Alembic migration failed (tables will be created via create_all)"

echo "=== Starting application ==="
exec "$@"
