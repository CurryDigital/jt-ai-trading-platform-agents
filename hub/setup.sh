#!/bin/bash
# Setup script for Hub Event Router

set -e

echo "=== Hub Event Router Setup ==="

# Check for PostgreSQL
if ! command -v psql &> /dev/null; then
    echo "Error: PostgreSQL client (psql) not found"
    echo "Install with: sudo apt-get install postgresql-client"
    exit 1
fi

# Get database URL
DB_URL="${HUB_DATABASE_URL:-postgresql://localhost:5432/hub_events}"
echo "Database URL: $DB_URL"

# Extract database name
DB_NAME=$(echo "$DB_URL" | sed -n 's/.*\/\([^\/]*\)$/\1/p')

# Create database if it doesn't exist
echo "Creating database if not exists..."
psql postgres://localhost:5432 -c "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    psql postgres://localhost:5432 -c "CREATE DATABASE $DB_NAME;"

# Run schema
echo "Initializing schema..."
psql "$DB_URL" -f hub/schema.sql

echo "=== Setup Complete ==="
echo ""
echo "Test the installation:"
echo "  python -c \"from hub import emit_event; print('OK')\""
echo ""
echo "Run the demo:"
echo "  python hub/agents.py"
