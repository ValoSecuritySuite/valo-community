# Valo Community Edition

Open-source, self-hostable AI input risk analysis and monitor-mode AI Firewall.

Valo Community Edition provides deterministic prompt-injection detection, YAML
governance policies, and an OpenAI-compatible proxy for observability. Valo
Enterprise extends this platform with enforce-mode blocking, portfolio analytics,
executive reporting, playbooks, and managed deployment options.

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

## Features

- YAML rule engine and default prompt-injection rule pack
- `POST /analyze` with deterministic risk scoring
- JSON and PDF scan reports
- Governance policies (`/policies/*`) with `allow`, `warn`, and `deny` decisions
- OpenAI-compatible proxy in **monitor** mode (`POST /v1/proxy/chat/completions`)
- Plugin loader (`app/plugins/`)
- Web UI: Playground, Policies, Rules, Analysis, Firewall

## Enterprise capabilities

The following are available in Valo Enterprise under valosecurity.ai, and not in this release:

- Portfolio rollups and multi-tenant analytics
- AI Firewall **enforce** mode (request blocking)
- Executive dashboard and automated reporting
- Playbooks, learning loop, and correlation engine integrations
- Custom report branding, SSO, and managed cloud hosting

## Local development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Web UI (development):

```bash
cd web && npm install && npm run dev
```

## Tests

```bash
pytest tests/test_edition_community.py tests/test_health.py tests/test_api.py -v
python scripts/community_smoke.py
```

## Documentation

- [`docs/COMMUNITY_ARCHITECTURE.md`](docs/COMMUNITY_ARCHITECTURE.md)
- [`docs/COMMUNITY_OWASP_ATLAS.md`](docs/COMMUNITY_OWASP_ATLAS.md)
- [`docs/POLICY_ENGINE.md`](docs/POLICY_ENGINE.md)
- [`docs/threat_model.md`](docs/threat_model.md)

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
