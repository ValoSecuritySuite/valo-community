# Release v0.1.0-community

## Highlights

First public **Community Edition** of Valo:

- `POST /analyze` with deterministic prompt-injection scoring
- YAML rule engine + governance policies (`allow` / `warn` / `deny`)
- OpenAI-compatible proxy in **monitor** mode
- Basic PDF reports (no custom branding)
- Plugin loader
- Docker Compose: `docker-compose.yml` (community defaults)
- Web UI: Playground, Policies, Rules, Analysis, Firewall (monitor only)

## Not included (enterprise)

- Portfolio rollups (`/portfolio/*`)
- AI Firewall **enforce** mode
- Executive dashboard, reporting automation, playbooks, learning loop
- Custom report branding

## Upgrade path

Set `APP_EDITION=enterprise` and enable the modules documented in
`.env.example` for the full product surface.

## Verify

```bash
docker compose up --build
python scripts/community_smoke.py
```
