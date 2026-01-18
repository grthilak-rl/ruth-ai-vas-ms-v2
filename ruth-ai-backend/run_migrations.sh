#!/bin/bash
# Database migration script for Ruth AI Backend
set -e

echo "Running database migrations..."

cd /app
export PYTHONPATH=/app:$PYTHONPATH

# Run alembic migrations
/usr/local/bin/alembic upgrade head

echo "✓ Migrations completed successfully!"
