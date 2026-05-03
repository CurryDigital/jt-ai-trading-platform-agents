#!/bin/bash
# scripts/deploy.sh - Build and sync frontend to production Nginx root

set -e

REPO_FRONTEND_DIR="$HOME/web_app/frontend"
PRODUCTION_WEB_ROOT="/var/www/trade.jtcml.com"

echo "🚀 Starting deployment..."

# 1. Build
echo "📦 Building frontend..."
cd "$REPO_FRONTEND_DIR"
npm run build

# 2. Sync
echo "🔄 Syncing to production root: $PRODUCTION_WEB_ROOT"
# Using sudo as we need to write to /var/www
sudo cp -r "$REPO_FRONTEND_DIR/dist/"* "$PRODUCTION_WEB_ROOT/"

# 3. Permissions
echo "🔐 Setting permissions..."
sudo chown -R www-data:www-data "$PRODUCTION_WEB_ROOT/"

# 4. Reload Nginx
echo "🌐 Reloading Nginx..."
sudo systemctl reload nginx

echo "✅ Deployment complete!"
