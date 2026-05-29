# Release v0.1.0-community

## Highlights

First public release of Valo Community Edition:

- `POST /analyze` with deterministic prompt-injection scoring
- YAML rule engine and governance policies (`allow` / `warn` / `deny`)
- OpenAI-compatible proxy in **monitor** mode
- PDF scan reports
- Plugin loader
- Docker Compose stack (`docker-compose.yml`)
- Web UI: Playground, Policies, Rules, Analysis, Firewall

## Not included

- Portfolio rollups (`/portfolio/*`)
- AI Firewall **enforce** mode
- Executive dashboard, reporting automation, playbooks, learning loop
- Custom report branding

These capabilities are part of Valo Enterprise.

## Verify

```bash
docker compose up --build
python scripts/community_smoke.py
```
