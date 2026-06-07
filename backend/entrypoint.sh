#!/bin/bash
set -e

echo "=== Running database migrations ==="
cd /app && python -c "
import os, sys
sys.path.insert(0, '.')
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text

cfg = Config('alembic.ini')
db_url = os.environ.get('DATABASE_URL')
if db_url:
    cfg.set_main_option('sqlalchemy.url', db_url)

engine = create_engine(db_url or cfg.get_main_option('sqlalchemy.url'))

# Check if alembic_version exists
with engine.connect() as conn:
    result = conn.execute(text(
        \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'alembic_version')\"
    ))
    has_version = result.scalar()

if not has_version:
    # Tables were created by create_all — stamp to current head so alembic knows the state
    print('No alembic_version table found. Stamp to head (tables already exist).')
    command.stamp(cfg, 'head')
else:
    # Normal migration path
    command.upgrade(cfg, 'head')

print('Migration step complete.')
" || echo "WARNING: Alembic migration step had issues (tables managed via create_all)"

echo "=== Starting application ==="
exec "$@"
