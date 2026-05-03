---
name: deploy-frontend
description: Build and deploy the React frontend to the Nginx production web root. Use this after making any frontend changes to ensure they are live.
---

# Deploy Frontend

This skill ensures that frontend changes are correctly built and synchronized with the production web server.

## Quick Start

Run the bundled deployment script:
```bash
./scripts/deploy.sh
```

## Manual Workflow

If the script fails, follow these steps manually:

1. **Build**: Run the build script in the frontend directory.
   ```bash
   cd ~/web_app/frontend && npm run build
   ```

2. **Sync**: Copy the build artifacts to the Nginx web root.
   ```bash
   sudo cp -r ~/web_app/frontend/dist/* /var/www/trade.jtcml.com/
   ```

3. **Permissions**: Ensure the web server can read the files.
   ```bash
   sudo chown -R www-data:www-data /var/www/trade.jtcml.com/
   ```

4. **Reload**: Reload Nginx to ensure new assets are served correctly.
   ```bash
   sudo systemctl reload nginx
   ```

## Troubleshooting

- If the user doesn't see changes, advise a **hard refresh** (Ctrl+F5).
- Verify the `dist/index.html` exists before copying.
