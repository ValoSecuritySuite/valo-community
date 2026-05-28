# Upstream sync

Valo Community Edition is exported from the private **valo** codebase.

## Export a fresh community tree

From the Valo monorepo root:

```bash
rsync -a --delete \
  --exclude 'venv/' --exclude '.git/' --exclude 'data/' \
  --exclude '__pycache__/' --exclude 'web/node_modules/' \
  valo/ valo-community/
```

Then re-apply community-only customizations:

- `app/main.py` (no enterprise routers)
- `app/api/routes.py` (no portfolio / ingest / executive routes)
- `app/core/config.py` (default `APP_EDITION=community`, reject enterprise)
- `README.md`, `docker-compose.yml`, deleted enterprise API modules

## Publishing

This folder is intended to be its **own git repository**:

```bash
cd valo-community
git init
git remote add origin git@github.com:YOUR_ORG/valo-community.git
```

Do not push the private `valo` repository to the public remote.
