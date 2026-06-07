#!/bin/bash
set -e

echo "=== Running database migrations ==="
cd /app && alembic upgrade head || \
  cd /app && python -c "
import os, sys
sys.path.insert(0, '.')
from alembic.config import Config
from alembic import command
cfg = Config('alembic.ini')
db_url = os.environ.get('DATABASE_URL')
if db_url:
    cfg.set_main_option('sqlalchemy.url', db_url)
command.upgrade(cfg, 'head')
" || \
  echo "WARNING: Alembic migration failed (tables will be created via create_all)"

echo "=== Starting application ==="
exec "$@"
