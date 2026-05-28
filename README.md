# Valo Community Edition

Open-source, self-hostable AI input risk analysis and monitor-mode AI Firewall.

This repository is the **public Community Edition**. The full enterprise product
(portfolio rollups, enforce mode, executive dashboard, playbooks, learning loop)
lives in the private `valo` repository.

## Quick start

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| API + Swagger | http://localhost:8000/docs |
| Web UI | http://localhost:8080 |

First scan:

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"target":"quickstart","prompt":"Summarize this update in plain language."}'
```

Sample payloads: [`demo/community/README.md`](demo/community/README.md).

## What is included

- YAML rule engine + default prompt-injection rule pack
- `POST /analyze` deterministic risk scoring
- JSON + basic PDF reports (no custom branding)
- Governance policies (`/policies/*`, allow / warn / deny)
- OpenAI-compatible proxy in **monitor** mode (`POST /v1/proxy/chat/completions`)
- Plugin loader (`app/plugins/`)
- Web UI: Playground, Policies, Rules, Analysis, Firewall

## What is not in this repo (enterprise)

- Portfolio rollups, enforce-mode blocking, executive dashboard
- Reporting automation, playbooks, learning loop, correlation engine
- Custom report branding, SSO, multi-tenant, managed cloud

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
APP_EDITION=community APP_ENFORCEMENT_MODE=monitor \
  uvicorn app.main:app --reload
```

Web dev server:

```bash
cd web && npm install && VITE_VALO_EDITION=community npm run dev
```

## Tests and smoke

```bash
pytest tests/test_edition_community.py tests/test_health.py tests/test_api.py -v
python scripts/community_smoke.py
```

## Documentation

- [`docs/COMMUNITY_ARCHITECTURE.md`](docs/COMMUNITY_ARCHITECTURE.md)
- [`docs/COMMUNITY_OWASP_ATLAS.md`](docs/COMMUNITY_OWASP_ATLAS.md)
- [`docs/POLICY_ENGINE.md`](docs/POLICY_ENGINE.md)
- [`docs/threat_model.md`](docs/threat_model.md)
- [`UPSTREAM.md`](UPSTREAM.md) (syncing from the private `valo` repo)

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
