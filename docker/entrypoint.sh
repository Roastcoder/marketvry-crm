#!/bin/bash
set -e

echo "Starting Horilla CRM..."

# Extract database host and port from DATABASE_URL
DB_HOST=$(python -c "import os, urllib.parse; print(urllib.parse.urlparse(os.environ.get('DATABASE_URL', '')).hostname or 'db')")
DB_PORT=$(python -c "import os, urllib.parse; print(urllib.parse.urlparse(os.environ.get('DATABASE_URL', '')).port or 5432)")

# Wait for PostgreSQL to be ready (with timeout)
echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."
MAX_TRIES=30
COUNT=0
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -ge "$MAX_TRIES" ]; then
    echo "ERROR: PostgreSQL not available after $MAX_TRIES attempts"
    exit 1
  fi
  sleep 1
done
echo "PostgreSQL is ready!"

# Run migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

echo "Starting server..."
exec "$@"
