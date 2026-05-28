# Contributing to Valo

Thank you for contributing to Valo Community Edition.

## Development setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
APP_EDITION=community APP_ENFORCEMENT_MODE=monitor \
  uvicorn app.main:app --reload
```

## Tests

```bash
pytest tests/test_edition_community.py tests/test_api.py tests/test_pipeline.py -v
```

Full suite (enterprise defaults):

```bash
pytest tests/ -v
```

## Pull requests

- Keep changes focused; community edition must stay runnable with
  `docker compose up --build`.
- Do not commit secrets, `.env`, or `data/` artifacts.
- Update docs when adding public API surface.
